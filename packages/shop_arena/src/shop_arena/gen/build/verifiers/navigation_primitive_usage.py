"""``navigation_primitive_usage`` build-loop verifier (impl plan T4.1).

Asserts that ``gen_navigation`` outputs adopt the navigation primitives
shipped under ``app/components`` / ``app/lib`` instead of re-deriving the
same code inline. Two complementary checks run against the post-build
``hydrogen/`` tree:

1. **Required imports.** ``app/components/Header.tsx`` must import at
   least one of the structural primitives (``~/components/NavMenu`` or
   ``~/components/HeaderShell``). The header is the single canonical
   site that has to consume the new layer; once it does, the rest of
   the nav surface (drawer, breadcrumbs, footer, announcement) follows
   by transitive composition.
2. **Anti-pattern fingerprints.** Three textual fingerprints flag
   re-derivation of code that already lives in a primitive:

   * ``setTimeout(() => setOpen(false)`` — re-derived hover-intent
     debounce (use :mod:`~/lib/use-hover-intent`).
   * ``'line-height': 'inherit'`` inline on a ``<button>`` — re-derived
     button-typography reset (use ``<NavTrigger>``).
   * ``margin-left: 3rem`` on ``.header-menu-desktop`` — legacy CSS that
     compounds the brand↔nav seam ``<HeaderShell>`` was designed to own.

The check is a deliberate substring/regex scan rather than an AST pass:
the executor is free to reformat its imports, and a textual fingerprint
matches the spec's "did you adopt the primitive at all?" question with
zero parser surface area. The same posture :class:`NavCoverageVerifier`
takes for handle membership.

Applicability mirrors the spec table: only ``gen_navigation``.

References:
    * Spec §"Acceptance" of
      ``docs/specs/shop_arena/template_navigation_primitives.md``.
    * Impl plan task T4.1 in
      ``docs/impl/template_navigation_primitives_implementation.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from harness.verifiers import Verdict, VerifierContext, VerifierResult

_NAME: Final[str] = "navigation_primitive_usage"
"""Verifier name (filesystem-safe; matches the spec table + impl plan T4.1)."""

_NAV_TASK_ID: Final[str] = "gen_navigation"
"""The single task this verifier gates."""

_HYDROGEN_DIR: Final[str] = "hydrogen"
"""Path of the hydrogen tree relative to ``VerifierContext.artifact_dir``."""

_HEADER_REL: Final[str] = "app/components/Header.tsx"
"""Header source path relative to ``hydrogen/``."""

_STYLES_REL: Final[str] = "app/styles/app.css"
"""Stylesheet path relative to ``hydrogen/``. The ``.header-menu-desktop``
legacy rule lives here in the template's current shape."""

_SPEC_POINTER: Final[str] = (
    "See `docs/specs/shop_arena/template_navigation_primitives.md` "
    '(\u00a7"Desired Status" + \u00a7"Acceptance").'
)
"""Markdown pointer included in every FAIL feedback body."""

# Required-import patterns — at least one must match in Header.tsx.
# A trailing single quote anchors the path so a partial match against
# e.g. ``~/components/NavMenuOther`` does not satisfy the rule.
_IMPORT_NAVMENU_RE: Final[re.Pattern[str]] = re.compile(
    r"""\bfrom\s+['"]~/components/NavMenu['"]""",
)
_IMPORT_HEADERSHELL_RE: Final[re.Pattern[str]] = re.compile(
    r"""\bfrom\s+['"]~/components/HeaderShell['"]""",
)


@dataclass(frozen=True)
class _AntiPattern:
    """One anti-pattern fingerprint scanned for in a target file.

    Attributes:
        rule_id: Stable identifier surfaced in ``details`` so feedback
            consumers can branch on the specific rule that fired
            without parsing the human-readable message.
        target: Project-relative path of the file the regex runs
            against. Used for both the file read and the user-facing
            message.
        pattern: Compiled regex matched against the file's full text.
        message: One-line markdown body explaining what to do instead.
    """

    rule_id: str
    target: str
    pattern: re.Pattern[str]
    message: str


# Hover-intent inlined as a raw setTimeout closing the menu — the exact
# debounce shape ``useHoverIntent`` exists to centralise. The regex
# tolerates whitespace and an optional ``window.`` prefix; it does NOT
# match ``setTimeout(close, ...)`` because that is the canonical
# composition path through the hook (the hook itself owns the timer).
_ANTI_HOVER_RE: Final[re.Pattern[str]] = re.compile(
    r"""(?:window\.)?setTimeout\s*\(\s*\(\s*\)\s*=>\s*setOpen\s*\(\s*false\s*\)""",
)

