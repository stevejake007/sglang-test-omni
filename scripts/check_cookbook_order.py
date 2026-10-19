#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Lint the Cookbook sidebar order in docs/index.rst. Checking does not rewrite files.

The Cookbook toctree in docs/index.rst must list cookbook pages in the model
order defined for PR #2876 (sgl-project/sglang-omni#2876), which mirrors the
SGLang-Omni Roadmap #1081:

  1. Roadmap part: the models listed under **Focus -> Supporting** in #1081,
     in that exact order (12 entries).
  2. Downloads part: every remaining cookbook entry, sorted by Hugging Face
     download counts in descending order (15 entries).

Any missing, extra, duplicate, or misplaced entry is a violation and fails CI.
There is no noqa exemption.

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

# Remaining cookbook entries, sorted by Hugging Face download counts in
# descending order (queried October 2026).
DOWNLOADS_ORDER = [
    "cookbook/qwen3_asr.md",
    "cookbook/fun_asr.md",
    "cookbook/higgs_tts.md",
    "cookbook/moss_tts_local.md",
    "cookbook/nemotron_diarization.md",
    "cookbook/minimax_music3.md",
    "cookbook/fishaudio_drama3.md",
    "cookbook/ming_omni.md",
    "cookbook/nemotron_voicechat.md",
    "cookbook/auk.md",
    "cookbook/arkasr.md",
    "cookbook/zonos2.md",
    "cookbook/voxtral_tts.md",
    "cookbook/dots_tts.md",
    "cookbook/ming_tts.md",
]

EXPECTED_ORDER = ROADMAP_ORDER + DOWNLOADS_ORDER

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

    # Missing and unexpected entries.
    expected_set = set(EXPECTED_ORDER)
    actual_set = set(entries)
    for entry in EXPECTED_ORDER:
        if entry not in actual_set:
            violations.append(
                Violation(path, 1, 1, "cookbook-order", f"missing entry '{entry}'")
            )
    for entry in sorted(actual_set - expected_set):
        lineno = lineno_by_entry.get(entry, 1)
        violations.append(
            Violation(path, lineno, 1, "cookbook-order", f"unexpected entry '{entry}'")
        )

    # Positional order: report the first mismatch to keep the report readable.
    for index, (actual, expected) in enumerate(zip(entries, EXPECTED_ORDER)):
        if actual != expected:
            lineno = lineno_by_entry.get(actual, 1)
            violations.append(
                Violation(
                    path,
                    lineno,
                    1,
                    "cookbook-order",
                    f"position {index + 1}: expected '{expected}', got '{actual}'",
                )
            )
            break
    return violations


def check_file(path: Path) -> list[Violation]:
    source = path.read_text(encoding="utf-8")
    return check_source(path, source)


def report_violations(violations: list[Violation]) -> int:
    if not violations:
        print(f"OK: cookbook order matches PR #2876 ({len(EXPECTED_ORDER)} entries)")
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
    args = parser.parse_args(argv)
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
