"""Tests for :mod:`shop_arena.env_eval.visualize` and the
``shop-env-eval visualize`` CLI subcommand.

The visualizer is post-measurement: it reads ``transition/graph.json``
from a run directory and writes a self-contained HTML file. These tests
cover:

* successful render with the default and overridden output paths,
* byte-stable output for fixed inputs (matches the project's SC5
  convention for derived artifacts),
* shape validation — missing keys, wrong types, and missing graph file
  raise :class:`shop_arena.env_eval.errors.EnvEvalError`,
* the embedded JS payload escapes ``</`` so a stray closing-tag in any
  data field cannot break out of the ``<script>`` block,
* the CLI subcommand prints the absolute path on stdout and surfaces
  errors via exit code ``2``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shop_arena.env_eval import cli, render_graph_html
from shop_arena.env_eval.errors import EnvEvalError


def _write_graph(run_dir: Path, graph: dict[str, Any]) -> Path:
    """Write a ``graph.json`` fixture under ``<run_dir>/transition/``."""
    target = run_dir / "transition" / "graph.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(graph), encoding="utf-8")
    return target


def _minimal_graph() -> dict[str, Any]:
    return {
        "nodes": [
            {
                "canonical_id": "/",
                "representative_url": "https://example.test/",
                "kind": "url",
                "state_name": None,
            },
            {
                "canonical_id": "/cart",
                "representative_url": "https://example.test/cart",
                "kind": "url",
                "state_name": None,
            },
            {
                "canonical_id": "state:/:cart_drawer",
                "representative_url": "https://example.test/",
                "kind": "state",
                "state_name": "cart_drawer",
            },
        ],
        "edges": [
            {
                "source": "/",
                "target": "/cart",
                "label": "click(https://example.test/cart)",
                "action": "click",
            },
            {
                "source": "/",
                "target": "state:/:cart_drawer",
                "label": "click(add_to_cart)",
                "action": "click",
            },
        ],
        "seeds": ["/", "/cart"],
    }


def test_render_writes_default_html_path(tmp_path: Path) -> None:
    """Default output is ``<run_dir>/transition/graph.html``."""
    _write_graph(tmp_path, _minimal_graph())

    out = render_graph_html(tmp_path)

    assert out == (tmp_path / "transition" / "graph.html").resolve()
    assert out.is_file()


def test_render_honours_explicit_out_path(tmp_path: Path) -> None:
    """``out_path`` overrides the default and parent dirs are created."""
    _write_graph(tmp_path, _minimal_graph())
    explicit = tmp_path / "viz" / "deep" / "graph.html"

    out = render_graph_html(tmp_path, out_path=explicit)

    assert out == explicit.resolve()
    assert explicit.is_file()


def test_rendered_html_embeds_graph_payload(tmp_path: Path) -> None:
    """Seeds, canonical ids, and state names appear in the rendered HTML."""
    _write_graph(tmp_path, _minimal_graph())

    out = render_graph_html(tmp_path)
    body = out.read_text(encoding="utf-8")

    assert "vis-network" in body
    assert '"/cart"' in body
    assert '"cart_drawer"' in body
    assert '"seeds":["/","/cart"]' in body


def test_render_is_byte_stable_for_fixed_input(tmp_path: Path) -> None:
    """Two renders of the same graph produce byte-identical HTML (SC5)."""
    _write_graph(tmp_path, _minimal_graph())
    first_out = tmp_path / "first.html"
    second_out = tmp_path / "second.html"

    render_graph_html(tmp_path, out_path=first_out)
    render_graph_html(tmp_path, out_path=second_out)

    assert first_out.read_bytes() == second_out.read_bytes()


def test_render_escapes_script_close_tag_in_payload(tmp_path: Path) -> None:
    """``</`` in any string field is rewritten to ``<\\/`` so a stray
    closing tag inside JSON data cannot terminate the ``<script>`` block.
    """
    graph = _minimal_graph()
    graph["nodes"][0]["representative_url"] = "https://example.test/</script>x"
    _write_graph(tmp_path, graph)

    out = render_graph_html(tmp_path)
    body = out.read_text(encoding="utf-8")

    assert "</script>x" not in body.split("</script>")[0]
    assert "<\\/script>" in body


def test_render_rejects_missing_run_dir(tmp_path: Path) -> None:
    """``run_dir`` that does not exist surfaces a clear :class:`EnvEvalError`."""
    with pytest.raises(EnvEvalError, match="run_dir is not a directory"):
        render_graph_html(tmp_path / "nope")


def test_render_rejects_missing_graph_json(tmp_path: Path) -> None:
    """An empty run directory raises rather than producing empty HTML."""
    with pytest.raises(EnvEvalError, match=r"graph\.json not found"):
        render_graph_html(tmp_path)


def test_render_rejects_invalid_json(tmp_path: Path) -> None:
    """Malformed JSON surfaces :class:`EnvEvalError`, not :class:`json.JSONDecodeError`."""
    target = tmp_path / "transition" / "graph.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not json", encoding="utf-8")

    with pytest.raises(EnvEvalError, match="not valid JSON"):
        render_graph_html(tmp_path)


@pytest.mark.parametrize("missing_key", ["nodes", "edges", "seeds"])
def test_render_rejects_missing_top_level_key(tmp_path: Path, missing_key: str) -> None:
    """Each of ``nodes``/``edges``/``seeds`` is required."""
    graph = _minimal_graph()
    del graph[missing_key]
    _write_graph(tmp_path, graph)

    with pytest.raises(EnvEvalError, match=f"missing required key '{missing_key}'"):
        render_graph_html(tmp_path)


def test_render_rejects_node_without_canonical_id(tmp_path: Path) -> None:
    """Nodes must include both ``canonical_id`` and ``representative_url``."""
    graph = _minimal_graph()
    graph["nodes"].append({"kind": "url"})
    _write_graph(tmp_path, graph)

    with pytest.raises(EnvEvalError, match="must include canonical_id"):
        render_graph_html(tmp_path)


def test_render_rejects_edge_without_endpoints(tmp_path: Path) -> None:
    """Edges must include both ``source`` and ``target``."""
    graph = _minimal_graph()
    graph["edges"].append({"label": "click(/foo)"})
    _write_graph(tmp_path, graph)

    with pytest.raises(EnvEvalError, match="must include source and target"):
        render_graph_html(tmp_path)


def test_cli_visualize_prints_absolute_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``shop-env-eval visualize`` emits the rendered HTML path on stdout."""
    _write_graph(tmp_path, _minimal_graph())

    code = cli.main(["visualize", str(tmp_path)])
    captured = capsys.readouterr()

    assert code == 0
    expected = (tmp_path / "transition" / "graph.html").resolve()
    assert captured.out.strip() == str(expected)
    assert expected.is_file()


def test_cli_visualize_honours_out_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--out`` redirects the output path."""
    _write_graph(tmp_path, _minimal_graph())
    explicit = tmp_path / "elsewhere.html"

    code = cli.main(["visualize", str(tmp_path), "--out", str(explicit)])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out.strip() == str(explicit.resolve())
    assert explicit.is_file()


def test_cli_visualize_returns_exit_2_on_missing_graph(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A run dir without ``graph.json`` exits ``2`` and writes to stderr."""
    code = cli.main(["visualize", str(tmp_path)])
    captured = capsys.readouterr()

    assert code == 2
    assert "graph.json not found" in captured.err
