"""Shared skill-probe helpers for build-loop verifiers (impl plan T1.0).

The :class:`~shop_gen.build.verifiers.visual_judge.VisualJudgeVerifier`
(M1) and the final-eval visual sweep (M5) both depend on the
``pi-playwright`` skill being installed globally. The probe is
platform-level — it queries the JS package manager's global root, which
is the same for every harness-supported runtime (``pi``,
``claude_code``, ``replay``). When the skill is missing the visual
judge is omitted from the verifier tuple with a single warning, per
spec §5.5.1.

The canonical resolver lives in :mod:`shop_explore.pipeline` (where it
also gates the playwright session pre-open). This module imports it
and adds the boolean predicate that the verifier factory needs.

This module is import-safe: no I/O, no env reads, and no side effects
at import time. Callers invoke :func:`is_playwright_skill_available`
(which shells out to ``pnpm root -g`` / ``npm root -g`` via the lifted
resolver) only when they need to decide whether to register the
visual judge.
"""

from __future__ import annotations

from pathlib import Path

# Re-export of the canonical resolver in ``shop_explore.pipeline``. The
# spec (impl plan T1.0) blesses either lifting the function or this
# import-and-re-export; we choose re-export to keep ``shop_explore``
# free of any back-edge into ``shop_gen.build``.
from shop_explore.pipeline import (
    _resolve_playwright_skill_dir,  # pyright: ignore[reportPrivateUsage]
)

__all__ = [
    "is_playwright_skill_available",
    "resolve_playwright_skill_dir",
]


def resolve_playwright_skill_dir() -> Path | None:
    """Locate the ``pi-playwright`` browser skill on this machine.

    Thin re-export of :func:`shop_explore.pipeline._resolve_playwright_skill_dir`
    so the build-loop verifiers don't reach across packages for a
    private name. Returns the resolved skill directory, or ``None``
    when neither ``pnpm root -g`` nor ``npm root -g`` succeeds or the
    skill is not installed globally.

    Returns:
        Absolute path to the skill directory when found, else ``None``.
    """
    return _resolve_playwright_skill_dir()


def is_playwright_skill_available() -> bool:
    """Return ``True`` iff the playwright skill is fully usable.

    "Fully usable" means the skill directory resolves *and* its
    ``scripts/pw.js`` entrypoint is a regular file. The latter check
    catches partial installs where the package directory exists but
    the CLI shim was not laid down. Spec §5.5.1.

    Returns:
        ``True`` when the resolver finds the skill and ``pw.js`` is
        present; ``False`` otherwise.
    """
    skill_dir = resolve_playwright_skill_dir()
    if skill_dir is None:
        return False
    return (skill_dir / "scripts" / "pw.js").is_file()
