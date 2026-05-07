"""Reference verifier fixtures for harness consumers.

These stubs are usable from other packages (e.g. ``shop_arena.gen``) to drive
integration tests without depending on production verifier
implementations. Spec: ``docs/specs/harness/verifiers.md`` §9.2.
"""

from __future__ import annotations

from tests.integration.verifiers.fixtures import (
    AlwaysFail,
    AlwaysPass,
    LLMCompleterDriven,
    RaisesException,
)

__all__ = [
    "AlwaysFail",
    "AlwaysPass",
    "LLMCompleterDriven",
    "RaisesException",
]
