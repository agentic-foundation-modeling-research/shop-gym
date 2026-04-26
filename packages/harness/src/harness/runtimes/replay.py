"""Deterministic cassette-replay runtime for harness tests (spec §5.6).

`ReplayRuntime` does not call any LLM. For each iteration, it consults a
pre-recorded cassette under ``<scenario_dir>/<iter_id>/`` and:

* copies the recorded ``workspace_after/`` overlay into ``run_dir`` with
  union-with-overwrite semantics (files in ``run_dir`` not present in the
  overlay are preserved; files present in the overlay overwrite their
  counterparts);
* copies the recorded ``trajectory.json`` and ``native.log`` (when
  present) into ``iter_dir``;
* returns the recorded `Trajectory` to the harness loop.

Setting the ``HARNESS_RECORD=1`` environment variable flips the runtime
into *record mode*: it delegates the iteration to the configured
``fallback`` runtime, then materialises a fresh cassette under
``<scenario_dir>/<iter_id>/`` from the resulting workspace and telemetry.
Record mode refuses to run when ``fallback`` is ``None``.

The cassette format matches spec §5.6:

```
<scenario_dir>/<iter_id>/
├── trajectory.json
├── native.log
└── workspace_after/
    ├── plan.md
    └── artifact/
```
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from harness.runtimes.base import AgentRuntime, RuntimeIterationResult
from harness.trajectory import Trajectory

_RECORD_ENV_VAR = "HARNESS_RECORD"
_TRAJECTORY_FILENAME = "trajectory.json"
_NATIVE_LOG_FILENAME = "native.log"
_WORKSPACE_AFTER_DIRNAME = "workspace_after"
_PLAN_FILENAME = "plan.md"
_ARTIFACT_DIRNAME = "artifact"


class ReplayError(Exception):
    """Raised when a cassette is missing, malformed, or record mode is misconfigured."""


class ReplayRuntime:
    """Cassette-driven `AgentRuntime` used by harness tests.

    Attributes:
        scenario_dir: Directory containing per-iteration cassette
            subdirectories (``plan/``, ``exec-0001/``, ...).
        fallback: Optional underlying runtime. Required when
            ``HARNESS_RECORD=1``; ignored in pure replay mode.
    """

    def __init__(
        self,
        scenario_dir: Path,
        fallback: AgentRuntime | None = None,
    ) -> None:
        """Initialise a replay runtime rooted at `scenario_dir`.

        Args:
            scenario_dir: Cassette root for the scenario under test.
            fallback: Runtime to delegate to when ``HARNESS_RECORD=1`` is
                set. Pure replay does not require it.
        """
        self._scenario_dir = scenario_dir
        self._fallback = fallback

    @property
    def scenario_dir(self) -> Path:
        """Cassette root for this scenario."""
        return self._scenario_dir

    @property
    def fallback(self) -> AgentRuntime | None:
        """Runtime used when recording cassettes; ``None`` when unset."""
        return self._fallback

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        """Run one iteration by replaying or recording a cassette.

        The iteration id is derived from ``iter_dir.name`` (e.g. ``plan``
        or ``exec-0001``). In replay mode the recorded cassette must exist
        and be well-formed; in record mode the cassette is freshly
        written from the fallback runtime's outputs.

        Args:
            run_dir: Workspace root used as the agent's working directory.
            iter_dir: Per-iteration directory the runtime owns. Must
                already exist.
            prompt: Fully rendered prompt. Forwarded to ``fallback`` in
                record mode; unused in replay mode.
            timeout: Per-iteration wall-clock budget in seconds.
                Forwarded to ``fallback`` in record mode.

        Returns:
            The recorded (replay) or freshly captured (record)
            `RuntimeIterationResult`.

        Raises:
            ReplayError: If the cassette is missing or malformed in
                replay mode, or if ``HARNESS_RECORD=1`` is set without a
                ``fallback`` runtime.
        """
        iter_id = iter_dir.name
        cassette_dir = self._scenario_dir / iter_id

        if os.environ.get(_RECORD_ENV_VAR) == "1":
            return self._record(
                cassette_dir=cassette_dir,
                run_dir=run_dir,
                iter_dir=iter_dir,
                prompt=prompt,
                timeout=timeout,
            )
        return self._replay(cassette_dir=cassette_dir, run_dir=run_dir, iter_dir=iter_dir)

    # ------------------------------------------------------------------
    # Replay mode
    # ------------------------------------------------------------------

    def _replay(
        self,
        *,
        cassette_dir: Path,
        run_dir: Path,
        iter_dir: Path,
    ) -> RuntimeIterationResult:
        """Materialise the cassette for one iteration into the live run."""
        if not cassette_dir.is_dir():
            raise ReplayError(f"cassette directory not found: {cassette_dir}")

        trajectory_src = cassette_dir / _TRAJECTORY_FILENAME
        if not trajectory_src.is_file():
            raise ReplayError(f"cassette is missing trajectory.json: {trajectory_src}")

        overlay_src = cassette_dir / _WORKSPACE_AFTER_DIRNAME
        if overlay_src.is_dir():
            _overlay_copy(overlay_src, run_dir)

        log_src = cassette_dir / _NATIVE_LOG_FILENAME
        if log_src.is_file():
            shutil.copyfile(log_src, iter_dir / _NATIVE_LOG_FILENAME)

        try:
            trajectory_data = json.loads(trajectory_src.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ReplayError(
                f"cassette trajectory.json is not valid JSON: {trajectory_src}"
            ) from exc
        trajectory = Trajectory.model_validate(trajectory_data)

        return RuntimeIterationResult(trajectory=trajectory)

    # ------------------------------------------------------------------
    # Record mode
    # ------------------------------------------------------------------

    def _record(
        self,
        *,
        cassette_dir: Path,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        """Delegate to `fallback` then write a fresh cassette to disk."""
        if self._fallback is None:
            raise ReplayError(f"{_RECORD_ENV_VAR}=1 set but ReplayRuntime has no fallback runtime")

        result = self._fallback.run_iteration(
            run_dir=run_dir,
            iter_dir=iter_dir,
            prompt=prompt,
            timeout=timeout,
        )

        # Reset the cassette directory so re-recording does not leave
        # stale files from a previous run alongside fresh output.
        if cassette_dir.exists():
            shutil.rmtree(cassette_dir)
        cassette_dir.mkdir(parents=True)

        # 1. trajectory.json — serialise the freshly captured trajectory.
        trajectory_payload = result.trajectory.model_dump(mode="json")
        (cassette_dir / _TRAJECTORY_FILENAME).write_text(
            json.dumps(trajectory_payload, indent=2) + "\n",
            encoding="utf-8",
        )

        # 2. native.log — copy from the iter_dir if the fallback wrote one.
        log_src = iter_dir / _NATIVE_LOG_FILENAME
        if log_src.is_file():
            shutil.copyfile(log_src, cassette_dir / _NATIVE_LOG_FILENAME)

        # 3. workspace_after/ — capture the evolving workspace surfaces.
        workspace_after = cassette_dir / _WORKSPACE_AFTER_DIRNAME
        workspace_after.mkdir()
        plan_src = run_dir / _PLAN_FILENAME
        if plan_src.is_file():
            shutil.copyfile(plan_src, workspace_after / _PLAN_FILENAME)
        artifact_src = run_dir / _ARTIFACT_DIRNAME
        if artifact_src.is_dir():
            shutil.copytree(artifact_src, workspace_after / _ARTIFACT_DIRNAME)

        return result


def _overlay_copy(src: Path, dst: Path) -> None:
    """Copy every file under `src` onto `dst` with union-with-overwrite semantics.

    Files in `src` overwrite their counterparts under `dst`; files in
    `dst` not present in `src` are left untouched. Subdirectories are
    created on demand.
    """
    for entry in src.rglob("*"):
        if entry.is_dir():
            continue
        relative = entry.relative_to(src)
        target = dst / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry, target)
