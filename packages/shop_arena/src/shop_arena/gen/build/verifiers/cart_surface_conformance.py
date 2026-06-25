"""``cart_surface_conformance`` build-loop verifier.

Checks the generated Hydrogen app against explicit negative cart-surface
requirements in the shop manual. The motivating case is a manual that
states there is no slide-in cart drawer or modal while the template's
generic ``<Aside type="cart">`` wiring survives in the generated app.

The verifier is intentionally small and textual. This is cheaper and more
deterministic than asking the visual judge to discover an unrendered stateful
surface, and it catches the bug before the route-level browser checks spend
time on polished but incomplete pages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from harness.verifiers import Verdict, VerifierContext, VerifierResult

_NAME: Final[str] = "cart_surface_conformance"
"""Verifier name used in harness telemetry."""

_APPLICABLE_TASKS: Final[frozenset[str]] = frozenset({"gen_cart_search", "visual_fix"})
"""Tasks that own or can clean up cart-surface mismatches."""

_HYDROGEN_APP_REL: Final[Path] = Path("hydrogen") / "app"
"""Hydrogen app subtree relative to ``VerifierContext.artifact_dir``."""

_CART_PART_REL: Final[Path] = Path("parts") / "cart_and_search.md"
"""Preferred manual slice path relative to ``VerifierContext.artifact_dir``."""

_FULL_MANUAL_REL: Final[Path] = Path("manual.md")
"""Fallback manual path relative to ``VerifierContext.artifact_dir``."""

_SOURCE_SUFFIXES: Final[frozenset[str]] = frozenset({".js", ".jsx", ".ts", ".tsx"})
"""Source suffixes scanned for forbidden cart-drawer fingerprints."""

_NO_DRAWER_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bno\b[^.\n]{0,120}\b(?:side\s+)?drawer\b", re.IGNORECASE),
    re.compile(r"\bno\b[^.\n]{0,120}\bmodal\b", re.IGNORECASE),
    re.compile(r"\bnot\b[^.\n]{0,80}\bside\s+drawer\b", re.IGNORECASE),
    re.compile(r"\bnot\b[^.\n]{0,80}\bmodal\b", re.IGNORECASE),
)
"""Manual prose patterns that mean a cart drawer/modal is explicitly absent."""


@dataclass(frozen=True, slots=True)
class _Fingerprint:
    """One forbidden cart-drawer source fingerprint."""

    rule_id: str
    pattern: re.Pattern[str]
    message: str


@dataclass(frozen=True, slots=True)
class _Finding:
    """A forbidden fingerprint match in one source file."""

    rule_id: str
    path: Path
    message: str
    snippet: str


_FORBIDDEN_FINGERPRINTS: Final[tuple[_Fingerprint, ...]] = (
    _Fingerprint(
        rule_id="cart_aside_component",
        pattern=re.compile(r"\bCartAside\b"),
        message="Generic cart-aside component is present.",
    ),
    _Fingerprint(
        rule_id="cart_aside_mount",
        pattern=re.compile(r"""<Aside\b[^>]*\btype=["']cart["']"""),
        message='Generic `<Aside type="cart">` drawer mount is present.',
    ),
    _Fingerprint(
        rule_id="cart_drawer_component",
        pattern=re.compile(r"\bCartDrawer\b"),
        message="Cart drawer component is present.",
    ),
    _Fingerprint(
        rule_id="open_cart_aside",
        pattern=re.compile(r"""\bopen\s*\(\s*["']cart["']\s*\)"""),
        message='Cart action opens the template cart aside via `open("cart")`.',
    ),
    _Fingerprint(
        rule_id="cart_drawer_label",
        pattern=re.compile(
            r"""aria-label=["'][^"']*\bcart\s+drawer\b[^"']*["']""",
            re.IGNORECASE,
        ),
        message='Accessible label exposes a "cart drawer" surface.',
    ),
)
"""Forbidden drawer fingerprints when the manual says no drawer/modal exists."""


