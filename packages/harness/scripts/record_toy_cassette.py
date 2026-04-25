"""Re-record the toy_homepage cassette against a real CLI runtime (impl plan T3.3).

The cassette under ``tests/cassettes/toy_homepage_<runtime>/`` is the
canonical per-runtime recording the e2e replay suite consumes. Re-record
when prompts, ``AGENTS.md``, or runtime stream contracts change.

Usage:

```
uv run python -m scripts.record_toy_cassette --runtime claude_code
uv run python -m scripts.record_toy_cassette --runtime pi
```

The script delegates to the toy-scenario helpers used by the smoke tests
(``tests/smoke/_toy_scenario.py``) so the planner/executor prompts
remain in one place. ``ReplayRuntime`` runs in record mode
(``HARNESS_RECORD=1``) with the chosen real runtime as fallback,
materialising a fresh cassette directory matching spec §5.6.

The script aborts (non-zero exit) if the run does not terminate with
``FinalStatus.COMPLETED`` so a botched recording cannot silently land
in the repo.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

_HARNESS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HARNESS_ROOT / "tests"))

from smoke._toy_scenario import build_config  # noqa: E402

from harness.config import FinalStatus  # noqa: E402
from harness.loop import run_plan_exec_loop  # noqa: E402
from harness.runtimes import get_runtime  # noqa: E402
from harness.runtimes.replay import ReplayRuntime  # noqa: E402

_CASSETTE_ROOT = _HARNESS_ROOT / "tests" / "cassettes"
_RUNTIMES = ("claude_code", "pi")
_DEFAULT_TIMEOUT_SECONDS = 600.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--runtime",
        required=True,
        choices=_RUNTIMES,
        help="Real runtime name to drive the recording.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=_DEFAULT_TIMEOUT_SECONDS,
        help="Per-iteration wall-clock budget in seconds.",
    )
    parser.add_argument(
        "--keep-run-dir",
        action="store_true",
        help="Preserve the temporary run_dir after recording (default: delete).",
    )
    return parser.parse_args()


def _record(runtime_name: str, timeout: float, keep_run_dir: bool) -> int:
    cassette_dir = _CASSETTE_ROOT / f"toy_homepage_{runtime_name}"
    cassette_dir.mkdir(parents=True, exist_ok=True)

    fallback = get_runtime(runtime_name)
    runtime = ReplayRuntime(cassette_dir, fallback=fallback)

    run_dir = Path(tempfile.mkdtemp(prefix=f"harness-record-{runtime_name}-"))
    # The harness owns run_dir and rejects pre-existing contents; mkdtemp
    # gives us an empty path with a unique name.
    shutil.rmtree(run_dir)

    os.environ["HARNESS_RECORD"] = "1"
    config = build_config(run_dir, timeout=timeout)
    print(f"[record] runtime={runtime_name} cassette={cassette_dir} run_dir={run_dir}")
    result = run_plan_exec_loop(config, runtime)
    print(
        f"[record] final_status={result.final_status.value} "
        f"plan_iters={result.plan_iter_count} exec_iters={result.exec_iter_count}"
    )

    if not keep_run_dir and run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)

    if result.final_status is not FinalStatus.COMPLETED:
        print(
            f"[record] ABORT: expected COMPLETED, got {result.final_status.value}; "
            "cassette may be partial. Inspect run_dir or rerun with --keep-run-dir.",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    args = _parse_args()
    return _record(args.runtime, args.timeout, args.keep_run_dir)


if __name__ == "__main__":
    sys.exit(main())
