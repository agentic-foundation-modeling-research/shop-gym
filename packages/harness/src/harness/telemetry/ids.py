"""Iteration ids and per-iteration directories (spec §5.3).

Single source of truth for naming the planner directory (`iters/plan/`)
and the zero-padded executor directories (`iters/exec-0001/`, ...).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from harness.workspace import Workspace

PLAN_ITER_ID: Final[str] = "plan"
"""Iteration id of the single planner iteration."""

_EXEC_ITER_ID_RE: Final[re.Pattern[str]] = re.compile(r"^exec-\d{4}$")


def exec_iter_id(n: int) -> str:
    """Return the canonical executor iteration id for the n-th executor run.

    Args:
        n: 1-indexed executor iteration ordinal.

    Returns:
        ``"exec-NNNN"`` zero-padded to four digits.

    Raises:
        ValueError: If `n` is less than 1.
    """
    if n < 1:
        raise ValueError(f"executor iteration index must be >= 1, got {n}")
    return f"exec-{n:04d}"


def iter_dir(workspace: Workspace, iter_id: str) -> Path:
    """Return the per-iteration directory under `iters/` for `iter_id`.

    Args:
        workspace: The run workspace.
        iter_id: Either `PLAN_ITER_ID` or an `exec-NNNN` id.

    Returns:
        Path to `<run_dir>/iters/<iter_id>/`. The directory is *not*
        created; callers that need it on disk should call `mkdir`.

    Raises:
        ValueError: If `iter_id` is not a recognised planner or executor id.
    """
    if iter_id != PLAN_ITER_ID and _EXEC_ITER_ID_RE.match(iter_id) is None:
        raise ValueError(f"unrecognised iter_id: {iter_id!r}")
    return workspace.iters_dir / iter_id
