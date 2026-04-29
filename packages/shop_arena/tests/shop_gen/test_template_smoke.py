"""Template-tree smoke tests for the ``hydrogen/`` template (T1.5).

The hydrogen template lives at
``packages/shop_arena/src/shop_gen/templates/hydrogen`` and is intentionally
**outside** the repo's pnpm workspace (every generated shop clones the tree,
so workspace-aware deps would bloat each artifact). It also ships no TS test
runner — per the implementation plan
``docs/impl/template_navigation_primitives_implementation.md`` we verify the
template through three coarse signals:

1. Required source files exist on disk.
2. Required named exports are present (cheap regex; full type-check below
   establishes the strict guarantee).
3. ``pnpm tsc --noEmit`` is clean against the template tree.

This module owns signals (1) and (2) outright and shells out for (3) when
``pnpm`` and ``node_modules`` are both available locally; it ``pytest.skip``s
otherwise so CI hosts without Node — and developer machines that haven't run
``pnpm install --ignore-workspace`` inside the template — surface the gap as
a skip rather than a hard failure.

The plan extends this module at each milestone (M1/M2/M3) with additional
file-existence and named-export assertions; the type-check is shared.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
"""Repo root (``shop-gym/``).

Resolved from this file's location:
``packages/shop_arena/tests/shop_gen/test_template_smoke.py`` → four parents
up lands at the repo root.
"""

_HYDROGEN_DIR: Final[Path] = (
    _REPO_ROOT / "packages" / "shop_arena" / "src" / "shop_gen" / "templates" / "hydrogen"
)
"""Filesystem location of the hydrogen template tree."""

_TYPECHECK_TIMEOUT_S: Final[float] = 180.0
"""Wall-clock budget for ``pnpm tsc --noEmit`` (mirrors
``shop_gen.build.verifiers.tsc._DEFAULT_TIMEOUT_S``)."""


# ---------------------------------------------------------------------------
# M1 — trigger + recursion + hover-intent
# ---------------------------------------------------------------------------

_M1_FILES: Final[tuple[str, ...]] = (
    "app/lib/use-hover-intent.ts",
    "app/components/NavTrigger.tsx",
    "app/components/NavMenu.tsx",
)
"""Files M1 of the navigation-primitives plan must add to the template tree."""


@pytest.mark.parametrize("relpath", _M1_FILES)
def test_template_smoke_m1_files_exist(relpath: str) -> None:
    """Each M1 primitive file is present in the template tree."""
    path = _HYDROGEN_DIR / relpath
    assert path.is_file(), f"expected primitive file at {path}, got nothing"


def test_template_smoke_m1_navmenu_exports_navmenu() -> None:
    """``NavMenu.tsx`` exposes ``NavMenu`` as a named export.

    Uses a substring check rather than a full TS parse: the M1 plan
    guarantees the export is declared with ``export function NavMenu(`` (per
    T1.4's status note); the strict shape is re-verified by the
    type-check test below.
    """
    source = (_HYDROGEN_DIR / "app/components/NavMenu.tsx").read_text(encoding="utf-8")
    assert "export function NavMenu(" in source, (
        "NavMenu.tsx must export `NavMenu` as a named function export"
    )


# ---------------------------------------------------------------------------
# Shared — ``pnpm tsc --noEmit`` against the template
# ---------------------------------------------------------------------------


def _node_modules_present() -> bool:
    """Whether the hydrogen template has dependencies installed locally."""
    return (_HYDROGEN_DIR / "node_modules").is_dir()


def test_template_smoke_typecheck_clean() -> None:
    """``pnpm typecheck`` reports no errors against the template tree.

    The package's ``typecheck`` script is ``react-router typegen && tsc
    --noEmit`` (see ``packages/shop_arena/src/shop_gen/templates/hydrogen``
    ``package.json``). Running ``tsc`` alone surfaces ~46 spurious errors
    about ``./+types/*`` modules that ``react-router typegen`` generates
    on demand — running the package script is the canonical, full-fidelity
    invocation and matches what the build-loop verifiers exercise on
    cloned shop artifacts after the build step has run.

    Skipped when ``pnpm`` is unavailable on ``$PATH`` or when
    ``node_modules/`` has not been installed in the template — both are
    valid local-dev / CI states (the template is not in the pnpm workspace,
    so deps are an explicit ``pnpm install --ignore-workspace`` step).
    """
    if shutil.which("pnpm") is None:
        pytest.skip("pnpm not on PATH; install Node + pnpm to run this check")
    if not _node_modules_present():
        pytest.skip(
            "hydrogen template has no node_modules; run "
            "`pnpm install --ignore-workspace` inside "
            f"{_HYDROGEN_DIR} to enable this check"
        )

    result = subprocess.run(
        ("pnpm", "typecheck"),
        cwd=_HYDROGEN_DIR,
        capture_output=True,
        text=True,
        timeout=_TYPECHECK_TIMEOUT_S,
        check=False,
    )
    assert result.returncode == 0, (
        "pnpm typecheck failed against the hydrogen template:\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