# Inline ``line-height: inherit`` written as a JSX style object key. The
# pattern intentionally tolerates double or single quotes around the
# property name so both ``"line-height": "inherit"`` and
# ``'line-height': 'inherit'`` are caught. The camelCase ``lineHeight``
# form is also accepted because the Header is a JSX file where both
# spellings are seen in the wild.
_ANTI_LINE_HEIGHT_RE: Final[re.Pattern[str]] = re.compile(
    r"""(?:['"]line-height['"]|\blineHeight\b)\s*:\s*['"]inherit['"]""",
)

# Legacy ``.header-menu-desktop { margin-left: 3rem; }`` rule. The regex
# anchors the property to a block opened by ``.header-menu-desktop`` so
# an unrelated ``margin-left: 3rem`` somewhere else in the stylesheet
# does not trigger the rule. The ``[^}]*`` between the selector and the
# property is bounded by the rule's own closing brace, so the match
# cannot leak across blocks.
_ANTI_LEGACY_CSS_RE: Final[re.Pattern[str]] = re.compile(
    r"""\.header-menu-desktop\b[^}]*\bmargin-left\s*:\s*3rem""",
    re.DOTALL,
)


_HEADER_ANTI_PATTERNS: Final[tuple[_AntiPattern, ...]] = (
    _AntiPattern(
        rule_id="hover_intent_inline",
        target=f"{_HYDROGEN_DIR}/{_HEADER_REL}",
        pattern=_ANTI_HOVER_RE,
        message=(
            "Re-derived hover-intent debounce found "
            "(`setTimeout(() => setOpen(false), ...)`). "
            "Use `useHoverIntent` from `~/lib/use-hover-intent` instead."
        ),
    ),
    _AntiPattern(
        rule_id="button_typography_inline",
        target=f"{_HYDROGEN_DIR}/{_HEADER_REL}",
        pattern=_ANTI_LINE_HEIGHT_RE,
        message=(
            "Inline button-typography reset found "
            "(`line-height: 'inherit'`). "
            "Use `<NavTrigger>` from `~/components/NavTrigger` instead — "
            "the typography reset is baked in."
        ),
    ),
)
"""Anti-patterns scanned against ``Header.tsx``."""

_STYLES_ANTI_PATTERNS: Final[tuple[_AntiPattern, ...]] = (
    _AntiPattern(
        rule_id="legacy_header_menu_margin",
        target=f"{_HYDROGEN_DIR}/{_STYLES_REL}",
        pattern=_ANTI_LEGACY_CSS_RE,
        message=(
            "Legacy `.header-menu-desktop { margin-left: 3rem }` rule "
            "found. Drop it and let `<HeaderShell>` own the brand\u2194nav "
            "gap via `.header-left { gap: var(--space-6) }`."
        ),
    ),
)
"""Anti-patterns scanned against ``app/styles/app.css``."""


