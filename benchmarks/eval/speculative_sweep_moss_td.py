# SPDX-License-Identifier: Apache-2.0
"""Sweep the MOSS-TD DFlash draft against no draft across concurrency.

The seedtts-based ``speculative_sweep`` drives clients that speak its sweep
protocol (--output carrying a ClientPayload); the MOSS-TD benchmark client
(benchmarks.eval.benchmark_asr_transcribe_diarize) writes its own payload under
--output-dir instead, so this sweep drives it directly. Each leg starts a fresh
server, with or without the draft config, runs the client once per concurrency
level with --use-existing-server, and stops the server. Legs run one after
another in the order given, ABBA by default, so drift between runs shows as a
gap between the two legs of one side.

The summary gives, per concurrency, both sides' audio throughput (audio s/s),
the gain, p95 latency and its change, CER and failed requests; then k, the
loads where the draft is worse than no draft, and per leg the startup time, KV
pool, peak token usage, retractions and acceptance length. sweep.json holds the
same comparison. With --stream-concurrencies set (comma-separated), each leg
runs an extra streaming pass at those loads and the report adds a streaming
first-text (text_ttft) table.

Set CUDA_VISIBLE_DEVICES to one GPU that nothing else uses: after each leg the
managed server ends every process still using it. Engine settings other than
the draft belong in the configs, so both legs get them; --baseline-config takes
the no-draft one.

Usage:

    CUDA_VISIBLE_DEVICES=0 python -m benchmarks.eval.speculative_sweep_moss_td \\
        --model-path OpenMOSS-Team/MOSS-Transcribe-Diarize \\
        --draft-config examples/configs/moss_td_dflash.yaml \\
        --output-dir results/sweep/moss_td_googletime \\
        --dataset googletime
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from benchmarks.benchmarker.utils import managed_omni_server
from benchmarks.metrics.speculative import (
    K_GAIN,
    ROADMAP_CONCURRENCIES,
    ClientResources,
    ClientResult,
    Leg,
    MetricMean,
    Side,
    compare,
    read_server_log,
    render,
)

logger = logging.getLogger(__name__)

SIDE_BY_LETTER: dict[str, Side] = {"A": "baseline", "B": "draft"}
HOST = "127.0.0.1"
DEFAULT_MODEL_PATH = "OpenMOSS-Team/MOSS-Transcribe-Diarize"
RESULTS_FILE = "transcribe_diarize_results.json"

CLIENT_MODULE = "benchmarks.eval.benchmark_asr_transcribe_diarize"
DRIVER_CLIENT_FLAGS = ("--host", "--port", "--model-path", "--output-dir")


def _client_result_from_payload(
    concurrency: int,
    payload: dict[str, object],
) -> ClientResult:
    """Map one MOSS-TD client run onto the shared sweep protocol.

    Throughput is the client's audio throughput (audio seconds per second),
    matching the roadmap Results rows. CER comes from diarization_metrics_percent,
    which stores percent numbers (5.82 means 5.82%), so it is divided by 100 to
    fit the corpus_wer fraction used by the renderer.
    """
    speed = payload["speed"]
    assert isinstance(speed, dict)
    diarization = payload["diarization_metrics_percent"]
    assert isinstance(diarization, dict)
    summary = payload["summary"]
    assert isinstance(summary, dict)

    def number_from(section: dict[str, object], key: str) -> float | None:
        value = section.get(key)
        return value if isinstance(value, (int, float)) else None

    cer_percent = number_from(diarization, "cer")
    return ClientResult(
        concurrency=concurrency,
        total=int(summary["total_samples"]),
        skipped=int(summary["skipped"]),
        failed=int(number_from(speed, "failed_requests") or 0),
        throughput_samples_per_s=MetricMean(
            mean=number_from(speed, "audio_throughput_s_per_s")
        ),
        latency_p95_s=MetricMean(mean=number_from(speed, "latency_p95_s")),
        corpus_wer=MetricMean(
            mean=cer_percent / 100.0 if cer_percent is not None else None
        ),
        resources=ClientResources(gpu_memory_used_peak_mib=None),
    )


def run_client_pass(
    *,
    leg_dir: Path,
    concurrency: int,
    port: int,
    args: argparse.Namespace,
    stream: bool,
) -> ClientResult:
    """Run the MOSS-TD client once against the running server and map its result."""
    pass_dir = leg_dir / ("stream" if stream else "plain") / f"c{concurrency}"
    pass_dir.mkdir(parents=True)
    client_log = pass_dir / "client.log"
    cmd = [
        sys.executable,
        "-m",
        CLIENT_MODULE,
        "--dataset",
        args.dataset,
        "--use-existing-server",
        "--host",
        HOST,
        "--port",
        str(port),
        "--model-path",
        args.model_path,
        "--concurrency",
        str(concurrency),
        "--output-dir",
        str(pass_dir),
        "--disable-tqdm",
    ]
    if stream:
        cmd.append("--stream")
    logger.info(
        f"[c={concurrency}{', stream' if stream else ''}] client: {' '.join(cmd)}"
    )
    with open(client_log, "w") as log:
        completed = subprocess.run(
            cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    results_path = pass_dir / RESULTS_FILE
    if not results_path.exists():
        raise RuntimeError(
            f"client left no {RESULTS_FILE} at {results_path} "
            f"(exit {completed.returncode}); see {client_log}"
        )
    payload = json.loads(results_path.read_text())
    return _client_result_from_payload(concurrency, payload)


def run_stream_pass(
    *,
    leg_dir: Path,
    port: int,
    args: argparse.Namespace,
    stream_concurrencies: list[int],
) -> dict[int, dict[str, object]]:
    """Streaming first-text pass at selected loads; needs a live server."""
    out: dict[int, dict[str, object]] = {}
    for concurrency in stream_concurrencies:
        result = run_client_pass(
            leg_dir=leg_dir,
            concurrency=concurrency,
            port=port,
            args=args,
            stream=True,
        )
        payload_path = leg_dir / "stream" / f"c{concurrency}" / RESULTS_FILE
        speed = json.loads(payload_path.read_text())["speed"]
        assert isinstance(speed, dict)
        out[concurrency] = {
            "result": result,
            "text_ttft_p95_s": speed.get("text_ttft_p95_s"),
            "text_ttft_mean_s": speed.get("text_ttft_mean_s"),
        }
    return out


def run_leg(
    *,
    name: str,
    side: Side,
    port: int,
    args: argparse.Namespace,
) -> tuple[Leg, dict[int, dict[str, object]]]:
    leg_dir = args.output_dir / name
    leg_dir.mkdir(exist_ok=True)
    server_log = leg_dir / "server.log"
    started = time.monotonic()
    stream_data: dict[int, dict[str, object]] = {}
    with managed_omni_server(
        model_path=args.model_path,
        port=port,
        host=HOST,
        log_file=server_log,
        server_config=args.draft_config if side == "draft" else args.baseline_config,
    ):
        startup_s = time.monotonic() - started
        logger.info(f"{name}: server ready in {startup_s:.1f} s")
        results = [
            run_client_pass(
                leg_dir=leg_dir,
                concurrency=concurrency,
                port=port,
                args=args,
                stream=False,
            )
            for concurrency in args.concurrencies
        ]
        if args.stream_concurrencies:
            stream_data = run_stream_pass(
                leg_dir=leg_dir,
                port=port,
                args=args,
                stream_concurrencies=args.stream_concurrencies,
            )
    return (
        Leg(
            name=name,
            side=side,
            startup_s=startup_s,
            server=read_server_log(server_log.read_text(errors="replace")),
            results=results,
        ),
        stream_data,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model-path", default=DEFAULT_MODEL_PATH)
    parser.add_argument(
        "--draft-config", required=True, help="Server config that adds the draft."
    )
    parser.add_argument(
        "--baseline-config",
        default=None,
        help="Server config without the draft; the model's defaults when omitted.",
    )
    parser.add_argument(
        "--dataset",
        default="googletime",
        help="MOSS-TD dataset preset passed to the client (googletime, ...).",
    )
    parser.add_argument(
        "--concurrencies",
        default=",".join(str(value) for value in ROADMAP_CONCURRENCIES),
        help="Comma-separated concurrency levels to sweep.",
    )
    parser.add_argument(
        "--stream-concurrencies",
        default="",
        help=(
            "Comma-separated concurrency levels that also run an SSE streaming "
            "pass, whose first-text latency is reported per side. "
            "Example: 1,16."
        ),
    )
    parser.add_argument(
        "--order", default="ABBA", help="A runs without the draft, B with it."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8700,
        help="The first leg's port; each later leg takes the next.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    args.concurrencies = [
        int(value) for value in args.concurrencies.split(",") if value.strip()
    ]
    args.stream_concurrencies = [
        int(value) for value in args.stream_concurrencies.split(",") if value.strip()
    ]
    visible_gpus = [
        gpu
        for gpu in os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",")
        if gpu.strip()
    ]
    if len(visible_gpus) != 1:
        parser.error("set CUDA_VISIBLE_DEVICES to the one GPU the sweep owns")
    elif set(args.order) != set(SIDE_BY_LETTER):
        parser.error("--order needs at least one A and one B, and no other letters")
    elif not args.concurrencies:
        parser.error("--concurrencies cannot be empty")
    else:
        pass
    return args


def _render_stream_table(
    stream_by_leg: list[tuple[str, dict[int, dict[str, object]]]],
) -> str:
    lines = [
        "",
        "## Streaming first text",
        "",
        "text_ttft is the first transcript delta on an SSE stream. "
        "Throughput and CER are the streaming pass's own.",
        "",
        "| c | No draft ttft p95 (s) | Draft ttft p95 (s) | No draft ttft mean (s) | Draft ttft mean (s) |",
        "|---:|---:|---:|---:|---:|",
    ]
    baseline = stream_by_leg[0][1]
    draft = stream_by_leg[1][1]
    for concurrency in sorted(baseline):
        lines.append(
            f"| {concurrency} "
            f"| {baseline[concurrency]['text_ttft_p95_s']} "
            f"| {draft[concurrency]['text_ttft_p95_s']} "
            f"| {baseline[concurrency]['text_ttft_mean_s']} "
            f"| {draft[concurrency]['text_ttft_mean_s']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    args = parse_args(sys.argv[1:])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    legs = []
    stream_by_leg: list[tuple[str, dict[int, dict[str, object]]]] = []
    for index, letter in enumerate(args.order):
        side = SIDE_BY_LETTER[letter]
        name = f"{index + 1}_{side}"
        leg, stream_data = run_leg(
            name=name,
            side=side,
            port=args.port + index,
            args=args,
        )
        legs.append(leg)
        if stream_data:
            stream_by_leg.append((name, stream_data))
    comparison = compare(legs, k_gain=K_GAIN)
    summary = render(comparison, legs, title=Path(args.draft_config).stem)
    if args.stream_concurrencies:
        summary += _render_stream_table(stream_by_leg)
    (args.output_dir / "summary.md").write_text(summary)
    sweep = {
        "arguments": vars(args),
        "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
        "legs": [
            {"name": leg.name, "startup_s": leg.startup_s, **asdict(leg.server)}
            for leg in legs
        ],
        "comparison": asdict(comparison),
        "streaming": {
            name: {
                str(concurrency): {
                    "result": asdict(entry["result"]),
                    "text_ttft_p95_s": entry["text_ttft_p95_s"],
                    "text_ttft_mean_s": entry["text_ttft_mean_s"],
                }
                for concurrency, entry in entries.items()
            }
            for name, entries in stream_by_leg
        },
    }
    (args.output_dir / "sweep.json").write_text(
        json.dumps(sweep, indent=2, default=str)
    )
    print(summary)


if __name__ == "__main__":
    main()
