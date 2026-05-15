"""Unit tests for the :mod:`navigation_primitive_usage` build verifier.

Tests :class:`NavigationPrimitiveUsageVerifier` from
``shop_arena.gen.build.verifiers.navigation_primitive_usage``.

Covers impl plan T4.1: ``Header.tsx`` must import at least one of the
shipped navigation primitives, and known anti-patterns (re-derived
hover-intent, inline button-typography reset, legacy
``.header-menu-desktop`` margin) must not appear in the post-build
hydrogen tree.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from harness.verifiers import Verdict, VerifierContext
from shop_arena.gen.build.verifiers.navigation_primitive_usage import (
    NavigationPrimitiveUsageVerifier,
)

# --------------------------------------------------------------------------- #
# Fixture content — fragments composed by individual tests.
# --------------------------------------------------------------------------- #

_HEADER_PASSING = """\
import {NavMenu} from '~/components/NavMenu';
import {HeaderShell} from '~/components/HeaderShell';

export function Header() {
  return <HeaderShell brand={null} primary={
    <NavMenu menu={null as any} viewport="desktop" primaryDomainUrl="" publicStoreDomain="" />
  } ctas={null} />;
}
"""

_HEADER_NAVMENU_ONLY = """\
import {NavMenu} from '~/components/NavMenu';

export function Header() {
  return <NavMenu menu={null as any} viewport="desktop" primaryDomainUrl="" publicStoreDomain="" />;
}
"""

_HEADER_HEADERSHELL_ONLY = """\
import {HeaderShell} from '~/components/HeaderShell';

export function Header() {
  return <HeaderShell brand={null} primary={null} ctas={null} />;
}
"""

_HEADER_NO_PRIMITIVES = """\
import {NavLink} from 'react-router';

export function Header() {
  return <header className="header"><NavLink to="/">Home</NavLink></header>;
}
"""

_HEADER_INLINE_HOVER = """\
import {NavMenu} from '~/components/NavMenu';
import {useState} from 'react';

export function Header() {
  const [, setOpen] = useState(false);
  setTimeout(() => setOpen(false), 120);
  return <NavMenu menu={null as any} viewport="desktop" primaryDomainUrl="" publicStoreDomain="" />;
}
"""

_HEADER_INLINE_LINE_HEIGHT = """\
import {NavMenu} from '~/components/NavMenu';

export function Header() {
  return (
    <NavMenu menu={null as any} viewport="desktop" primaryDomainUrl="" publicStoreDomain="" />
  );
}

export function NavButton() {
  return <button style={{'line-height': 'inherit'}}>Shop</button>;
}
"""

_HEADER_INLINE_LINE_HEIGHT_CAMEL = """\
import {NavMenu} from '~/components/NavMenu';

export function NavButton() {
  return <button style={{lineHeight: 'inherit'}}>Shop</button>;
}

import {HeaderShell} from '~/components/HeaderShell';
"""

_LEGACY_CSS = """\
.header-menu-desktop {
  display: flex;
  margin-left: 3rem;
  gap: 1rem;
}
"""

_CLEAN_CSS = """\
.header-menu-desktop {
  display: flex;
  gap: 1rem;
}

