"""Storefront template registry for ``shop_arena.gen``.

The registry centralizes the paths and commands that differ between
Hydrogen and React Vite storefront templates. Callers should resolve a
template once and pass its :class:`TemplateSpec` through path-sensitive
steps instead of branching on hardcoded ``hydrogen/`` paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

TemplateId = Literal["hydrogen", "react-vite"]
"""Supported storefront template ids."""

DEFAULT_TEMPLATE_ID: Final[TemplateId] = "hydrogen"
"""Default storefront template. Hydrogen remains the default."""


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    """Static metadata for one storefront template.

    Attributes:
        id: Stable CLI/config template id.
        source_dir: Vendored template directory shipped with ``shop_arena``.
        app_dir: Run-relative generated storefront directory.
        env_file: Path to the env file relative to ``app_dir``.
        install_command: Dependency install command.
        dev_command: Development server command.
        typecheck_command: Typecheck command used by build-loop verifiers.
        build_command: Production build command.
        health_path: HTTP health path exposed by the template server.
        run_navigation_primitive_verifier: Whether the Hydrogen-specific
            navigation primitive verifier applies to this template.
    """

    id: TemplateId
    source_dir: Path
    app_dir: Path
    env_file: Path
    install_command: tuple[str, ...]
    dev_command: tuple[str, ...]
    typecheck_command: tuple[str, ...]
    build_command: tuple[str, ...]
    health_path: str
    run_navigation_primitive_verifier: bool

    @property
    def env_path(self) -> Path:
        """Return the run-relative env path for this template."""
        return self.app_dir / self.env_file


_TEMPLATES_ROOT: Final[Path] = Path(__file__).resolve().parent / "templates"

_INSTALL_COMMAND: Final[tuple[str, ...]] = (
    "pnpm",
    "install",
    "--ignore-workspace",
    "--frozen-lockfile",
)

_REGISTRY: Final[dict[TemplateId, TemplateSpec]] = {
    "hydrogen": TemplateSpec(
        id="hydrogen",
        source_dir=_TEMPLATES_ROOT / "hydrogen",
        app_dir=Path("hydrogen"),
        env_file=Path(".env"),
        install_command=_INSTALL_COMMAND,
        dev_command=("pnpm", "dev"),
        typecheck_command=("pnpm", "tsc", "--noEmit"),
        build_command=("pnpm", "build"),
        health_path="/health",
        run_navigation_primitive_verifier=True,
    ),
    "react-vite": TemplateSpec(
        id="react-vite",
        source_dir=_TEMPLATES_ROOT / "react-vite",
        app_dir=Path("react-vite"),
        env_file=Path(".env"),
        install_command=_INSTALL_COMMAND,
        dev_command=("pnpm", "dev"),
        typecheck_command=("pnpm", "typecheck"),
        build_command=("pnpm", "build"),
        health_path="/health",
        run_navigation_primitive_verifier=False,
    ),
}


def get_template(template_id: TemplateId) -> TemplateSpec:
    """Return the registry entry for ``template_id``."""
    return _REGISTRY[template_id]


def template_ids() -> tuple[TemplateId, ...]:
    """Return supported template ids in stable CLI order."""
    return ("hydrogen", "react-vite")


__all__ = [
    "DEFAULT_TEMPLATE_ID",
    "TemplateId",
    "TemplateSpec",
    "get_template",
    "template_ids",
]
