"""Reference verifier stubs (verifiers.md §9.2).

These are minimal, well-typed examples of every verifier shape consumers
need to exercise the dispatch lifecycle:

* `AlwaysPass` / `AlwaysFail` — rule-based verifiers covering the two
  core verdict paths.
* `RaisesException` — a verifier whose `run()` raises, so callers can
  assert the harness's `Verdict.ERROR` mapping.
* `LLMCompleterDriven` — a verifier that calls
  ``ctx.runtime.complete`` and forwards its output as feedback. Useful
  for stub-runtime tests that assert the runtime adapter's
  `LLMCompleter` sub-protocol is wired through.

The fixtures live under ``tests/integration/verifiers/`` (rather than
``tests/unit/``) to match spec §9.2's "consumer fixtures" framing.
``shop_gen`` and other downstream callers import from this module via
the test-only path.
"""

from __future__ import annotations

from harness.runtimes.base import LLMCompleter
from harness.verifiers import Verdict, VerifierContext, VerifierResult


class AlwaysPass:
    """Trivially passing verifier; covers the no-op happy path."""

    name = "always_pass"

    def __init__(self, *, scope: str | None = None) -> None:
        """Optionally restrict applicability to a single task id."""
        self._scope = scope

    def applies_to(self, task_id: str) -> bool:
        if self._scope is None:
            return True
        return task_id == self._scope

    def run(self, ctx: VerifierContext) -> VerifierResult:
        del ctx
        return VerifierResult(verdict=Verdict.PASS)


class AlwaysFail:
    """Trivially failing verifier with deterministic feedback."""

    name = "always_fail"

    def __init__(
        self,
        *,
        feedback: str = "stub failure",
        scope: str | None = None,
    ) -> None:
        self._feedback = feedback
        self._scope = scope

    def applies_to(self, task_id: str) -> bool:
        if self._scope is None:
            return True
        return task_id == self._scope

    def run(self, ctx: VerifierContext) -> VerifierResult:
        del ctx
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback=self._feedback,
            details={"source": "AlwaysFail"},
        )


class RaisesException:
    """Verifier whose `run` raises; the harness must record `Verdict.ERROR`."""

    name = "raises"

    def __init__(self, *, message: str = "stub crash") -> None:
        self._message = message

    def applies_to(self, task_id: str) -> bool:
        del task_id
        return True

    def run(self, ctx: VerifierContext) -> VerifierResult:
        del ctx
        raise RuntimeError(self._message)


class LLMCompleterDriven:
    """Verifier that asserts `ctx.runtime.complete` is callable.

    Useful in stub-runtime tests where the runtime exposes the optional
    ``LLMCompleter`` sub-protocol. Returns a `Verdict.ADVISORY` result
    carrying the completion text as feedback so callers can assert the
    LLM call path end-to-end without coupling to a real model.
    """

    name = "llm_judge"

    def __init__(self, *, prompt: str = "judge me", timeout: float = 30.0) -> None:
        self._prompt = prompt
        self._timeout = timeout

    def applies_to(self, task_id: str) -> bool:
        del task_id
        return True

    def run(self, ctx: VerifierContext) -> VerifierResult:
        runtime = ctx.runtime
        if not isinstance(runtime, LLMCompleter):
            return VerifierResult(
                verdict=Verdict.ERROR,
                feedback="runtime does not implement LLMCompleter",
            )
        completion = runtime.complete(self._prompt, timeout=self._timeout)
        return VerifierResult(
            verdict=Verdict.ADVISORY,
            feedback=completion,
        )
