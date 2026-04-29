"""Replay-context tests for ``navigation_primitive_usage`` (impl plan T4.3).

Complements the synthetic-fixture unit tests in
``tests/shop_gen/build/verifiers/test_navigation_primitive_usage.py``
(T4.1) with two integration-shaped checks that exercise the verifier
against the *real* post-M2 cassette artifact:

(a) PASS when run against the ``fixture_build_loop`` ``exec-0002``
    post-build hydrogen tree — the cassette already ships a
    ``Header.tsx`` that imports ``<NavMenu>`` and ``<HeaderShell>``
    (per `cassettes/fixture_build_loop/README.md`'s M2/M3 contract),
    so the verifier should accept the artifact end-to-end.

(b) FAIL when the same artifact is mutated to re-derive hover-intent
    inline (`setTimeout(() => setOpen(false), ...)`), with the
    ``hover_intent_inline`` rule id surfaced in
    :attr:`VerifierResult.details`.

The replay-context shape — copy the cassette artifact into a tmp
directory, point the verifier at it — is deliberate: the unit tests
build their fixture from string fragments, which exercises the regex
surface in isolation but never actually proves the verifier accepts
a real cassette artifact. If a future cassette regeneration (T2.8)
swaps out the synthetic Header for a different shape, this test is
the one that lights up.

References:
    * Spec §"Acceptance" of
      ``docs/specs/shop_arena/template_navigation_primitives.md``.
    * Impl plan task T4.3 in
      ``docs/impl/template_navigation_primitives_implementation.md``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Final

from harness.plan.tasks import TaskList
from harness.runtimes.base import AgentRuntime, RuntimeIterationResult
from harness.verifiers import Verdict, VerifierContext
from shop_gen.build.verifiers.navigation_primitive_usage import (
    NavigationPrimitiveUsageVerifier,
)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

_CASSETTE_DIR: Final[Path] = Path(__file__).resolve().parent / "cassettes" / "fixture_build_loop"
"""Hand-crafted cassette root (shared with ``test_build_loop_replay.py``)."""

_POST_M2_ARTIFACT: Final[Path] = _CASSETTE_DIR / "exec-0002" / "workspace_after" / "artifact"
"""Post-``gen_navigation`` artifact directory.

After ``exec-0002`` runs, the cassette has layered ``Header.tsx`` +
``Footer.tsx`` onto the hydrogen tree — i.e. this is the snapshot the
verifier would see if dispatched against the real build loop.
"""

_HEADER_REL: Final[Path] = Path("hydrogen/app/components/Header.tsx")
"""Header source path relative to ``artifact_dir``."""

# Synthetic Header.tsx that imports a primitive (so the missing-import
# rule does not fire) but re-derives hover-intent inline. The verifier
# must FAIL with ``hover_intent_inline`` triggered.
_HEADER_INLINE_HOVER: Final[str] = """\
import {NavMenu} from '~/components/NavMenu';
import {useState} from 'react';

export function Header() {
  const [, setOpen] = useState(false);
  setTimeout(() => setOpen(false), 120);
  return <NavMenu menu={null as any} viewport="desktop" primaryDomainUrl="" publicStoreDomain="" />;
}
"""


# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


class _StubRuntime:
    """Minimal :class:`AgentRuntime` stub.

    The verifier never invokes ``run_iteration``; the stub exists only
    to satisfy the ``VerifierContext.runtime: AgentRuntime`` contract.
    """

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        del run_dir, iter_dir, prompt, timeout
        raise AssertionError("verifier tests do not invoke run_iteration")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _materialise_artifact(dst: Path) -> Path:
    """Copy the cassette's post-M2 artifact tree into ``dst``.

    Returns the copied ``artifact/`` directory so callers can hand it
    to a :class:`VerifierContext`. The copy isolates per-test mutations
    (e.g. test (b) rewriting ``Header.tsx``) from the source cassette.
    """
    shutil.copytree(_POST_M2_ARTIFACT, dst / "artifact")
    return dst / "artifact"


def _make_ctx(artifact_dir: Path) -> VerifierContext:
    """Build a :class:`VerifierContext` rooted at ``artifact_dir``."""
    runtime: AgentRuntime = _StubRuntime()
    return VerifierContext(
        run_dir=artifact_dir.parent,
        iter_id="exec-0002",
        selected_task_id="gen_navigation",
        plan=TaskList(tasks=()),
        artifact_dir=artifact_dir,
        runtime=runtime,
    )


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_navigation_verifier_passes_against_post_m2_cassette(
    tmp_path: Path,
) -> None:
    """The verifier accepts the post-``gen_navigation`` cassette artifact.

    Spec §"Acceptance": ``Header.tsx`` must import at least one of
    ``<NavMenu>`` / ``<HeaderShell>``, and no anti-pattern fingerprints
    fire. The cassette's synthetic ``Header.tsx`` (per
    ``cassettes/fixture_build_loop/README.md``) imports both primitives,
    so the verifier returns PASS.
    """
    artifact_dir = _materialise_artifact(tmp_path)

    result = NavigationPrimitiveUsageVerifier().run(_make_ctx(artifact_dir))

    assert result.verdict is Verdict.PASS, (
        f"verifier rejected the post-M2 cassette artifact: {result.feedback}"
    )
    assert result.details["rules_triggered"] == 0


def test_navigation_verifier_fails_when_header_re_derives_hover_intent(
    tmp_path: Path,
) -> None:
    """Mutating ``Header.tsx`` to inline hover-intent flips PASS to FAIL.

    The mutation keeps the ``<NavMenu>`` import (so the missing-import
    rule does not fire) but adds a ``setTimeout(() => setOpen(false), ...)``
    closure — the exact debounce shape ``useHoverIntent`` exists to
    centralise. The verifier must surface the ``hover_intent_inline``
    rule id and point the executor at ``useHoverIntent`` in the
    feedback body.
    """
    artifact_dir = _materialise_artifact(tmp_path)
    header_path = artifact_dir / _HEADER_REL
    assert header_path.is_file(), "cassette regression — Header.tsx missing"
    header_path.write_text(_HEADER_INLINE_HOVER, encoding="utf-8")

    result = NavigationPrimitiveUsageVerifier().run(_make_ctx(artifact_dir))

    assert result.verdict is Verdict.FAIL
    assert result.details["missing_imports"] is False
    assert "hover_intent_inline" in result.details["triggered_rule_ids"]
    assert "useHoverIntent" in result.feedback