class NavigationPrimitiveUsageVerifier:
    """Asserts ``gen_navigation`` outputs adopt the navigation primitives.

    Args:
        advisory: When ``True``, every verdict that would otherwise be
            :attr:`~harness.verifiers.Verdict.FAIL` is downgraded to
            :attr:`~harness.verifiers.Verdict.ADVISORY`. The harness
            still surfaces the markdown feedback to the next iteration
            (per :class:`~harness.verifiers.dispatch`'s ``FAIL`` /
            ``ADVISORY`` parity), but the selected task's ``[x]`` /
            ``[!]`` marker is left intact instead of being rewritten
            back to ``[~]``. Used by :func:`default_verifiers_factory`
            in M4 (impl plan T4.2) so the verifier warns without
            blocking landings retroactively while the M2 cassette
            migration completes; M5 (T5.1) flips this to ``False``
            to promote the rule to hard-fail.

    Attributes:
        name: ``"navigation_primitive_usage"`` — used as the per-verifier
            telemetry filename and the markdown section heading in
            ``feedback.md``.
    """

    name: str = _NAME

    def __init__(self, *, advisory: bool = False) -> None:
        self._advisory = advisory

    def applies_to(self, task_id: str) -> bool:
        """Match only ``gen_navigation`` (impl plan T4.1).

        Args:
            task_id: Selected task id.

        Returns:
            ``True`` iff ``task_id`` equals ``"gen_navigation"``.
        """
        return task_id == _NAV_TASK_ID

    def run(self, ctx: VerifierContext) -> VerifierResult:
        """Scan the post-iteration hydrogen tree for primitive adoption.

        Args:
            ctx: Verifier context. Reads ``ctx.artifact_dir / "hydrogen"``
                to locate ``Header.tsx`` and ``app.css``; ``ctx.runtime``
                is unused.

        Returns:
            ``PASS`` when ``Header.tsx`` imports at least one primitive
            and no anti-pattern fingerprints fire.

            ``FAIL`` otherwise, with markdown feedback enumerating each
            failed rule.

            ``FAIL`` when ``Header.tsx`` is missing — the executor cannot
            have wired up primitives without authoring the file.
        """
        hydrogen_dir = ctx.artifact_dir / _HYDROGEN_DIR
        header_path = hydrogen_dir / _HEADER_REL
        if not header_path.is_file():
            return VerifierResult(
                verdict=self._fail_verdict(),
                feedback=(
                    f"`{_NAME}` could not read `{_HYDROGEN_DIR}/{_HEADER_REL}`. "
                    "Did `gen_navigation` finish writing the header?\n\n"
                    f"{_SPEC_POINTER}"
                ),
                details={"header_path": str(header_path), "exists": False},
            )

        header_text = _read_text(header_path)
        styles_text = _read_text(hydrogen_dir / _STYLES_REL)

        missing_imports = not (
            _IMPORT_NAVMENU_RE.search(header_text) or _IMPORT_HEADERSHELL_RE.search(header_text)
        )

        triggered: list[_AntiPattern] = []
        triggered.extend(rule for rule in _HEADER_ANTI_PATTERNS if rule.pattern.search(header_text))
        triggered.extend(rule for rule in _STYLES_ANTI_PATTERNS if rule.pattern.search(styles_text))

        if not missing_imports and not triggered:
            return VerifierResult(
                verdict=Verdict.PASS,
                details={
                    "header_path": str(header_path),
                    "rules_checked": len(_HEADER_ANTI_PATTERNS) + len(_STYLES_ANTI_PATTERNS),
                    "rules_triggered": 0,
                },
            )

        triggered_ids = [rule.rule_id for rule in triggered]
        return VerifierResult(
            verdict=self._fail_verdict(),
            feedback=_render_failure_markdown(
                missing_imports=missing_imports,
                triggered=triggered,
            ),
            details={
                "header_path": str(header_path),
                "missing_imports": missing_imports,
                "rules_triggered": len(triggered),
                "triggered_rule_ids": triggered_ids,
                "advisory": self._advisory,
            },
        )

    def _fail_verdict(self) -> Verdict:
        """Return the verdict to emit on a failing scan.

        Honours the ``advisory`` constructor flag: when set, ``FAIL`` is
        downgraded to ``ADVISORY`` so the harness surfaces the feedback
        without rewriting the task marker back to ``[~]``.
        """
        return Verdict.ADVISORY if self._advisory else Verdict.FAIL


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _read_text(path: Path) -> str:
    """Return the UTF-8 text of ``path`` or the empty string when absent.

    Anti-pattern scanning treats a missing file as "no anti-pattern": a
    template that has not yet shipped ``app/styles/app.css`` cannot be
    failed by a rule that targets that file. The required-import check
    runs against ``Header.tsx`` directly and short-circuits earlier in
    :meth:`NavigationPrimitiveUsageVerifier.run` when the header is
    absent, so this fallback never silently passes a real failure.
    """
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _render_failure_markdown(
    *,
    missing_imports: bool,
    triggered: list[_AntiPattern],
) -> str:
    """Render the failure feedback body (one bullet per failed rule)."""
    lines: list[str] = [
        f"`{_NAME}` failed: `gen_navigation` did not adopt the template's navigation primitives.",
        "",
    ]
    if missing_imports:
        lines.extend(
            (
                "- **Missing primitive import.** "
                f"`{_HYDROGEN_DIR}/{_HEADER_REL}` does not import `~/components/NavMenu` "
                "or `~/components/HeaderShell`. Wire at least one in so the structural "
                "primitives drive the header instead of being shadowed by hand-rolled code.",
            ),
        )
    for rule in triggered:
        lines.append(f"- **`{rule.rule_id}`** in `{rule.target}`: {rule.message}")
    lines.extend(("", _SPEC_POINTER))
    return "\n".join(lines)


__all__ = ["NavigationPrimitiveUsageVerifier"]
