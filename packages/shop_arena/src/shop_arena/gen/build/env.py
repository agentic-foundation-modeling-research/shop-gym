"""Phase 4 env-setup steps (spec §5.5.1).

Two pre-loop steps that prepare the run workspace before
:func:`harness.run_plan_exec_loop` is invoked:

* :class:`CloneTemplateStep` (id ``clone_template``) — recursively
  copies the vendored Hydrogen template at
  ``packages/shop_arena/src/shop_arena/gen/templates/hydrogen/`` into
  ``<out_dir>/hydrogen/``. The template ships inside the wheel, so
  the source path is resolved at runtime from this module's location;
  a missing template directory is a packaging bug, not a user error.

* :class:`WriteEnvFileStep` (id ``write_env_file``) — picks a free
  TCP port, writes ``<out_dir>/hydrogen/.env`` with
  ``PUBLIC_STORE_DOMAIN=http://localhost:<port>`` (the resolved
  sidecar URL the build harness loop is going to spawn) plus the
  mock storefront tokens the Hydrogen runtime expects to find on
  ``process.env``. Overwrites the placeholder ``.env`` shipped in
  the template.

Both steps belong to the ``build`` phase and are deliberately
side-effect-only on disk: they write into ``<out_dir>`` and do not
spawn any subprocess (the sidecar is owned by the T5.2
``start_sidecar`` step).

Module is import-safe: no I/O, no env reads, no side effects at
import.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import socket
from pathlib import Path
from typing import Final, cast

from shop_arena.gen.steps.base import InputRef, StepContext, StepInput
from shop_arena.gen.template_registry import TemplateId, TemplateSpec, get_template

_PHASE: Final[str] = "build"

_CLONE_STEP_ID: Final[str] = "clone_template"
_CLONE_STEP_VERSION: Final[int] = 3
CLONE_TEMPLATE_STEP_VERSION: Final[int] = _CLONE_STEP_VERSION
"""Public clone-template version used by downstream cache fingerprints."""

_WRITE_ENV_STEP_ID: Final[str] = "write_env_file"
_WRITE_ENV_STEP_VERSION: Final[int] = 1

_HYDROGEN_DIR: Final[Path] = Path("hydrogen")
"""Run-relative path the template is cloned into (spec §5.5.1)."""

_TEMPLATE_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "templates" / "hydrogen"
"""Vendored Hydrogen template shipped with the package wheel."""

_TEMPLATE_METADATA: Final[Path] = Path(".shop_gen") / "template.json"
"""Run-relative template metadata path."""

_CLONE_SENTINEL: Final[Path] = _HYDROGEN_DIR / "package.json"
"""Single sentinel output for ``clone_template``.

Declaring every file under ``hydrogen/`` as an output would inflate
the runner's missing-output check to ~90 entries (spec §5.7). The
canonical ``package.json`` is sufficient: the template ships it, the
copy is byte-faithful, and it is never the only file the user might
delete to invalidate the clone.
"""

_ENV_FILE: Final[Path] = _HYDROGEN_DIR / ".env"
"""Run-relative path to the ``.env`` file ``write_env_file`` writes."""

_DEFAULT_HOST: Final[str] = "localhost"
"""Hostname embedded in ``PUBLIC_STORE_DOMAIN`` (spec §5.5.1)."""

# Mock storefront-API credentials. The Hydrogen runtime reads these
# off ``process.env`` (see ``templates/hydrogen/server.mjs``) and the
# storefront client validates them as opaque strings; the local
# sidecar at ``PUBLIC_STORE_DOMAIN`` ignores them. Stable values keep
# the ``.env`` byte-deterministic up to the dynamic port.
_MOCK_SESSION_SECRET: Final[str] = "shop-gen-mock-secret"
_MOCK_STOREFRONT_API_TOKEN: Final[str] = "shop-gen-mock-token"
_MOCK_STOREFRONT_ID: Final[str] = "shop-gen-mock"

_DEFAULT_FOOTER_MENU_HANDLE: Final[str] = "footer"
"""Fallback handle written to ``PUBLIC_FOOTER_MENU_HANDLES`` when the
caller does not supply ``footer_menu_handles`` (T3.5 / spec §N5).

