"""``nav_coverage`` build-loop verifier (spec §5.5.3).

Asserts that every collection handle published in
``data/collections.json`` is reachable from the hydrogen navigation —
specifically, that the handle appears textually in at least one
``.tsx``/``.ts`` source file inside ``hydrogen/app/``. The check is
deliberately a substring scan rather than a JSX-AST traversal: the
agent is free to author the nav as a static array, an inlined route
table, or a query-driven loop, and a textual match is the most robust
signal that the handle is wired up at all.

Applicability mirrors the spec table: only ``gen_navigation``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final, cast

from harness.verifiers import Verdict, VerifierContext, VerifierResult

_NAME: Final[str] = "nav_coverage"
"""Verifier name (filesystem-safe; matches the spec table)."""

_HYDROGEN_APP_DIR: Final[str] = "hydrogen/app"
"""Path of the hydrogen ``app/`` tree relative to ``VerifierContext.artifact_dir``."""

_NAV_TASK_ID: Final[str] = "gen_navigation"
"""The single task this verifier gates."""

_SCAN_SUFFIXES: Final[frozenset[str]] = frozenset({".tsx", ".ts"})
"""Source-file extensions inspected for handle references."""


class NavCoverageVerifier:
    """Asserts every collection handle is reachable from the hydrogen nav.

    Attributes:
        name: ``"nav_coverage"`` — used as the per-verifier telemetry
            filename and the markdown section heading in
            ``feedback.md``.
    """

    name: str = _NAME

    def __init__(
        self,
        *,
        data_dir: Path,
        app_dir: Path = Path(_HYDROGEN_APP_DIR),
    ) -> None:
        """Build the verifier bound to a published ``data/`` directory.

        Args:
            data_dir: Filesystem path containing the published
                ``collections.json`` (typically
                ``<out_dir>/data/`` — the same directory the sidecar
                serves from).
            app_dir: Storefront ``app/`` directory relative to
                ``VerifierContext.artifact_dir``. Defaults to
                ``hydrogen/app`` for backward compatibility.
        """
        self._data_dir = data_dir
        self._app_dir = app_dir

    def applies_to(self, task_id: str) -> bool:
        """Match only ``gen_navigation`` (spec §5.5.3).

        Args:
            task_id: Selected task id.

        Returns:
            ``True`` iff ``task_id`` equals ``"gen_navigation"``.
        """
        return task_id == _NAV_TASK_ID

    def run(self, ctx: VerifierContext) -> VerifierResult:
        """Diff the collection handles against the hydrogen ``app/`` tree.

        Args:
            ctx: Verifier context. Reads ``ctx.artifact_dir`` to locate
                the hydrogen ``app/`` tree; ``ctx.runtime`` is unused.

        Returns:
            ``PASS`` when every collection handle appears in at least
            one ``.tsx``/``.ts`` source file under ``hydrogen/app/``.
            ``FAIL`` listing the missing handles otherwise.

            ``FAIL`` with explanatory feedback when ``data/collections.json``
            is missing or malformed, or the hydrogen tree is absent.
        """
        collections_path = self._data_dir / "collections.json"
        try:
            handles = _load_collection_handles(collections_path)
        except _DataLoadError as exc:
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=str(exc),
                details={"collections_path": str(collections_path)},
            )

        app_dir = ctx.artifact_dir / self._app_dir
        if not app_dir.is_dir():
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    "nav_coverage could not find the hydrogen app tree "
                    f"at `{self._app_dir.as_posix()}/`. Did `clone_template` run?"
                ),
                details={"app_dir": str(app_dir), "exists": False},
            )

        scanned_text = _read_app_tree(app_dir)
        missing = [h for h in handles if h not in scanned_text]
        if not missing:
            return VerifierResult(
                verdict=Verdict.PASS,
                details={"collections": len(handles), "missing": 0},
            )
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback=_render_failure_markdown(missing, total=len(handles)),
            details={
                "collections": len(handles),
                "missing": len(missing),
                "missing_handles": missing,
            },
        )


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


class _DataLoadError(RuntimeError):
    """Raised when ``data/collections.json`` cannot be loaded.

    The verifier surfaces the message verbatim as feedback markdown so
    a human reading the iteration's checks can immediately identify the
    workspace bug. Internal errors only — not part of the public API.
    """


def _load_collection_handles(path: Path) -> list[str]:
    """Return the ordered list of ``handle`` strings from ``collections.json``."""
    if not path.is_file():
        raise _DataLoadError(
            f"nav_coverage could not read `{path}`. Did Phase 2 publish `data/collections.json`?",
        )
    raw_text = path.read_text(encoding="utf-8")
    try:
        decoded: Any = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise _DataLoadError(
            f"nav_coverage: `{path}` is not valid JSON: {exc}",
        ) from exc
    if not isinstance(decoded, list):
        raise _DataLoadError(
            f"nav_coverage: `{path}` must be a JSON array, got {type(decoded).__name__}.",
        )

    handles: list[str] = []
    for index, entry in enumerate(cast("list[Any]", decoded)):
        if not isinstance(entry, dict):
            raise _DataLoadError(
                f"nav_coverage: collections[{index}] must be an object, "
                f"got {type(entry).__name__}.",
            )
        handle = cast("dict[str, Any]", entry).get("handle")
        if not isinstance(handle, str) or not handle:
            raise _DataLoadError(
                f"nav_coverage: collections[{index}] missing string 'handle'.",
            )
        handles.append(handle)
    if not handles:
        raise _DataLoadError(
            f"nav_coverage: `{path}` is empty; no collections to check.",
        )
    return handles


def _read_app_tree(app_dir: Path) -> str:
    """Concatenate every ``.tsx``/``.ts`` source file under ``app_dir`` into one buffer.

    A single concatenated string lets the per-handle membership check
    run as a constant-cost ``in`` against the full tree (spec §5.5.3
    is silent on per-file attribution). Files that fail to decode are
    silently skipped — the same posture the §5.6 brand scanner takes
    when it encounters a binary lookalike.
    """
    chunks: list[str] = []
    for path in sorted(app_dir.rglob("*")):
        if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    return "\n".join(chunks)


def _render_failure_markdown(missing: list[str], *, total: int) -> str:
    """Render the failure feedback body (one bullet per missing handle)."""
    lines = [
        f"`nav_coverage` failed: {len(missing)} of {total} collection "
        "handle(s) are not referenced anywhere under the storefront `app/` tree.",
        "",
        "Add a navigation entry (header, footer, or mega-menu) for each "
        "missing handle so it is reachable from the rendered storefront.",
        "",
        "Missing handles:",
    ]
    lines.extend(f"- `{handle}`" for handle in missing)
    return "\n".join(lines)


__all__ = ["NavCoverageVerifier"]
