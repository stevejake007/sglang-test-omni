"""Shared helpers for the review-pr agent. Stdlib only, no third-party deps.

Every helper here is used by at least two scripts in this package, so it
lives in one module instead of being duplicated per script.
"""

import hashlib
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

RULES_VERSION = "1.0.0"
REVIEW_AGENT_ROOT = Path(__file__).resolve().parents[1]

PERF_KEYWORDS = (
    "faster",
    "speedup",
    "throughput",
    "latency",
    "perf",
    "optimize",
    "x faster",
    "x speedup",
    "2x",
    "3x",
    "4x",
    "%",
    "rps",
    "tokens/s",
    "tok/s",
    "ms",
    "reduce",
    "boost",
)

PERF_NUMBER_RE = re.compile(
    r"\d+(\.\d+)?\s*(rps|tokens/s|tok/s|gbps|gb/s|mb/s|ms|sec|min|req|tok|tokens|s)\b",
    re.IGNORECASE,
)

PERF_CLAIM_RE = re.compile(
    r"(faster|speedup|throughput|latency|boost|x\s*faster|x\s*speedup)\b",
    re.IGNORECASE,
)

REQUIRED_BODY_SECTIONS = (
    "summary",
    "validation",
    "untested",
)

CI_FAILED_CONCLUSIONS = {"failure", "cancelled", "timed_out", "action_required"}
CI_INCONCLUSIVE_CONCLUSIONS = {"skipped", "neutral", "pending", "queued", "startup_failure"}

MODEL_PATH_HINTS = ("/models/", "model_capabilities")
RUNTIME_PATH_HINTS = ("sglang_omni/", "sglang_omni_mlx/", "sglang_omni_router/", "playground/")
CONFIG_PATH_HINTS = ("/config/", "pyproject", "config.py", "setup.cfg")
TEST_PATH_HINTS = ("tests/", "test_", "unit_test", ".test")
DOCS_PATH_HINTS = ("docs/", ".mdx", ".rst", "cookbook")
CI_PATH_HINTS = (".github/", "workflow")
BENCH_PATH_HINTS = ("benchmarks/", "benchmark/")

API_ROOT = "https://api.github.com"
RAW_ROOT = "https://raw.githubusercontent.com"


class ApiError(RuntimeError):
    """Raised when a GitHub API request fails."""


def resolve_token():
    """Return a GitHub token from the environment or the macOS keychain.

    The keychain lookup is best effort and macOS only; it never raises.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        out = subprocess.run(
            ["security", "find-internet-password", "-s", "github.com", "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def api_get(path, token, params=None):
    """GET a GitHub REST API path and return parsed JSON."""
    url = f"{API_ROOT}{path}"
    if params:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ApiError(f"GET {url} failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"GET {url} failed: {exc.reason}") from exc


def raw_get(repo, ref, path, token):
    """GET a raw file at a ref. Returns text, or None when the file is gone."""
    url = f"{RAW_ROOT}/{repo}/{ref}/{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github.raw+json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def canonical_json(obj):
    """Serialize an object to compact, key-sorted JSON bytes."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def input_hash(parts):
    """One sha256 over the frozen review inputs.

    Parts is a dict; keys are sorted so the hash is stable across runs.
    Changed evidence on the same commit changes the hash and counts as a
    new review input.
    """
    return hashlib.sha256(canonical_json(parts)).hexdigest()


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, ensure_ascii=False, indent=2, sort_keys=True)


def classify_file(path):
    """Map a repo file path to one of the review categories."""
    lowered = path.lower()
    if any(hint in lowered for hint in TEST_PATH_HINTS):
        return "test"
    if any(hint in lowered for hint in DOCS_PATH_HINTS):
        return "docs"
    if any(hint in lowered for hint in CI_PATH_HINTS):
        return "ci"
    if any(hint in lowered for hint in BENCH_PATH_HINTS):
        return "benchmark"
    if any(hint in lowered for hint in MODEL_PATH_HINTS):
        return "model"
    if any(hint in lowered for hint in CONFIG_PATH_HINTS):
        return "config"
    if any(hint in lowered for hint in RUNTIME_PATH_HINTS):
        return "runtime"
    return "other"


def has_perf_claim(text):
    """True when the text contains a performance claim phrase."""
    return bool(PERF_CLAIM_RE.search(text or ""))


def has_perf_numbers(text):
    """True when the text contains a number with a comparable unit."""
    return bool(PERF_NUMBER_RE.search(text or ""))