Mirrors the ``DEFAULT_FOOTER_MENU_HANDLE`` constant the template's
``app/root.tsx`` loader uses (T3.2) so the env-file writer and the
Hydrogen runtime agree on the single-menu fallback without coupling.
"""


class CloneTemplateStep:
    """Phase 4 ``clone_template`` step (spec §5.5.1).

    Recursively copies the vendored Hydrogen template into
    ``<out_dir>/hydrogen/`` so subsequent build-loop steps have a
    mutable work surface. The copy is byte-faithful: the template
    ships a placeholder ``.env`` containing ``SESSION_SECRET="foobar"``
    and the copy preserves it; the downstream :class:`WriteEnvFileStep`
    overwrites that file with the resolved sidecar URL.

    Attributes:
        id: Step id (``clone_template``).
        phase: ``build``.
        inputs: Empty. The template ships inside the package; bumping
            :attr:`version` is the documented way to invalidate
            cached clones (spec §5.7.1).
        outputs: ``[hydrogen/package.json]`` — single staleness sentinel.
            See :data:`_CLONE_SENTINEL` for the rationale.
        depends_on: Empty.
        version: Bumped when the template is rev'd (spec §5.7.1).
    """

    def __init__(self, *, template_id: TemplateId = "hydrogen") -> None:
        """Build the step with no per-run configuration."""
        self._template: TemplateSpec = get_template(template_id)
        self.id: str = _CLONE_STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = []
        self.outputs: list[Path] = [self._template.app_dir / "package.json"]
        self.depends_on: list[str] = []
        self.version: int = _CLONE_STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Recursively copy the vendored template into ``<out_dir>/hydrogen/``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is ignored — the
                copy is fully deterministic and never invokes the LLM.

        Raises:
            FileNotFoundError: The vendored template directory is
                missing from the installed package (packaging bug).
        """
        source_dir = _TEMPLATE_DIR if self._template.id == "hydrogen" else self._template.source_dir
        if not source_dir.is_dir():
            raise FileNotFoundError(
                f"{self._template.id} template not found at {source_dir}; "
                "this indicates a broken shop_arena install.",
            )
        target = ctx.out_dir / self._template.app_dir
        # ``copytree`` rejects an existing destination unless
        # ``dirs_exist_ok=True``; re-runs are legitimate (the runner
        # may force-rerun via ``--from`` even when outputs already
        # exist) so we permit overwrite. The downstream
        # ``write_env_file`` step is the only writer outside this
        # tree, and the harness loop owns mutations after Phase 4
        # env setup completes.
        #
        # ``ignore`` skips any ``node_modules/`` that may have
        # accumulated in the template directory (e.g. from an
        # exploratory ``pnpm install`` run by a developer). Pnpm's
        # strict layout uses symlinks to keep a single physical
        # copy of every package; ``shutil.copytree`` defaults to
        # ``symlinks=False`` and would dereference those symlinks,
        # producing a tree with multiple physical copies of
        # ``react`` / ``react-dom``. The subsequent
        # ``pnpm install --frozen-lockfile`` rebuilds top-level
        # symlinks but does not audit the inner ``.pnpm/<pkg>/``
        # tree, so the duplicates persist and break SSR with a
        # ``Cannot read properties of null (reading 'useContext')``
        # crash. ``node_modules/`` belongs to the install step,
        # never to the clone step.
        #
        # We also actively remove any ``node_modules/`` already sitting
        # in the destination. ``copytree(dirs_exist_ok=True)`` does not
        # descend into directories listed in ``ignore`` — it neither
        # writes them nor cleans them up — so a corrupted tree from
        # before this step shipped its ``ignore`` filter would persist
        # forever otherwise. ``node_modules/`` is owned exclusively by
        # the downstream ``pnpm install`` step, so wiping it here is
        # safe.
        target_node_modules = target / "node_modules"
        if target_node_modules.exists():
            shutil.rmtree(target_node_modules)
        shutil.copytree(
            source_dir,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("node_modules"),
        )
        _write_template_metadata(ctx.out_dir, self._template, source_dir)


