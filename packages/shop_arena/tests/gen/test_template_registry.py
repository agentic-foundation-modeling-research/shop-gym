"""Tests for the storefront template registry."""

from __future__ import annotations

from pathlib import Path

from shop_arena.gen.template_registry import (
    DEFAULT_TEMPLATE_ID,
    get_template,
    template_ids,
)


def test_template_registry_keeps_hydrogen_as_default() -> None:
    """Hydrogen remains the default storefront template."""
    assert DEFAULT_TEMPLATE_ID == "hydrogen"
    assert template_ids()[0] == "hydrogen"


def test_template_registry_exposes_hydrogen_and_react_vite_specs() -> None:
    """Both supported templates declare clone paths and commands."""
    hydrogen = get_template("hydrogen")
    react_vite = get_template("react-vite")

    assert hydrogen.app_dir == Path("hydrogen")
    assert hydrogen.env_path == Path("hydrogen") / ".env"
    assert hydrogen.source_dir.name == "hydrogen"
    assert hydrogen.run_navigation_primitive_verifier is True

    assert react_vite.app_dir == Path("react-vite")
    assert react_vite.env_path == Path("react-vite") / ".env"
    assert react_vite.source_dir.name == "react-vite"
    assert react_vite.typecheck_command == ("pnpm", "typecheck")
    assert react_vite.build_command == ("pnpm", "build")
    assert react_vite.health_path == "/health"
    assert react_vite.run_navigation_primitive_verifier is False
