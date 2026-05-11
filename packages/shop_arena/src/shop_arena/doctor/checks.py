"""Health checks for local ShopGym browser tooling.

The checks in this module are intentionally small and side-effect-free at
import time. Browser and Node probes run only when :func:`run_checks` or a
single check function is called.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from shop_arena.explore.pipeline import resolve_playwright_skill_dir

_PLAYWRIGHT_VERSION_TIMEOUT_SECONDS = 10.0
"""Wall-clock budget for the Python Playwright version probe."""

_CHROMIUM_LAUNCH_TIMEOUT_SECONDS = 30.0
"""Wall-clock budget for launching Playwright Chromium."""

_SKILL_HELP_TIMEOUT_SECONDS = 15.0
"""Wall-clock budget for the ``pi-playwright`` help probe."""

_CHROMIUM_LAUNCH_CODE = """
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    print(browser.version)
    browser.close()
""".strip()
"""Python snippet used by the Chromium launch subprocess probe."""


@dataclass(frozen=True)
class CheckResult:
    """Result of one doctor check.

    Attributes:
        name: Human-readable check name.
        passed: Whether the check passed.
        detail: Short diagnostic detail for the report line.
        remedy: Optional command or action to try when the check fails.
    """

    name: str
    passed: bool
    detail: str
    remedy: str | None = None


@dataclass(frozen=True)
class _CommandResult:
    """Captured subprocess result used by command-backed probes."""

    returncode: int
    stdout: str
    stderr: str


def run_checks() -> list[CheckResult]:
    """Run every currently supported ShopGym doctor check.

    Returns:
        Ordered check results. The order is stable so the CLI output is
        predictable and easy to scan.
    """
    return [
        check_python_playwright_cli(),
        check_playwright_chromium(),
        check_playwright_skill(),
        check_playwright_skill_entrypoint(),
    ]


def check_python_playwright_cli() -> CheckResult:
    """Verify that the Python Playwright CLI is importable."""
    result = _run_command(
        [sys.executable, "-m", "playwright", "--version"],
        timeout=_PLAYWRIGHT_VERSION_TIMEOUT_SECONDS,
    )
    if result.returncode == 0:
        return CheckResult(
            name="Python Playwright CLI",
            passed=True,
            detail=_first_output_line(result) or "playwright module is importable",
        )
    return CheckResult(
        name="Python Playwright CLI",
        passed=False,
        detail=_command_failure_detail(result),
        remedy="Run `uv sync` from the repo root.",
    )


def check_playwright_chromium() -> CheckResult:
    """Verify that Playwright's Chromium browser can launch headlessly."""
    result = _run_command(
        [sys.executable, "-c", _CHROMIUM_LAUNCH_CODE],
        timeout=_CHROMIUM_LAUNCH_TIMEOUT_SECONDS,
    )
    if result.returncode == 0:
        return CheckResult(
            name="Playwright Chromium",
            passed=True,
            detail=_first_output_line(result) or "Chromium launched",
        )
    return CheckResult(
        name="Playwright Chromium",
        passed=False,
        detail=_command_failure_detail(result),
        remedy="Run `uv run playwright install chromium` from the repo root.",
    )


def check_playwright_skill() -> CheckResult:
    """Verify that the ``pi-playwright`` browser skill directory resolves."""
    skill_dir = resolve_playwright_skill_dir()
    if skill_dir is None:
        return CheckResult(
            name="pi-playwright skill",
            passed=False,
            detail="skill directory not found",
            remedy="Run `pnpm install` from the repo root.",
        )
    return CheckResult(
        name="pi-playwright skill",
        passed=True,
        detail=str(skill_dir),
    )


def check_playwright_skill_entrypoint() -> CheckResult:
    """Verify that the resolved ``pi-playwright`` entrypoint can run."""
    skill_dir = resolve_playwright_skill_dir()
    if skill_dir is None:
        return CheckResult(
            name="pi-playwright entrypoint",
            passed=False,
            detail="skill directory not found",
            remedy="Run `pnpm install` from the repo root.",
        )

    entrypoint = skill_dir / "scripts" / "pw.js"
    if not entrypoint.is_file():
        return CheckResult(
            name="pi-playwright entrypoint",
            passed=False,
            detail=f"missing {entrypoint}",
            remedy="Run `pnpm install` from the repo root.",
        )

    result = _run_command(
        ["node", str(entrypoint), "--help"],
        timeout=_SKILL_HELP_TIMEOUT_SECONDS,
    )
    if result.returncode == 0:
        return CheckResult(
            name="pi-playwright entrypoint",
            passed=True,
            detail=_first_output_line(result) or "help command succeeded",
        )
    return CheckResult(
        name="pi-playwright entrypoint",
        passed=False,
        detail=_command_failure_detail(result),
        remedy="Run `pnpm install`; if Node is missing, install Node >=20.",
    )


def _run_command(argv: Sequence[str], *, timeout: float) -> _CommandResult:
    """Run ``argv`` and capture text output without invoking a shell."""
    try:
        proc = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return _CommandResult(
            returncode=127,
            stdout="",
            stderr=f"executable not found: {argv[0]}",
        )
    except subprocess.TimeoutExpired as exc:
        return _CommandResult(
            returncode=124,
            stdout=_coerce_output(exc.stdout),
            stderr=_coerce_output(exc.stderr) or f"timed out after {timeout:g}s",
        )
    return _CommandResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def _coerce_output(value: str | bytes | None) -> str:
    """Normalize optional subprocess timeout output to text."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _first_output_line(result: _CommandResult) -> str:
    """Return the first non-empty stdout/stderr line for a command result."""
    for output in (result.stdout, result.stderr):
        for line in output.splitlines():
            clean = line.strip()
            if clean:
                return clean
    return ""


def _command_failure_detail(result: _CommandResult) -> str:
    """Format a compact command failure detail for CLI output."""
    first_line = _first_output_line(result)
    if first_line:
        return f"exit {result.returncode}: {first_line}"
    return f"exit {result.returncode}"
