#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Lint the Cookbook sidebar order in docs/index.rst. Checking does not rewrite files.

The Cookbook toctree in docs/index.rst must follow the model order defined for
PR #2876 (sgl-project/sglang-omni#2876), which mirrors the SGLang-Omni Roadmap
#1081:

  1. Roadmap part: the models listed under **Focus -> Supporting** in #1081,
     in that exact order (ROADMAP_ORDER below).
  2. Downloads part: every remaining cookbook entry, sorted by Hugging Face
     download counts in descending order (DOWNLOADS_DESC below).

New models are supported without touching the checking logic:

  * A new model under the #1081 roadmap: insert it into ROADMAP_ORDER at its
    roadmap position.
  * Any other new model: add it to DOWNLOADS_DESC with its Hugging Face
    download count and place the cookbook entry so that the downloads part
    stays in descending order. The lint verifies that constraint directly, so
    the exact insertion point is chosen by the download count, not hard-coded.

Missing, extra, duplicate, unknown, or misplaced entries are violations and
fail CI. There is no noqa exemption.

Run without arguments to check docs/index.rst, or pass explicit paths.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = REPO_ROOT / "docs" / "index.rst"

# Models listed under **Focus -> Supporting** in sgl-project/sglang-omni#1081,
# in that exact order. Qwen3-TTS Base and CustomVoice share one cookbook page.
# New roadmap models: insert here at their #1081 position; the cookbook toctree
# must then list the same prefix in the same order.
ROADMAP_ORDER = [
    "cookbook/qwen3_tts.md",
    "cookbook/moss_tts.md",
    "cookbook/whisper_asr.md",
    "cookbook/nemotron3_5_asr.md",
    "cookbook/moss_transcribe_diarize.md",
    "cookbook/fishaudio_s2_pro.md",
    "cookbook/cosmos3_nano.md",
    "cookbook/qwen3_omni.md",
    "cookbook/fun_cosyvoice3.md",
    "cookbook/personaplex.md",
    "cookbook/minicpm_o.md",
    "cookbook/llada2_uni.md",
]

# Hugging Face download counts (queried October 2026) for every cookbook entry
# that is NOT part of the roadmap. The downloads part of the toctree must be
# sorted by these counts in descending order. New non-roadmap models: add a
# line here with the current download count and insert the cookbook entry at
# the position the count implies.
DOWNLOADS_DESC = {
    "cookbook/qwen3_asr.md": 1_127_141,
    "cookbook/fun_asr.md": 152_655,
    "cookbook/higgs_tts.md": 123_139,
    "cookbook/moss_tts_local.md": 114_752,
    "cookbook/nemotron_diarization.md": 90_352,
    "cookbook/minimax_music3.md": 6_224,
    "cookbook/fishaudio_drama3.md": 6_158,
    "cookbook/ming_omni.md": 5_114,
    "cookbook/nemotron_voicechat.md": 4_659,
    "cookbook/auk.md": 2_695,
    "cookbook/arkasr.md": 2_608,
    "cookbook/zonos2.md": 2_346,
    "cookbook/voxtral_tts.md": 1_561,
    "cookbook/dots_tts.md": 746,
    "cookbook/ming_tts.md": 318,
}

ROADMAP_SET = frozenset(ROADMAP_ORDER)
DOWNLOAD_SET = frozenset(DOWNLOADS_DESC)
EXPECTED_COUNT = len(ROADMAP_ORDER) + len(DOWNLOADS_DESC)

_ENTRY_RE = re.compile(r"^   (cookbook/[a-z0-9_.-]+\.md)$")


@dataclass(frozen=True)
class Violation:
    path: Path
    lineno: int
    col: int
    rule: str
    detail: str


def repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def resolve_targets(raw_paths: list[str]) -> list[Path]:
    if not raw_paths:
        return [DEFAULT_TARGET]
    else:
        return [Path(item) for item in raw_paths]


def extract_cookbook_entries(source: str) -> tuple[list[str], dict[str, int]]:
    """Return (entries, lineno_by_entry) for the Cookbook toctree block."""
    lines = source.splitlines()
    entries: list[str] = []
    lineno_by_entry: dict[str, int] = {}
    in_cookbook = False
    for lineno, line in enumerate(lines, start=1):
        if line.startswith(".. toctree::"):
            in_cookbook = False
            continue
        if line.strip() == ":caption: Cookbook":
            in_cookbook = True
            continue
        if not in_cookbook:
            continue
        if not line.strip():
            continue
        match = _ENTRY_RE.match(line)
        if match:
            entry = match.group(1)
            entries.append(entry)
            lineno_by_entry[entry] = lineno
        else:
            break
    return entries, lineno_by_entry


