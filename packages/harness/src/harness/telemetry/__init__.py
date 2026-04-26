"""Run-level telemetry subpackage: ids, secret scrubbing, run.json, recovery.

Re-exports the public telemetry API so callers and tests can keep their
existing ``from harness.telemetry import …`` imports working::

    from harness.telemetry import (
        PLAN_ITER_ID,
        RunSummaryWriter,
        exec_iter_id,
        iter_dir,
        reconstruct,
        scrub_secrets,
    )

The submodules (`ids`, `secrets`, `summary`, `recovery`) split the four
concerns the original `telemetry.py` carried — see their individual
docstrings for spec references.
"""

from __future__ import annotations

from harness.telemetry.ids import PLAN_ITER_ID, exec_iter_id, iter_dir
from harness.telemetry.recovery import reconstruct
from harness.telemetry.secrets import scrub_secrets
from harness.telemetry.summary import RunSummaryWriter

__all__ = [
    "PLAN_ITER_ID",
    "RunSummaryWriter",
    "exec_iter_id",
    "iter_dir",
    "reconstruct",
    "scrub_secrets",
]