class WriteEnvFileStep:
    """Phase 4 ``write_env_file`` step (spec §5.5.1).

    Picks a free TCP port and writes ``<out_dir>/hydrogen/.env`` with
    the resolved sidecar URL (``PUBLIC_STORE_DOMAIN=http://localhost:<port>``)
    plus the mock storefront credentials the Hydrogen runtime expects
    on ``process.env``. The downstream :class:`start_sidecar` step
    (T5.2) reads the port back out of this file before spawning the
    ``shop-backend`` subprocess.

    Port selection happens at run time via ``socket.bind(0)``; a small
    race window exists between selection and the sidecar's listen,
    which matches the existing ``validate_hosting`` pattern (spec §5.4).

    Also emits ``PUBLIC_FOOTER_MENU_HANDLES`` as a CSV the template's
    ``app/root.tsx`` loader (T3.2) parses to fan out per-handle footer
    menu queries. When ``footer_menu_handles`` is left unset (or
    normalizes to empty after trimming), the line falls back to
    ``PUBLIC_FOOTER_MENU_HANDLES=footer`` so existing single-menu
    artifacts keep rendering their single-column footer (spec §N5).

    Attributes:
        id: Step id (``write_env_file``).
        phase: ``build``.
        inputs: One :class:`StepInput` referencing ``clone_template``
            so the runner cascades staleness when the template is
            re-cloned.
        outputs: ``[hydrogen/.env]``.
        depends_on: ``[clone_template]``.
        version: Bumped when the env-file schema changes (spec §5.7.1).
    """

    def __init__(
        self,
        *,
        template_id: TemplateId = "hydrogen",
        footer_menu_handles: list[str] | None = None,
    ) -> None:
        """Build the step bound to the ``clone_template`` upstream.

        Args:
            footer_menu_handles: Optional list of footer menu handles
                to emit as ``PUBLIC_FOOTER_MENU_HANDLES``. Each entry
                is whitespace-trimmed and deduplicated (preserving
                first-occurrence order) to match the loader's parser
                in ``app/root.tsx``. ``None`` or an all-empty input
                falls back to ``["footer"]`` so legacy single-menu
                artifacts keep working.
        """
        self._template: TemplateSpec = get_template(template_id)
        self._footer_menu_handles: tuple[str, ...] = _normalize_footer_handles(
            footer_menu_handles,
        )
        self.id: str = _WRITE_ENV_STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [StepInput(step_id=_CLONE_STEP_ID)]
        self.outputs: list[Path] = [self._template.env_path]
        self.depends_on: list[str] = [_CLONE_STEP_ID]
        self.version: int = _WRITE_ENV_STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Pick a free port and write the ``.env`` file.

        Args:
            ctx: Execution context. ``ctx.runtime`` is ignored — the
                write is fully deterministic up to the dynamic port.

        Raises:
            FileNotFoundError: ``<out_dir>/hydrogen/`` does not exist
                (the upstream ``clone_template`` step did not run).
        """
        app_dir = ctx.out_dir / self._template.app_dir
        if not app_dir.is_dir():
            raise FileNotFoundError(
                f"{self._template.id} tree not found at {app_dir}; did clone_template run?",
            )
        port = _allocate_free_port()
        env_path = ctx.out_dir / self._template.env_path
        env_path.write_text(
            _render_env_file(port, self._footer_menu_handles),
            encoding="utf-8",
        )


def _render_env_file(port: int, footer_menu_handles: tuple[str, ...]) -> str:
    """Render the ``.env`` body for a sidecar listening on ``port``.

    The leading comment matches the placeholder ``.env`` shipped in
    the template so a diff against the original points at exactly
    one line (the ``PUBLIC_STORE_DOMAIN`` value).

    Args:
        port: TCP port the sidecar will bind to.
        footer_menu_handles: Already-normalized footer menu handles to
            emit as a CSV value for ``PUBLIC_FOOTER_MENU_HANDLES``.
            Must be non-empty; the caller is expected to apply
            :func:`_normalize_footer_handles` (which guarantees the
            ``footer`` fallback) before passing the tuple in.

    Returns:
        Contents of the ``.env`` file, terminated by a newline.
    """
    lines = (
        "# Resolved sidecar URL written by shop_arena.gen write_env_file (spec §5.5.1).",
        f"PUBLIC_STORE_DOMAIN=http://{_DEFAULT_HOST}:{port}",
        f"SHOP_BACKEND_URL=http://{_DEFAULT_HOST}:{port}",
        f"SESSION_SECRET={_MOCK_SESSION_SECRET}",
        f"PUBLIC_STOREFRONT_API_TOKEN={_MOCK_STOREFRONT_API_TOKEN}",
        f"PUBLIC_STOREFRONT_ID={_MOCK_STOREFRONT_ID}",
        f"PUBLIC_FOOTER_MENU_HANDLES={','.join(footer_menu_handles)}",
    )
    return "\n".join(lines) + "\n"


def _allocate_free_port() -> int:
    """Bind a TCP socket to port 0 and return the kernel-assigned port.

    The socket is closed before returning, so a small race window
    exists between port selection and the sidecar's listen. This
    matches the pattern used in :mod:`shop_arena.gen.data_validation.hosting_check`
    and is acceptable for the single-machine, sequential build-loop
    invocation in v0.1.
    """
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return cast("int", sock.getsockname()[1])


def _normalize_footer_handles(raw: list[str] | None) -> tuple[str, ...]:
    """Trim, drop empties, and deduplicate footer menu handles.

    Mirrors the parser in ``templates/hydrogen/app/root.tsx`` (T3.2)
    so the env file the writer emits round-trips byte-identically
    through the Hydrogen loader's ``parseFooterMenuHandles`` helper.

    Args:
        raw: Caller-supplied list of handles, or ``None``.

    Returns:
        Normalized tuple of handles. Falls back to
        ``(_DEFAULT_FOOTER_MENU_HANDLE,)`` when ``raw`` is ``None``
        or every entry is empty / whitespace-only.
    """
    if not raw:
        return (_DEFAULT_FOOTER_MENU_HANDLE,)
    seen: set[str] = set()
    handles: list[str] = []
    for entry in raw:
        handle = entry.strip()
        if not handle or handle in seen:
            continue
        seen.add(handle)
        handles.append(handle)
    if not handles:
        return (_DEFAULT_FOOTER_MENU_HANDLE,)
    return tuple(handles)


def _write_template_metadata(
    out_dir: Path,
    template: TemplateSpec,
    source_dir: Path,
) -> None:
    """Persist selected template metadata for host/final-eval consumers."""
    metadata = {
        "template_id": template.id,
        "app_dir": template.app_dir.as_posix(),
        "source_dir": str(source_dir),
    }
    path = out_dir / _TEMPLATE_METADATA
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "CloneTemplateStep",
    "WriteEnvFileStep",
]
