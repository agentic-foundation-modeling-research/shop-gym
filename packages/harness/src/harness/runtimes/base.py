"""Runtime adapter contract for harness iterations (spec §5.6).

Every concrete runtime is a thin adapter that runs one agent iteration
synchronously: it spawns the agent subprocess with `run_dir` as the
working directory, writes its native log and any screenshots into
`iter_dir`, and returns a normalized `Trajectory`.

The runtime owns LLM, tool, and in-iteration context concerns. The
harness owns iteration lifecycle, telemetry persistence, plan parsing,
and the workspace state machine *between* iterations. See
`docs/specs/harness/plan_exec_loop.md` §5.6 and §5.7.

This module also defines the optional `LLMCompleter` sub-protocol, used
by callers (notably `shop_arena.explore` synthesis, spec §5.10) that need a
single non-agent LLM completion against the same model the runtime drives
its iterations with. Runtime adapters are free to implement it; harness
itself does not call it.
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


@runtime_checkable
class LLMCompleter(Protocol):
    """Optional sub-protocol for runtimes that expose a one-shot LLM completion.

    Implementations run a single non-agent prompt → text call against the
    same underlying model the runtime drives iterations with — no tools,
    no AGENTS.md context, no session persistence. Callers (notably
    `shop_arena.explore` synthesis, spec §5.10) use it to delegate the
    one-shot manual-merge LLM call to the configured runtime instead of
    instantiating a separate provider SDK.

    Adapters are free to implement this; the harness loop itself never
    calls it. Runtimes that cannot serve completions (e.g.
    `ReplayRuntime`) simply omit the method.
    """

    def complete(self, prompt: str, *, timeout: float) -> str:
        """Run one non-agent LLM completion against `prompt`.

        Args:
            prompt: Fully rendered prompt body. The runtime delivers it
                to the LLM verbatim — callers are responsible for any
                templating or guard rails.
            timeout: Wall-clock budget in seconds. Implementations
                should kill the underlying subprocess on expiry and
                surface the failure via an exception.

        Returns:
            The model's text completion as a single string. Empty
            output is allowed; callers (e.g. synthesis fallback)
            decide how to react.

        Raises:
            subprocess.TimeoutExpired: When the underlying call exceeds
                `timeout`. Other implementation-specific errors may also
                surface; callers that need a fallback should catch
                broad exceptions.
        """
        ...