def check_source(path: Path, source: str) -> list[Violation]:
    violations: list[Violation] = []
    entries, lineno_by_entry = extract_cookbook_entries(source)

    if not entries:
        violations.append(
            Violation(path, 1, 1, "cookbook-order", "Cookbook toctree block not found")
        )
        return violations

    # Duplicates.
    seen: set[str] = set()
    for entry in entries:
        if entry in seen:
            lineno = lineno_by_entry.get(entry, 1)
            violations.append(
                Violation(path, lineno, 1, "cookbook-order", f"duplicate entry '{entry}'")
            )
        else:
            seen.add(entry)

    # Unknown entries and models placed in the wrong part.
    expected_set = ROADMAP_SET | DOWNLOAD_SET
    actual_set = set(entries)
    for entry in sorted(actual_set - expected_set):
        lineno = lineno_by_entry.get(entry, 1)
        violations.append(
            Violation(
                path,
                lineno,
                1,
                "cookbook-order",
                f"unknown entry '{entry}': add it to ROADMAP_ORDER (roadmap model) "
                "or DOWNLOADS_DESC (with its HF download count) in scripts/check_cookbook_order.py",
            )
        )
    for index, entry in enumerate(entries):
        if entry in ROADMAP_SET and index >= len(ROADMAP_ORDER):
            lineno = lineno_by_entry.get(entry, 1)
            violations.append(
                Violation(
                    path,
                    lineno,
                    1,
                    "cookbook-order",
                    f"'{entry}' is a roadmap (#1081) model and must be in the roadmap part "
                    f"(first {len(ROADMAP_ORDER)} entries), not in the downloads part",
                )
            )

    # Missing entries.
    for entry in sorted(expected_set - actual_set):
        violations.append(
            Violation(
                path,
                1,
                1,
                "cookbook-order",
                f"missing entry '{entry}' (removed from the cookbook toctree, or not yet added)",
            )
        )

    # Roadmap part: exact positional match.
    roadmap_part = entries[: len(ROADMAP_ORDER)]
    for index, (actual, expected) in enumerate(zip(roadmap_part, ROADMAP_ORDER)):
        if actual != expected:
            lineno = lineno_by_entry.get(actual, 1)
            violations.append(
                Violation(
                    path,
                    lineno,
                    1,
                    "cookbook-order",
                    f"roadmap position {index + 1}: expected '{expected}', got '{actual}'",
                )
            )
            break

    # Downloads part: descending-order constraint instead of a fixed sequence,
    # so a new model just has to be inserted where its download count implies.
    downloads_part = entries[len(ROADMAP_ORDER) :]
    for index, (first, second) in enumerate(zip(downloads_part, downloads_part[1:])):
        if first not in DOWNLOADS_DESC or second not in DOWNLOADS_DESC:
            continue
        first_count = DOWNLOADS_DESC[first]
        second_count = DOWNLOADS_DESC[second]
        if first_count < second_count:
            lineno = lineno_by_entry.get(first, 1)
            violations.append(
                Violation(
                    path,
                    lineno,
                    1,
                    "cookbook-order",
                    f"downloads not in descending order at downloads position {index + 1}: "
                    f"'{first}' ({first_count:,}) must come before '{second}' ({second_count:,})",
                )
            )
            break
    return violations


def check_file(path: Path) -> list[Violation]:
    source = path.read_text(encoding="utf-8")
    return check_source(path, source)


def report_violations(violations: list[Violation]) -> int:
    if not violations:
        print(
            f"OK: cookbook order matches PR #2876 "
            f"({len(ROADMAP_ORDER)} roadmap + {len(DOWNLOADS_DESC)} downloads entries)"
        )
        return 0
    else:
        for v in violations:
            print(f"{repo_relative(v.path)}:{v.lineno}: {v.rule}: {v.detail}")
        print(
            f"cookbook order check failed with {len(violations)} violation(s)",
            file=sys.stderr,
        )
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="*", help="Files to check (defaults to docs/index.rst)"
    )
    parser.add_argument(
        "--print-expected",
        action="store_true",
        help="Print the expected cookbook order (roadmap part, then downloads part "
        "sorted by HF downloads) and exit without checking",
    )
    args = parser.parse_args(argv)
    if args.print_expected:
        downloads_sorted = sorted(DOWNLOADS_DESC, key=DOWNLOADS_DESC.__getitem__, reverse=True)
        for entry in ROADMAP_ORDER + downloads_sorted:
            print(entry)
        return 0
    targets = resolve_targets(args.paths)
    violations: list[Violation] = []
    for path in targets:
        if not path.is_file():
            print(f"{path}: not a file; skipped", file=sys.stderr)
        else:
            violations.extend(check_file(path))
    return report_violations(violations)


if __name__ == "__main__":
    raise SystemExit(main())