.unrelated {
  margin-left: 3rem;
}
"""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _write(write_app_file: Callable[[str, str], Path], header: str, css: str | None = None) -> None:
    """Write a ``Header.tsx`` (and optionally an ``app.css``) into the fixture tree."""
    write_app_file("components/Header.tsx", header)
    if css is not None:
        write_app_file("styles/app.css", css)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_name_and_applicability() -> None:
    verifier = NavigationPrimitiveUsageVerifier()
    assert verifier.name == "navigation_primitive_usage"
    assert verifier.applies_to("gen_navigation") is True
    assert verifier.applies_to("gen_homepage") is False
    assert verifier.applies_to("visual_fix") is False


def test_passes_when_both_primitives_imported_and_no_anti_patterns(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    _write(write_app_file, _HEADER_PASSING, _CLEAN_CSS)

    result = NavigationPrimitiveUsageVerifier().run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.PASS
    assert result.details["rules_triggered"] == 0


def test_passes_with_navmenu_import_alone(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """Either NavMenu OR HeaderShell satisfies the import requirement."""
    _write(write_app_file, _HEADER_NAVMENU_ONLY, _CLEAN_CSS)

    result = NavigationPrimitiveUsageVerifier().run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.PASS


def test_passes_with_headershell_import_alone(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    _write(write_app_file, _HEADER_HEADERSHELL_ONLY, _CLEAN_CSS)

    result = NavigationPrimitiveUsageVerifier().run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.PASS


def test_passes_when_styles_file_absent(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """A missing ``app.css`` cannot trigger the legacy-CSS rule."""
    _write(write_app_file, _HEADER_PASSING, css=None)

    result = NavigationPrimitiveUsageVerifier().run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.PASS


def test_fails_when_header_missing_primitive_imports(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    _write(write_app_file, _HEADER_NO_PRIMITIVES, _CLEAN_CSS)

    result = NavigationPrimitiveUsageVerifier().run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.FAIL
    assert result.details["missing_imports"] is True
    assert result.details["rules_triggered"] == 0
    assert "Missing primitive import" in result.feedback
    assert "template_navigation_primitives.md" in result.feedback


def test_fails_on_inline_hover_intent(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    _write(write_app_file, _HEADER_INLINE_HOVER, _CLEAN_CSS)

    result = NavigationPrimitiveUsageVerifier().run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.FAIL
    assert result.details["missing_imports"] is False
    assert "hover_intent_inline" in result.details["triggered_rule_ids"]
    assert "useHoverIntent" in result.feedback


def test_fails_on_inline_line_height_kebab(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    _write(write_app_file, _HEADER_INLINE_LINE_HEIGHT, _CLEAN_CSS)

    result = NavigationPrimitiveUsageVerifier().run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.FAIL
    assert "button_typography_inline" in result.details["triggered_rule_ids"]
    assert "NavTrigger" in result.feedback


def test_fails_on_inline_line_height_camel(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """The camelCase ``lineHeight`` form is also a violation."""
    _write(write_app_file, _HEADER_INLINE_LINE_HEIGHT_CAMEL, _CLEAN_CSS)

    result = NavigationPrimitiveUsageVerifier().run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.FAIL
    assert "button_typography_inline" in result.details["triggered_rule_ids"]


def test_fails_on_legacy_header_menu_margin(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    _write(write_app_file, _HEADER_PASSING, _LEGACY_CSS)

    result = NavigationPrimitiveUsageVerifier().run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.FAIL
    assert "legacy_header_menu_margin" in result.details["triggered_rule_ids"]
    assert "HeaderShell" in result.feedback


def test_legacy_margin_outside_block_does_not_trigger(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """A ``margin-left: 3rem`` on an unrelated selector is not a violation."""
    _write(write_app_file, _HEADER_PASSING, _CLEAN_CSS)

    result = NavigationPrimitiveUsageVerifier().run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.PASS


def test_fails_when_header_file_missing(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    """A missing ``Header.tsx`` is itself a failure — the executor never wrote it."""
    result = NavigationPrimitiveUsageVerifier().run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.FAIL
    assert "could not read" in result.feedback
    assert result.details["exists"] is False


def test_reports_multiple_anti_patterns_at_once(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """The verifier surfaces every triggered rule, not just the first."""
    _write(write_app_file, _HEADER_INLINE_HOVER, _LEGACY_CSS)

    result = NavigationPrimitiveUsageVerifier().run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.FAIL
    triggered = sorted(result.details["triggered_rule_ids"])
    assert triggered == ["hover_intent_inline", "legacy_header_menu_margin"]
    assert result.details["rules_triggered"] == len(triggered)


# --------------------------------------------------------------------------- #
# Advisory mode (impl plan T4.2) — FAIL is downgraded to ADVISORY when the
# verifier is constructed with ``advisory=True``. The harness still surfaces
# the markdown feedback, but the selected task's marker is left intact.
# --------------------------------------------------------------------------- #


def test_advisory_mode_downgrades_missing_imports_to_advisory(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """With ``advisory=True``, a missing-import failure surfaces as ADVISORY."""
    _write(write_app_file, _HEADER_NO_PRIMITIVES, _CLEAN_CSS)

    result = NavigationPrimitiveUsageVerifier(advisory=True).run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.ADVISORY
    assert result.details["missing_imports"] is True
    assert result.details["advisory"] is True
    # Feedback body is unchanged — only the verdict is downgraded.
    assert "Missing primitive import" in result.feedback


def test_advisory_mode_downgrades_anti_pattern_to_advisory(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """With ``advisory=True``, an anti-pattern hit surfaces as ADVISORY."""
    _write(write_app_file, _HEADER_INLINE_HOVER, _CLEAN_CSS)

    result = NavigationPrimitiveUsageVerifier(advisory=True).run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.ADVISORY
    assert "hover_intent_inline" in result.details["triggered_rule_ids"]


def test_advisory_mode_downgrades_missing_header_to_advisory(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    """With ``advisory=True``, a missing ``Header.tsx`` surfaces as ADVISORY."""
    result = NavigationPrimitiveUsageVerifier(advisory=True).run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.ADVISORY
    assert result.details["exists"] is False


def test_advisory_mode_does_not_downgrade_pass(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """PASS is unaffected by ``advisory=True`` — only FAIL is downgraded."""
    _write(write_app_file, _HEADER_PASSING, _CLEAN_CSS)

    result = NavigationPrimitiveUsageVerifier(advisory=True).run(
        make_ctx(selected_task_id="gen_navigation"),
    )

    assert result.verdict is Verdict.PASS


def test_default_mode_still_fails_hard() -> None:
    """Default ``advisory=False`` preserves the M4-pre hard-fail behaviour."""
    verifier = NavigationPrimitiveUsageVerifier()
    # Internal probe: the default constructor stores ``False`` so future M5
    # promotion (impl plan T5.1) only has to drop the ``advisory=True`` kwarg
    # in ``default_verifiers_factory``.
    assert verifier._advisory is False
