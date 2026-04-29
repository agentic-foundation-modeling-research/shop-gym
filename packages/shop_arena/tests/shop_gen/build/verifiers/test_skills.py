"""Unit tests for ``shop_gen.build.verifiers._skills`` (impl plan T1.0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from shop_gen.build.verifiers import _skills


def _make_skill_tree(root: Path, *, with_pw_js: bool) -> Path:
    """Create a fake skill tree under ``root`` and return its path.

    Mirrors the on-disk layout the real ``pi-playwright`` package uses:
    ``<root>/SKILL.md`` plus ``<root>/scripts/pw.js`` (the latter
    optional, to exercise the partial-install case).
    """
    skill_dir = root / "skill"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# fake skill\n", encoding="utf-8")
    if with_pw_js:
        (skill_dir / "scripts" / "pw.js").write_text("// fake\n", encoding="utf-8")
    return skill_dir


def test_is_playwright_skill_available_returns_true_when_skill_and_pw_js_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_dir = _make_skill_tree(tmp_path, with_pw_js=True)
    monkeypatch.setattr(_skills, "resolve_playwright_skill_dir", lambda: skill_dir)

    assert _skills.is_playwright_skill_available() is True


def test_is_playwright_skill_available_returns_false_when_skill_dir_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_skills, "resolve_playwright_skill_dir", lambda: None)

    assert _skills.is_playwright_skill_available() is False


def test_is_playwright_skill_available_returns_false_when_pw_js_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_dir = _make_skill_tree(tmp_path, with_pw_js=False)
    monkeypatch.setattr(_skills, "resolve_playwright_skill_dir", lambda: skill_dir)

    assert _skills.is_playwright_skill_available() is False


def test_resolve_playwright_skill_dir_delegates_to_shop_explore(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The re-export is wired to ``shop_explore.pipeline``'s resolver."""
    sentinel = tmp_path / "sentinel"
    monkeypatch.setattr(_skills, "_resolve_playwright_skill_dir", lambda: sentinel)

    assert _skills.resolve_playwright_skill_dir() == sentinel
