"""Runtime adapter contract for harness iterations (spec §5.6).

Every concrete runtime is a thin adapter that runs one agent iteration
synchronously: it spawns the agent subprocess with `run_dir` as the
working directory, writes its native log and any screenshots into
`iter_dir`, and returns a normalized `Trajectory`.

The runtime owns LLM, tool, and in-iteration context concerns. The
harness owns iteration lifecycle, telemetry persistence, plan parsing,
and the workspace state machine *between* iterations. See
`docs/specs/harness/plan_exec_loop.md` §5.6 and §5.7.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from harness.trajectory import Trajectory


@dataclass(frozen=True, slots=True)
class RuntimeIterationResult:
    """Outcome of one `AgentRuntime.run_iteration` call.

    The runtime is expected to have already written `iter_dir/native.log`
    and any screenshots under `iter_dir/screenshots/` before returning.
    The harness loop is responsible for persisting `trajectory.json`
    (from `trajectory`) and the iteration's `metadata.json` sidecar.

    Attributes:
        trajectory: Normalized telemetry for the iteration. The runtime
            fills in `iter_id`, `runtime`, timestamps, `exit_code`,
            `prompt_sha256`, and the ordered step list.
    """

    trajectory: Trajectory


@runtime_checkable
class AgentRuntime(Protocol):
    """Contract every concrete runtime adapter must satisfy.

    Implementations spawn the agent subprocess with `run_dir` as the
    working directory and may write freely under `iter_dir`. They must
    not mutate stable workspace files (`AGENTS.md`, `prompts/`).

    A wall-clock timeout is enforced by raising
    `subprocess.TimeoutExpired`; the harness loop maps that exception to
    `final_status=timeout`.
    """

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        """Run one iteration synchronously.

        Args:
            run_dir: Workspace root used as the agent's working directory.
                The agent reads anchors (`AGENTS.md`, `plan.md`) and may
                edit evolving files (`plan.md`, `artifact/`).
            iter_dir: Per-iteration directory the runtime owns for
                telemetry side-effects (`native.log`, `screenshots/`).
                The directory exists when this method is called.
            prompt: Fully rendered prompt to deliver to the agent. The
                harness has already prepended any `<<<harness-control>>>`
                header for executor iterations.
            timeout: Per-iteration wall-clock budget in seconds.

        Returns:
            A `RuntimeIterationResult` carrying the normalized
            `Trajectory` for the iteration.

        Raises:
            subprocess.TimeoutExpired: When the agent exceeds `timeout`.
        """
        ...
