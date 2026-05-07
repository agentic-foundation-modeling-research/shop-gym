"""Verifier extension public surface (spec `verifiers.md` §5.2 + §9.1).

Verifiers are caller-provided checks (rule-based or LLM-as-judge) that
the harness dispatches between executor iterations. The harness owns
dispatch, telemetry, and the prompt-feedback slot; it owns no
verifier implementations.

The names re-exported below form the v0.3.0 public surface described in
``docs/specs/harness/verifiers.md`` §9.1.
"""

from __future__ import annotations

from harness.verifiers.protocol import (
    Verdict,
    Verifier,
    VerifierContext,
    VerifierResult,
    VerifierRun,
)

__all__ = [
    "Verdict",
    "Verifier",
    "VerifierContext",
    "VerifierResult",
    "VerifierRun",
]