class CartSurfaceConformanceVerifier:
    """Fail when generated source contradicts explicit manual cart-surface rules."""

    name: str = _NAME

    def __init__(self, *, app_rel: Path = _HYDROGEN_APP_REL) -> None:
        """Build the verifier for a selected storefront app subtree.

        Args:
            app_rel: Storefront ``app/`` directory relative to
                ``VerifierContext.artifact_dir``. Defaults to
                ``hydrogen/app`` for backward compatibility.
        """
        self._app_rel = app_rel

    def applies_to(self, task_id: str) -> bool:
        """Return whether this verifier should run for ``task_id``."""
        return task_id in _APPLICABLE_TASKS

    def run(self, ctx: VerifierContext) -> VerifierResult:
        """Scan the Hydrogen app for forbidden cart-drawer wiring.

        Args:
            ctx: Verifier context. Reads the cart/search manual slice and
                ``hydrogen/app`` from ``ctx.artifact_dir``.

        Returns:
            ``PASS`` when no explicit no-drawer/manual constraint exists, or
            when the source has no forbidden drawer fingerprints.
            ``FAIL`` when the constraint exists and drawer fingerprints remain.
        """
        manual_path = _select_manual_path(ctx.artifact_dir)
        if manual_path is None:
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"`{_NAME}` could not read `{_CART_PART_REL.as_posix()}` or "
                    f"`{_FULL_MANUAL_REL.as_posix()}` from the run artifact. "
                    "The cart-surface check needs the manual prose to know whether "
                    "a drawer/modal is allowed."
                ),
                details={"manual_found": False},
            )

        manual_text = _read_text(manual_path)
        if not _manual_forbids_drawer(manual_text):
            return VerifierResult(
                verdict=Verdict.PASS,
                details={
                    "manual_path": str(manual_path),
                    "manual_forbids_drawer": False,
                    "findings": [],
                },
            )

        app_dir = ctx.artifact_dir / self._app_rel
        if not app_dir.is_dir():
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"`{_NAME}` could not read `{self._app_rel.as_posix()}`. "
                    "Did the storefront template clone run?"
                ),
                details={"app_dir": str(app_dir), "exists": False},
            )

        findings = _scan_forbidden_fingerprints(app_dir)
        if not findings:
            return VerifierResult(
                verdict=Verdict.PASS,
                details={
                    "manual_path": str(manual_path),
                    "manual_forbids_drawer": True,
                    "findings": [],
                },
            )

        feedback = _format_feedback(manual_path=manual_path, findings=findings)
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback=feedback,
            details={
                "manual_path": str(manual_path),
                "manual_forbids_drawer": True,
                "finding_count": len(findings),
                "triggered_rule_ids": sorted({finding.rule_id for finding in findings}),
                "files": sorted({str(finding.path) for finding in findings}),
            },
        )


def _select_manual_path(artifact_dir: Path) -> Path | None:
    """Return the cart/search manual slice, falling back to the full manual."""
    for rel in (_CART_PART_REL, _FULL_MANUAL_REL):
        path = artifact_dir / rel
        if path.is_file():
            return path
    return None


def _manual_forbids_drawer(manual_text: str) -> bool:
    """Return ``True`` when manual prose explicitly disallows drawers/modals."""
    return any(pattern.search(manual_text) for pattern in _NO_DRAWER_PATTERNS)


def _scan_forbidden_fingerprints(app_dir: Path) -> list[_Finding]:
    """Return all forbidden cart-drawer fingerprints under ``app_dir``."""
    findings: list[_Finding] = []
    for path in sorted(app_dir.rglob("*")):
        if not path.is_file() or path.suffix not in _SOURCE_SUFFIXES:
            continue
        text = _read_text(path)
        for fingerprint in _FORBIDDEN_FINGERPRINTS:
            match = fingerprint.pattern.search(text)
            if match is None:
                continue
            findings.append(
                _Finding(
                    rule_id=fingerprint.rule_id,
                    path=path,
                    message=fingerprint.message,
                    snippet=_line_for_offset(text, match.start()),
                ),
            )
    return findings


def _line_for_offset(text: str, offset: int) -> str:
    """Return the source line containing ``offset``, stripped for feedback."""
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end == -1:
        end = len(text)
    return text[start:end].strip()


def _format_feedback(*, manual_path: Path, findings: list[_Finding]) -> str:
    """Render actionable markdown feedback for forbidden drawer findings."""
    lines = [
        "The cart manual explicitly says this shop has no slide-in cart drawer/modal, "
        "but the generated Hydrogen source still contains cart-drawer wiring.",
        "",
        f"Manual checked: `{manual_path}`",
        "",
        "Remove the generic cart aside/drawer and make the header/add-to-cart behavior "
        "match the manual's documented cart surface.",
        "",
        "Findings:",
    ]
    for finding in findings:
        lines.append(
            f"- `{finding.rule_id}` in `{finding.path}`: {finding.message} "
            f"`{finding.snippet}`",
        )
    return "\n".join(lines)


def _read_text(path: Path) -> str:
    """Read ``path`` as UTF-8, returning an empty string when it is absent."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


__all__ = ["CartSurfaceConformanceVerifier"]
