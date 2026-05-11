"""Tests for the ``shop-doctor`` diagnostic command."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
from pathlib import Path

import pytest

from shop_arena.doctor import checks as checks_mod
from shop_arena.doctor import cli as cli_mod


def test_console_script_registered() -> None:
    """``[project.scripts]`` exposes ``shop-doctor`` pointing at ``cli:main``."""
    entry_points = importlib_metadata.entry_points(group="console_scripts")
    matches = [ep for ep in entry_points if ep.name == "shop-doctor"]
    assert len(matches) == 1, "shop-doctor console script not registered"
    assert matches[0].value == "shop_arena.doctor.cli:main"


def test_console_script_loads_to_main() -> None:
    """The registered entry point loads to the same callable as ``cli.main``."""
    (entry,) = (
        ep
        for ep in importlib_metadata.entry_points(group="console_scripts")
        if ep.name == "shop-doctor"
    )
    assert entry.load() is cli_mod.main


def test_main_returns_ok_when_all_checks_pass(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``shop-doctor`` exits successfully when every check passes."""
    monkeypatch.setattr(
        cli_mod,
        "run_checks",
        lambda: [
            checks_mod.CheckResult(
                name="Python Playwright CLI",
                passed=True,
                detail="Version 1.44.0",
            ),
            checks_mod.CheckResult(
                name="pi-playwright skill",
                passed=True,
                detail="/repo/node_modules/pi-playwright/skills/playwright-browser",
            ),
        ],
    )

    assert cli_mod.main([]) == cli_mod.EXIT_OK

    out = capsys.readouterr().out
    assert "[OK] Python Playwright CLI: Version 1.44.0" in out
    assert "All checks passed." in out


def test_main_returns_failure_when_any_check_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``shop-doctor`` returns nonzero and prints remedies for failures."""
    monkeypatch.setattr(
        cli_mod,
        "run_checks",
        lambda: [
            checks_mod.CheckResult(
                name="Playwright Chromium",
                passed=False,
                detail="exit 1: missing browser",
                remedy="Run `uv run playwright install chromium` from the repo root.",
            ),
        ],
    )

    assert cli_mod.main([]) == cli_mod.EXIT_CHECK_FAILED

    out = capsys.readouterr().out
    assert "[FAIL] Playwright Chromium: exit 1: missing browser" in out
    assert "fix: Run `uv run playwright install chromium` from the repo root." in out
    assert "One or more checks failed." in out


def test_check_python_playwright_cli_reports_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Playwright CLI check reports the version from stdout."""
    monkeypatch.setattr(
        checks_mod,
        "_run_command",
        lambda _argv, *, timeout: checks_mod._CommandResult(
            returncode=0,
            stdout="Version 1.44.0\n",
            stderr="",
        ),
    )

    result = checks_mod.check_python_playwright_cli()

    assert result == checks_mod.CheckResult(
        name="Python Playwright CLI",
        passed=True,
        detail="Version 1.44.0",
    )


def test_check_playwright_chromium_reports_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Chromium check points at the one-time browser install command."""
    monkeypatch.setattr(
        checks_mod,
        "_run_command",
        lambda _argv, *, timeout: checks_mod._CommandResult(
            returncode=1,
            stdout="",
            stderr="Executable doesn't exist at /tmp/chromium\n",
        ),
    )

    result = checks_mod.check_playwright_chromium()

    assert result.passed is False
    assert result.name == "Playwright Chromium"
    assert result.detail == "exit 1: Executable doesn't exist at /tmp/chromium"
    assert result.remedy == "Run `uv run playwright install chromium` from the repo root."


def test_check_playwright_skill_entrypoint_runs_help(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The skill entrypoint check uses the resolved ``pw.js`` path."""
    skill_dir = tmp_path / "playwright-browser"
    entrypoint = skill_dir / "scripts" / "pw.js"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("console.log('help')\n", encoding="utf-8")
    seen_argv: list[list[str]] = []

    def fake_run_command(argv: list[str], *, timeout: float) -> checks_mod._CommandResult:
        seen_argv.append(argv)
        return checks_mod._CommandResult(returncode=0, stdout="playwright-cli\n", stderr="")

    monkeypatch.setattr(checks_mod, "resolve_playwright_skill_dir", lambda: skill_dir)
    monkeypatch.setattr(checks_mod, "_run_command", fake_run_command)

    result = checks_mod.check_playwright_skill_entrypoint()

    assert result == checks_mod.CheckResult(
        name="pi-playwright entrypoint",
        passed=True,
        detail="playwright-cli",
    )
    assert seen_argv == [["node", str(entrypoint), "--help"]]


def test_check_playwright_skill_reports_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The skill check explains how to repair a missing workspace dependency."""
    monkeypatch.setattr(checks_mod, "resolve_playwright_skill_dir", lambda: None)

    result = checks_mod.check_playwright_skill()

    assert result == checks_mod.CheckResult(
        name="pi-playwright skill",
        passed=False,
        detail="skill directory not found",
        remedy="Run `pnpm install` from the repo root.",
    )
