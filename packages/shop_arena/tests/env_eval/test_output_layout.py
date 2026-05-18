"""End-to-end output-layout acceptance test for ``evaluate()`` (M1+M3).

Pins the run-directory layout described in spec §5.6 to the artifacts
:mod:`shop_arena.env_eval.pipeline.evaluate` actually emits in M1 (page
discovery + observation) and M3 (action layer). Drives the pipeline against
a stubbed BrowserGym session so the test stays hermetic — no Chromium, no
LLM, no network.

Coverage (impl-plan M1 "Output-layout acceptance test" + M3 wiring):

* ``pages.json`` lives at the run-dir root and validates against
  :class:`shop_arena.env_eval.pages.PagesDoc`.
* ``observation/`` contains exactly ``<bucket>.{png,axtree.json,axtree.txt,rubric.json}``
  for every measurable bucket and *no* artifacts for ``not_found`` ones.
* ``action/`` contains exactly ``<bucket>.action_space.json`` for every
  measurable bucket and *no* artifacts for ``not_found`` ones (spec §5.6).
* ``metrics.json`` lives at the run-dir root and validates against
  :class:`shop_arena.env_eval.schema.metrics.Metrics`.
* ``manifest.json`` lives at the run-dir root and validates against
  :class:`shop_arena.env_eval.schema.manifest.Manifest`.
* M1+M3 do *not* yet populate ``transition/`` (lands in M4-M5).
* No unexpected files leak into the run dir at the top level.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from shop_arena.env_eval import pipeline as pipeline_mod
from shop_arena.env_eval.config import EvalConfig
from shop_arena.env_eval.pages import (
    PAGES_JSON_FILENAME,
    CartAndSearch,
    PageNotFound,
    PageOk,
    PagesDoc,
    SearchPageOk,
    write_pages_json,
)
from shop_arena.env_eval.pipeline import evaluate
from shop_arena.env_eval.schema.manifest import MANIFEST_JSON_FILENAME, Manifest
from shop_arena.env_eval.schema.metrics import Metrics, NotFound

_BASE_URL = "https://example-shop.com/"

_NODE_FOLDERS: tuple[str, ...] = (
    "home",
    "collections__template",
    "policies__template",
    "cart",
    "search",
)
_OBSERVATION_SUFFIXES: tuple[str, ...] = (".png", ".axtree.json", ".axtree.txt", ".rubric.json")
_ACTION_SUFFIX: str = ".action_space.json"


def _sample_axtree() -> dict[str, Any]:
    """Tiny CDP-shaped axtree the renderer + stats helpers can chew on."""
    return {
        "nodes": [
            {
                "nodeId": "1",
                "role": {"value": "RootWebArea"},
                "name": {"value": "Home"},
                "childIds": ["2"],
            },
            {
                "nodeId": "2",
                "role": {"value": "link"},
                "name": {"value": "Shop"},
                "childIds": [],
                "browsergym_id": "a1",
            },
        ],
    }


class _StubPage:
    """Inert :class:`playwright.sync_api.Page` stand-in for BFS link scans."""

    url: str = "about:blank"

    def evaluate(self, _expression: str, *_args: object) -> list[Any]:
        return []


class _StubSession:
    """Records ``goto`` calls and serves canned axtree/screenshot."""

    def __init__(self) -> None:
        self.goto_calls: list[str] = []
        self.nav_count: int = 0
        self.page: _StubPage = _StubPage()

    def goto(self, url: str) -> None:
        self.goto_calls.append(url)
        self.nav_count += 1
        self.page.url = url

    def axtree(self) -> dict[str, Any]:
        return _sample_axtree()

    def screenshot(self) -> Any:
        return np.zeros((4, 6, 3), dtype=np.uint8)


@contextlib.contextmanager
def _stub_make_env(*_args: object, **_kwargs: object) -> Generator[_StubSession, None, None]:
    """Stand-in for :func:`shop_arena.env_eval.pipeline.make_env`."""
    yield _StubSession()


def _seed_pages_json(run_dir: Path) -> PagesDoc:
    """Write a representative ``pages.json`` so discovery is reused.

    ``product`` is intentionally ``not_found`` so the layout assertion
    can confirm that ``not_found`` buckets emit *zero* observation files.
    """
    doc = PagesDoc(
        base_url=_BASE_URL,
        homepage=PageOk(url="/", selected_by="input"),
        collection=PageOk(
            url="/collections/men",
            canonical_url="/collections/<*>",
            selected_by="first_href",
        ),
        product=PageNotFound(reason="no_product_link"),
        policy=PageOk(
            url="/policies/privacy-policy",
            canonical_url="/policies/<*>",
            selected_by="convention",
        ),
        cart_and_search=CartAndSearch(
            cart=PageOk(url="/cart", selected_by="convention"),
            search=SearchPageOk(
                url="/search?q=linen",
                query="linen",
                selected_by="collection_slug",
                raw_source="linen",
            ),
        ),
    )
    write_pages_json(doc, run_dir)
    return doc


def test_evaluate_produces_expected_run_dir_layout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``evaluate()`` writes the M1 slice of the spec §5.6 layout, and only that."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    result = evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir, no_rubric=True))

    # 1. Result points at the run dir + metrics.json.
    assert result.run_dir == run_dir
    assert result.metrics_path == run_dir / "metrics.json"

    # 2. Top-level run dir contains exactly the M1+M3+M4 published artifacts.
    top_level = {p.name for p in run_dir.iterdir()}
    assert top_level == {
        PAGES_JSON_FILENAME,
        "observation",
        "action",
        "transition",
        "metrics.json",
        MANIFEST_JSON_FILENAME,
    }, f"unexpected top-level entries: {top_level}"

    # 3. ``pages.json`` round-trips through the closed schema.
    pages_payload = json.loads((run_dir / PAGES_JSON_FILENAME).read_text(encoding="utf-8"))
    pages_doc = PagesDoc.model_validate(pages_payload)
    assert pages_doc.base_url == _BASE_URL
    assert isinstance(pages_doc.product, PageNotFound)

    # 4. ``observation/`` has exactly the expected per-transition-node artifact set.
    obs_dir = run_dir / "observation"
    assert obs_dir.is_dir()
    expected_obs_files = {
        f"{folder}{suffix}" for folder in _NODE_FOLDERS for suffix in _OBSERVATION_SUFFIXES
    } | {"index.json"}
    actual_obs_files = {p.name for p in obs_dir.iterdir()}
    assert actual_obs_files == expected_obs_files, (
        f"missing: {expected_obs_files - actual_obs_files}; "
        f"unexpected: {actual_obs_files - expected_obs_files}"
    )

    # 5. ``metrics.json`` validates and records aggregate observation metrics.
    metrics_payload = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    metrics = Metrics.model_validate(metrics_payload)
    assert metrics.shop.url == _BASE_URL
    assert isinstance(metrics.pages.product, NotFound)
    assert metrics.observation.node_count == len(_NODE_FOLDERS) * 2
    assert metrics.observation.interactive_count == len(_NODE_FOLDERS)

    # 6. ``manifest.json`` validates through the closed schema.
    manifest_payload = json.loads((run_dir / MANIFEST_JSON_FILENAME).read_text(encoding="utf-8"))
    manifest = Manifest.model_validate(manifest_payload)
    assert manifest.config.url == _BASE_URL
    assert manifest.config.out_dir == str(run_dir)
    assert manifest.llm_calls == 0

    # 7. ``action/`` has exactly one artifact per transition node plus index.
    action_dir = run_dir / "action"
    assert action_dir.is_dir()
    expected_action_files = {f"{folder}{_ACTION_SUFFIX}" for folder in _NODE_FOLDERS} | {
        "index.json",
    }
    actual_action_files = {p.name for p in action_dir.iterdir()}
    assert actual_action_files == expected_action_files, (
        f"missing: {expected_action_files - actual_action_files}; "
        f"unexpected: {actual_action_files - expected_action_files}"
    )

    # 8. ``transition/`` has graph/trace plus one folder per graph node (M4).
    transition_dir = run_dir / "transition"
    assert transition_dir.is_dir()
    assert (transition_dir / "graph.json").is_file()
    assert (transition_dir / "trace.jsonl").is_file()
    assert (transition_dir / "node" / "index.json").is_file()
    assert (transition_dir / "node" / "home" / "node.json").is_file()
    assert (transition_dir / "node" / "home" / "screenshot.png").is_file()
    assert (transition_dir / "node" / "home" / "axtree.json").is_file()


def test_evaluate_omits_artifacts_for_not_found_buckets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``not_found`` page entries do not create a product transition node.

    The node-driven layers only emit files for nodes captured by the transition
    graph. Because the seeded page discovery marks product as ``not_found`` and
    the stub BFS discovers no links, ``products__template`` is absent.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir, no_rubric=True))

    obs_dir = run_dir / "observation"
    for suffix in _OBSERVATION_SUFFIXES:
        artifact = obs_dir / f"products__template{suffix}"
        assert not artifact.exists(), f"unexpected artifact for not_found product node: {artifact}"
