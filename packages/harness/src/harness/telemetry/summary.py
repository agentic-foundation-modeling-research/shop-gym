"""Atomic writer for `<run_dir>/run.json` (spec §5.7).

`run.json` is rewritten in full after every iteration. The payload is
the serialised `PlanExecLoopResult` augmented with an optional
``config_snapshot`` field carrying the secret-free echo of the
caller-supplied configuration.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from harness.config import PlanExecLoopResult
from harness.telemetry.secrets import scrub_secrets
from harness.workspace import atomic_write_json


class RunSummaryWriter:
    """Atomic writer for `run_dir/run.json` (spec §5.7).

    `run.json` is rewritten in full after every iteration. The payload
    is the serialised `PlanExecLoopResult` augmented with an optional
    ``config_snapshot`` field carrying the secret-free echo of the
    caller-supplied configuration.
    """

    @staticmethod
    def rewrite(
        run_dir: Path,
        *,
        result: PlanExecLoopResult,
        config_snapshot: Mapping[str, Any] | None = None,
    ) -> None:
        """Atomically rewrite `<run_dir>/run.json`.

        Args:
            run_dir: Run workspace root. Must already exist.
            result: Authoritative result for this run, in its current
                state. Serialised verbatim.
            config_snapshot: Optional caller-supplied configuration echo.
                If given, it is deep-copied with `scrub_secrets` and
                stored under the top-level ``config_snapshot`` key.
        """
        payload: dict[str, Any] = result.model_dump(mode="json")
        if config_snapshot is not None:
            payload["config_snapshot"] = scrub_secrets(dict(config_snapshot))
        atomic_write_json(run_dir / "run.json", payload)
