# SPDX-License-Identifier: Apache-2.0
"""MOSS-TD speculative sweep: client payload mapping, arg validation, reports."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from benchmarks.eval import speculative_sweep_moss_td as sweep
from benchmarks.metrics.speculative import MetricMean


def _sample_payload(*, concurrency: int = 8) -> dict[str, object]:
    return {
        "config": {
            "repo_id": "zhaochenyang20/googletime",
            "split": "validation",
            "model_path": "OpenMOSS-Team/MOSS-Transcribe-Diarize",
            "concurrency": concurrency,
            "wall_clock_s": 42.0,
        },
        "summary": {
            "total_samples": 25,
            "evaluated": 25,
            "skipped": 0,
            "exact_matches": 0,
            "mismatches": 25,
            "exact_match_rate": 0.0,
        },
        "speed": {
            "total_requests": 25,
            "completed_requests": 25,
            "failed_requests": 0,
            "latency_p95_s": 3.4,
            "audio_throughput_s_per_s": 123.4,
            "text_ttft_p95_s": 0.85,
            "text_ttft_mean_s": 0.62,
        },
        "diarization_metrics_percent": {
            "cer": 5.82,
            "speaker_timestamp_der": 21.06,
        },
        "per_sample": [],
    }


def test_client_result_maps_moss_td_payload() -> None:
    result = sweep._client_result_from_payload(8, _sample_payload())

    assert result.concurrency == 8
    assert result.total == 25
    assert result.skipped == 0
    assert result.failed == 0
    assert result.throughput_samples_per_s == MetricMean(mean=123.4)
    assert result.latency_p95_s == MetricMean(mean=3.4)
    # diarization_metrics_percent stores percent numbers; the sweep protocol
    # wants a fraction.
    assert result.corpus_wer == MetricMean(mean=0.0582)


def test_client_result_counts_failed_requests() -> None:
    payload = _sample_payload()
    payload["speed"] = {**payload["speed"], "failed_requests": 3}
    result = sweep._client_result_from_payload(4, payload)

    assert result.failed == 3


def test_client_result_tolerates_missing_metrics() -> None:
    payload = _sample_payload()
    payload["speed"] = {"failed_requests": 1}
    payload["diarization_metrics_percent"] = {}
    result = sweep._client_result_from_payload(4, payload)

    assert result.throughput_samples_per_s.mean is None
    assert result.latency_p95_s.mean is None
    assert result.corpus_wer.mean is None
    assert result.failed == 1


def test_parse_args_rejects_missing_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    with pytest.raises(SystemExit):
        sweep.parse_args(
            [
                "--draft-config",
                "examples/configs/moss_td_dflash.yaml",
                "--output-dir",
                "results/sweep/x",
            ]
        )


def test_parse_args_rejects_multiple_gpus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    with pytest.raises(SystemExit):
        sweep.parse_args(
            [
                "--draft-config",
                "examples/configs/moss_td_dflash.yaml",
                "--output-dir",
                "results/sweep/x",
            ]
        )


def test_parse_args_rejects_bad_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    with pytest.raises(SystemExit):
        sweep.parse_args(
            [
                "--draft-config",
                "examples/configs/moss_td_dflash.yaml",
                "--output-dir",
                "results/sweep/x",
                "--order",
                "AAA",
            ]
        )


def test_parse_args_parses_concurrencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    args = sweep.parse_args(
        [
            "--draft-config",
            "examples/configs/moss_td_dflash.yaml",
            "--output-dir",
            "results/sweep/x",
            "--concurrencies",
            "1,4,8",
            "--stream-concurrencies",
            "1,16",
        ]
    )

    assert args.concurrencies == [1, 4, 8]
    assert args.stream_concurrencies == [1, 16]
    assert args.dataset == "googletime"
    assert args.model_path == sweep.DEFAULT_MODEL_PATH


def test_run_client_pass_writes_client_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client is invoked against the running server with the sweep flags."""
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        pass_dir = Path(cmd[cmd.index("--output-dir") + 1])
        pass_dir.mkdir(parents=True, exist_ok=True)
        (pass_dir / sweep.RESULTS_FILE).write_text(
            json.dumps(
                _sample_payload(concurrency=int(cmd[cmd.index("--concurrency") + 1]))
            )
        )
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(sweep.subprocess, "run", fake_run)
    args = Namespace(
        dataset="googletime",
        model_path=sweep.DEFAULT_MODEL_PATH,
    )
    result = sweep.run_client_pass(
        leg_dir=tmp_path,
        concurrency=8,
        port=8700,
        args=args,
        stream=False,
    )

    assert result.concurrency == 8
    assert calls[-1][:4] == [
        sys_executable(),
        "-m",
        sweep.CLIENT_MODULE,
        "--dataset",
    ]
    command = calls[-1]
    assert "--use-existing-server" in command
    assert command[command.index("--concurrency") + 1] == "8"
    assert command[command.index("--port") + 1] == "8700"
    assert "--stream" not in command


def test_run_client_pass_adds_stream_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        pass_dir = Path(cmd[cmd.index("--output-dir") + 1])
        pass_dir.mkdir(parents=True, exist_ok=True)
        (pass_dir / sweep.RESULTS_FILE).write_text(
            json.dumps(_sample_payload(concurrency=16))
        )
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(sweep.subprocess, "run", fake_run)
    args = Namespace(dataset="googletime", model_path=sweep.DEFAULT_MODEL_PATH)
    sweep.run_client_pass(
        leg_dir=tmp_path,
        concurrency=16,
        port=8700,
        args=args,
        stream=True,
    )

    assert "--stream" in calls[-1]


def test_render_stream_table_reports_both_sides() -> None:
    baseline = {1: {"text_ttft_p95_s": 0.9, "text_ttft_mean_s": 0.5}}
    draft = {1: {"text_ttft_p95_s": 0.7, "text_ttft_mean_s": 0.4}}
    table = sweep._render_stream_table([("1_baseline", baseline), ("2_draft", draft)])

    assert "Streaming first text" in table
    assert "| 1 | 0.9 | 0.7 | 0.5 | 0.4 |" in table


def sys_executable() -> str:
    import sys

    return sys.executable
