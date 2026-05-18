"""Render the EnvEval transition graph as an interactive HTML page.

The transition graph (``<run_dir>/transition/graph.json``) is the union
of the structural BFS pass (spec §5.5.1) and the stateful in-page rule
pass (§5.5.2). This module bundles those nodes and edges into a
self-contained HTML file backed by ``vis-network`` (loaded at view time
from a CDN) so a reviewer can open the file in any browser and inspect
the graph without installing extra tooling.

The renderer is post-measurement: it never re-walks the storefront,
runs no LLM calls, and depends only on the on-disk ``graph.json``
produced by the pipeline. Output is byte-stable for fixed inputs — the
template is loaded verbatim and the graph payload is JSON-encoded with
deterministic options — so committed HTML files round-trip cleanly.

Public surface:

* :func:`render_graph_html` — library entrypoint, re-exported from
  :mod:`shop_arena.env_eval.visualize` and the top-level package.

The CLI subcommand ``shop-env-eval visualize`` (see
:mod:`shop_arena.env_eval.cli`) is a thin wrapper around this function.

Asset: the HTML template lives next to this module as
``transition_graph.html`` and is loaded via :mod:`importlib.resources`
(mirrors the ``observation/prompt.md`` and
``transition/state_prompt.md`` patterns).
"""

from __future__ import annotations

import html
import json
from importlib import resources
from pathlib import Path
from typing import Any, Final, cast

from shop_arena.env_eval._version import __version__
from shop_arena.env_eval.errors import EnvEvalError

__all__ = ["render_graph_html"]

#: Package containing :data:`_TEMPLATE_FILENAME` (loaded via ``importlib.resources``).
_TEMPLATE_PACKAGE: Final[str] = "shop_arena.env_eval.visualize"

#: Filename of the HTML template shipped alongside this module.
_TEMPLATE_FILENAME: Final[str] = "transition_graph.html"

#: Sentinel replaced with the JSON-encoded graph payload (parseable as a JS
#: literal — *not* a string).
_GRAPH_JSON_TOKEN: Final[str] = "__ENV_EVAL_GRAPH_JSON__"

#: Sentinel replaced with the HTML-escaped run title shown in the header.
_TITLE_TOKEN: Final[str] = "__ENV_EVAL_TITLE__"

#: Sentinel replaced with :data:`shop_arena.env_eval.__version__`.
_VERSION_TOKEN: Final[str] = "__ENV_EVAL_VERSION__"

#: Path to ``transition/graph.json`` relative to the run directory.
_GRAPH_RELPATH: Final[tuple[str, str]] = ("transition", "graph.json")

#: Default output filename relative to the run directory.
_DEFAULT_HTML_RELPATH: Final[tuple[str, str]] = ("transition", "graph.html")


def render_graph_html(
    run_dir: Path | str,
    out_path: Path | str | None = None,
) -> Path:
    """Write an interactive HTML view of an EnvEval transition graph.

    The graph payload is read from
    ``<run_dir>/transition/graph.json``; the rendered HTML embeds it
    verbatim so the resulting file is fully self-contained apart from
    the ``vis-network`` CDN script tag.

    Args:
        run_dir: EnvEval run directory written by
            :func:`shop_arena.env_eval.evaluate`.
        out_path: Output HTML path. Defaults to
            ``<run_dir>/transition/graph.html``. Parent directories are
            created if needed.

    Returns:
        Absolute path to the rendered HTML file.

    Raises:
        EnvEvalError: ``run_dir`` is not a directory, ``graph.json`` is
            missing or malformed, or the JSON does not match the
            expected ``{nodes, edges, seeds}`` shape.
    """
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise EnvEvalError(f"run_dir is not a directory: {run_dir}")

    graph_path = run_dir.joinpath(*_GRAPH_RELPATH)
    if not graph_path.is_file():
        raise EnvEvalError(f"graph.json not found at {graph_path}")
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EnvEvalError(f"graph.json is not valid JSON: {graph_path}") from exc
    _validate_graph(graph, source=graph_path)

    out = Path(out_path) if out_path is not None else run_dir.joinpath(*_DEFAULT_HTML_RELPATH)
    title = f"{run_dir.parent.name}/{run_dir.name}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render(graph, title=title), encoding="utf-8")
    return out.resolve()


def _validate_graph(graph: object, *, source: Path) -> None:
    """Reject anything that is not a ``{nodes, edges, seeds}`` envelope.

    Validation is intentionally narrow: the renderer only needs the
    keys it actually reads. The closed schema for the graph itself
    lives in :mod:`shop_arena.env_eval.transition.graph`; re-validating
    here would couple the visualizer to that schema and force lock-step
    upgrades.
    """
    if not isinstance(graph, dict):
        raise EnvEvalError(f"graph.json must be a JSON object: {source}")
    payload = cast("dict[str, Any]", graph)
    for key in ("nodes", "edges", "seeds"):
        if key not in payload:
            raise EnvEvalError(f"graph.json missing required key {key!r}: {source}")
        if not isinstance(payload[key], list):
            raise EnvEvalError(f"graph.json[{key!r}] must be a list: {source}")
    for i, node in enumerate(cast("list[Any]", payload["nodes"])):
        if (
            not isinstance(node, dict)
            or "canonical_id" not in node
            or "representative_url" not in node
        ):
            raise EnvEvalError(
                f"graph.json.nodes[{i}] must include canonical_id and representative_url: {source}",
            )
    for i, edge in enumerate(cast("list[Any]", payload["edges"])):
        if not isinstance(edge, dict) or "source" not in edge or "target" not in edge:
            raise EnvEvalError(
                f"graph.json.edges[{i}] must include source and target: {source}",
            )


def _render(graph: dict[str, Any], *, title: str) -> str:
    """Return the rendered HTML body with ``graph`` embedded as JS state."""
    template = (
        resources.files(_TEMPLATE_PACKAGE).joinpath(_TEMPLATE_FILENAME).read_text(encoding="utf-8")
    )
    payload = json.dumps(graph, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    return (
        template.replace(_GRAPH_JSON_TOKEN, payload)
        .replace(_TITLE_TOKEN, html.escape(title, quote=True))
        .replace(_VERSION_TOKEN, html.escape(__version__, quote=True))
    )
