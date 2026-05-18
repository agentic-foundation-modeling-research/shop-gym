"""Unit tests for :func:`shop_arena.env_eval.pipeline.evaluate` (M1+M2 tasks).

The orchestrator is exercised against a stub :class:`EnvEvalSession`, a
pre-written ``pages.json``, and a fake :class:`LLMVisionClient` so the tests
stay hermetic — no Chromium, no LLM, no network.  Covers the M1 contract
(per-bucket observation artifacts, schema-valid ``metrics.json``,
``EvalResult``) plus the M2 contract (rubric LLM call wired into the
pipeline; reuse skips the call when a non-stub artifact already exists).
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from shop_arena.env_eval import pipeline as pipeline_mod
from shop_arena.env_eval.config import EvalConfig
from shop_arena.env_eval.observation.rubric import (
    RUBRIC_PROMPT_VERSION,
    RUBRIC_RESPONSE_SCHEMA,
    RubricArtifact,
    write_rubric_artifact,
)
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
from shop_arena.env_eval.schema.metrics import (
    METRICS_SCHEMA_VERSION,
    RUBRIC_CATEGORIES,
    ActionSemanticCounts,
    NotFound,
    Rubric,
    load_metrics,
)
from shop_arena.env_eval.schema.metrics import (
    PageOk as MetricsPageOk,
)
from shop_arena.env_eval.schema.metrics import (
    SearchPageOk as MetricsSearchPageOk,
)
from shop_arena.env_eval.transition import node_artifacts as node_artifacts_mod
from shop_arena.env_eval.transition.graph import GraphEdge, GraphNode, TransitionGraph
from shop_arena.util._llm import VisionResponse

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BASE_URL = "https://example-shop.com/"
_NODE_FOLDERS = ("home", "collections__template", "policies__template", "cart", "search")


def _sample_axtree() -> dict[str, Any]:
    """Tiny CDP-shaped axtree the renderer + stats helpers can chew on."""
    return {
        "nodes": [
            {
                "nodeId": "1",
                "role": {"value": "RootWebArea"},
                "name": {"value": "Home"},
                "childIds": ["2", "3"],
            },
            {
                "nodeId": "2",
                "role": {"value": "link"},
                "name": {"value": "Shop"},
                "childIds": [],
                "browsergym_id": "a1",
            },
            {
                "nodeId": "3",
                "role": {"value": "button"},
                "name": {"value": "Add to cart"},
                "childIds": [],
                "browsergym_id": "b1",
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


@dataclass
class _FakeRubricClient:
    """Fake :class:`shop_arena.util._llm.LLMVisionClient` for hermetic tests."""

    model: str = "claude-sonnet-4-6"
    response_factory: Callable[[], VisionResponse] | None = None
    calls: list[dict[str, Any]] = field(default_factory=lambda: cast("list[dict[str, Any]]", []))

    def call(
        self,
        *,
        prompt: str,
        images: Sequence[bytes],
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        self.calls.append(
            {
                "prompt": prompt,
                "images": tuple(images),
                "schema": schema,
                "temperature": temperature,
            },
        )
        if self.response_factory is None:
            parsed = dict.fromkeys(RUBRIC_CATEGORIES, 0)
            return VisionResponse(parsed=parsed, raw_response=json.dumps(parsed, sort_keys=True))
        return self.response_factory()


@contextlib.contextmanager
def _stub_make_env(*_args: object, **_kwargs: object) -> Generator[_StubSession, None, None]:
    """Stand-in for :func:`shop_arena.env_eval.pipeline.make_env`."""
    yield _StubSession()


def _seed_pages_json(run_dir: Path) -> PagesDoc:
    """Write a representative ``pages.json`` so discovery is reused."""
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


@pytest.fixture
def fake_rubric_client(monkeypatch: pytest.MonkeyPatch) -> _FakeRubricClient:
    """Inject a hermetic :class:`_FakeRubricClient` into the pipeline."""
    client = _FakeRubricClient()

    def _build(_config: EvalConfig) -> _FakeRubricClient:
        return client

    monkeypatch.setattr(pipeline_mod, "_build_rubric_client", _build)
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_evaluate_writes_observation_artifacts_for_each_transition_node(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """Per-node ``*.png``/``*.axtree.json``/``*.axtree.txt`` artifacts are written."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    result = evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    assert result.run_dir == run_dir
    assert result.metrics_path == run_dir / "metrics.json"

    obs = run_dir / "observation"
    assert (obs / "index.json").is_file()
    for folder in _NODE_FOLDERS:
        for suffix in (".png", ".axtree.json", ".axtree.txt"):
            artifact = obs / f"{folder}{suffix}"
            assert artifact.is_file(), f"missing artifact: {artifact}"

    # ``product`` is ``not_found`` in the seeded pages.json so no product node is seeded.
    assert not (obs / "products__template.png").exists()


def test_evaluate_emits_schema_valid_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """``metrics.json`` validates against the closed v0.2 schema."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    result = evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    metrics = load_metrics(result.metrics_path)
    assert metrics.version == METRICS_SCHEMA_VERSION
    assert metrics.shop.url == _BASE_URL
    assert metrics.shop.domain == "example-shop.com"
    assert isinstance(metrics.pages.product, NotFound)
    assert metrics.pages.product.reason == "no_product_link"
    # Axtree stats aggregate over five captured transition nodes. Each stub
    # axtree has 3 nodes and 2 interactive elements.
    assert metrics.observation.node_count == len(_NODE_FOLDERS) * 3
    assert metrics.observation.interactive_count == len(_NODE_FOLDERS) * 2
    assert metrics.observation.distinct_node_count == 3
    assert metrics.observation.max_depth == 1
    assert metrics.observation.semantic_max_depth == 1
    # Pages translation preserves selection rules + canonical URLs.
    assert isinstance(metrics.pages.collection, MetricsPageOk)
    assert metrics.pages.collection.canonical_url == "/collections/<*>"
    assert isinstance(metrics.pages.cart_and_search.search, MetricsSearchPageOk)
    assert metrics.pages.cart_and_search.search.query == "linen"


def test_evaluate_navigates_each_measurable_bucket(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """The session sees one ``goto`` per measurable bucket, base-resolved."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    captured: list[_StubSession] = []

    @contextlib.contextmanager
    def _capturing_make_env(
        *_args: object,
        **_kwargs: object,
    ) -> Generator[_StubSession, None, None]:
        session = _StubSession()
        captured.append(session)
        yield session

    monkeypatch.setattr(pipeline_mod, "make_env", _capturing_make_env)

    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    (session,) = captured
    # The session sees transition graph navigation only. Observation/action read
    # ``transition/node`` artifacts, so they do not issue their own gotos:
    #   * 5 BFS-seed goto's (one per measurable bucket),
    #   * 10 stateful-rule goto's (6 homepage, 2 collection, 1 cart, 1 search),
    #   * 5 URL-node artifact goto's (one per URL node).
    # All stateful rules return ``no_target`` against the stub axtree (no
    # banner/main landmark) so the goto runs but no state-namer call follows.
    measurable_urls = [
        "https://example-shop.com/",
        "https://example-shop.com/collections/men",
        "https://example-shop.com/policies/privacy-policy",
        "https://example-shop.com/cart",
        "https://example-shop.com/search?q=linen",
    ]
    stateful_urls = (
        # 6 homepage rules: hover + click variants for the mega menu (v0.3)
        # plus the 4 original homepage rules (announcement, cart, search,
        # predictive search).
        ["https://example-shop.com/"] * 6
        + ["https://example-shop.com/collections/men"] * 2
        + ["https://example-shop.com/cart"]
        + ["https://example-shop.com/search?q=linen"]
    )
    assert session.goto_calls == measurable_urls + stateful_urls + measurable_urls


def test_evaluate_axtree_json_is_valid_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """``*.axtree.json`` is round-trip parseable JSON of the stub axtree."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    payload = json.loads((run_dir / "observation" / "home.axtree.json").read_text())
    assert payload == _sample_axtree()


def test_evaluate_reuses_existing_pages_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """Pre-existing ``pages.json`` is reused verbatim (spec §5.7)."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    seeded = _seed_pages_json(run_dir)
    pages_mtime_before = (run_dir / PAGES_JSON_FILENAME).stat().st_mtime_ns
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    pages_mtime_after = (run_dir / PAGES_JSON_FILENAME).stat().st_mtime_ns
    # Reuse means the file was not rewritten.
    assert pages_mtime_after == pages_mtime_before
    # And the seeded doc is still on disk byte-identical.
    payload = json.loads((run_dir / PAGES_JSON_FILENAME).read_text())
    assert payload["product"]["status"] == "not_found"
    assert payload == seeded.model_dump(mode="json")


def test_evaluate_writes_manifest_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """M1+M2 ``manifest.json`` lands alongside ``metrics.json`` with live counters."""
    from shop_arena.env_eval import _version as _ev_version
    from shop_arena.env_eval.schema.manifest import MANIFEST_JSON_FILENAME, Manifest

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    manifest_path = run_dir / MANIFEST_JSON_FILENAME
    assert manifest_path.is_file()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = Manifest.model_validate(payload)
    assert manifest.eval_version == _ev_version.__version__
    # 5 measurable buckets, one rubric call each (``product`` is ``not_found``).
    # The M5 stateful pass issues no LLM calls because every rule resolves to
    # ``no_target`` against the stub axtree (no banner/main landmark).
    assert manifest.llm_calls == 5
    assert manifest.config.url == _BASE_URL
    assert manifest.config.out_dir == str(run_dir)
    # Five measurable buckets (homepage, collection, policy, cart, search;
    # ``product`` is ``not_found`` so no goto) are navigated once for the BFS
    # seed pass and once for URL-node artifact capture. The M5 stateful pass
    # adds 10 more goto's (6 homepage + 2 collection + 1 cart + 1 search rules);
    # plus the homepage navigation done in ``EnvEvalBrowserTask.setup`` →
    # ``5 + 5 + 10 + 1 = 21``.
    assert manifest.browser_navigations == 21


def test_evaluate_no_rubric_writes_stub_rubric_per_measurable_bucket(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``--no-rubric`` emits ``{counts: {}, stub: true}`` per measurable bucket."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir, no_rubric=True))

    obs = run_dir / "observation"
    for folder in _NODE_FOLDERS:
        rubric_path = obs / f"{folder}.rubric.json"
        assert rubric_path.is_file(), f"missing rubric stub: {rubric_path}"
        payload = json.loads(rubric_path.read_text(encoding="utf-8"))
        assert payload == {"counts": {}, "stub": True}

    assert not (obs / "products__template.rubric.json").exists()


def test_evaluate_default_writes_real_rubric_per_measurable_bucket(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """Without ``--no-rubric``, M2 issues one rubric call per measurable bucket."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    obs = run_dir / "observation"
    for folder in _NODE_FOLDERS:
        rubric_path = obs / f"{folder}.rubric.json"
        assert rubric_path.is_file(), f"missing rubric artifact: {rubric_path}"
        artifact = RubricArtifact.model_validate_json(rubric_path.read_text(encoding="utf-8"))
        assert artifact.prompt_version == RUBRIC_PROMPT_VERSION
        assert artifact.model == fake_rubric_client.model
        assert artifact.parse_errors == ()
    assert not (obs / "products__template.rubric.json").exists()
    # One LLM call per captured transition node; the closed schema and PNG bytes
    # are forwarded verbatim.
    assert len(fake_rubric_client.calls) == len(_NODE_FOLDERS)
    for call in fake_rubric_client.calls:
        assert call["schema"] == RUBRIC_RESPONSE_SCHEMA
        assert all(img.startswith(b"\x89PNG") for img in call["images"])
        assert call["temperature"] == 0.0
        # M2/v0.2 wire shape: the axtree text from the stub session reaches
        # the rubric prompt under the canonical ``--- AXTREE ---`` header.
        assert "--- AXTREE ---" in call["prompt"]
        assert "link 'Shop'" in call["prompt"]


def test_evaluate_skips_rubric_call_when_non_stub_artifact_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """A pre-existing real rubric artifact short-circuits the LLM call (spec §5.7)."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    obs_dir = run_dir / "observation"
    obs_dir.mkdir()
    seeded_artifact = RubricArtifact(
        prompt_version=RUBRIC_PROMPT_VERSION,
        model="claude-sonnet-4-6",
        temperature=0.0,
        counts=Rubric(nav=7, footer=3),
        raw_response='{"nav": 7, "footer": 3}',
        parse_errors=(),
    )
    write_rubric_artifact(seeded_artifact, obs_dir / "homepage.rubric.json")
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    result = evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    # Legacy per-bucket artifacts are ignored because observation now derives
    # from transition-node artifacts and transition reruns reset the node layer.
    assert len(fake_rubric_client.calls) == len(_NODE_FOLDERS)
    metrics = load_metrics(result.metrics_path)
    assert metrics.observation.rubric.nav == 0


def test_evaluate_replaces_stub_rubric_with_real_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """A leftover ``--no-rubric`` stub is treated as missing; the rubric runs."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    obs_dir = run_dir / "observation"
    obs_dir.mkdir()
    stub_path = obs_dir / "homepage.rubric.json"
    stub_path.write_text(json.dumps({"counts": {}, "stub": True}, indent=2, sort_keys=True) + "\n")
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    # All five measurable buckets ran (the stub did not satisfy reuse).
    assert len(fake_rubric_client.calls) == 5
    artifact = RubricArtifact.model_validate_json(
        (run_dir / "observation" / "home.rubric.json").read_text(encoding="utf-8"),
    )
    assert artifact.prompt_version == RUBRIC_PROMPT_VERSION


def test_evaluate_default_metrics_observation_uses_parsed_rubric_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Parsed rubric counts aggregate into ``metrics.observation.rubric``."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    parsed = dict.fromkeys(RUBRIC_CATEGORIES, 0) | {"nav": 4, "hero": 2}
    response = VisionResponse(parsed=parsed, raw_response=json.dumps(parsed, sort_keys=True))
    fake = _FakeRubricClient(response_factory=lambda: response)

    def _build(_config: EvalConfig) -> _FakeRubricClient:
        return fake

    monkeypatch.setattr(pipeline_mod, "_build_rubric_client", _build)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    result = evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    metrics = load_metrics(result.metrics_path)
    assert metrics.observation.rubric.nav == 4 * len(_NODE_FOLDERS)
    assert metrics.observation.rubric.hero == 2 * len(_NODE_FOLDERS)


# ---------------------------------------------------------------------------
# Action layer (M3) wiring
# ---------------------------------------------------------------------------


def test_evaluate_writes_action_space_per_transition_node(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """Each transition node gets an ``action/<folder>.action_space.json`` artifact."""
    del fake_rubric_client
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    action_dir = run_dir / "action"
    assert (action_dir / "index.json").is_file()
    for folder in _NODE_FOLDERS:
        artifact_path = action_dir / f"{folder}.action_space.json"
        assert artifact_path.is_file(), f"missing action artifact: {artifact_path}"
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert set(payload) == {
            "vocabulary",
            "by_action",
            "by_category",
            "elements",
            "subsets",
            "heuristic_version",
        }
        # Stub axtree has 1 link + 1 button → click/dblclick/hover = 2 each.
        assert payload["by_action"] == {"click": 2, "dblclick": 2, "hover": 2}
    assert not (action_dir / "products__template.action_space.json").exists()


def test_evaluate_action_metrics_project_by_action_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """``metrics.action`` aggregates raw action counts over graph nodes."""
    del fake_rubric_client
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    result = evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    metrics = load_metrics(result.metrics_path)
    assert metrics.action.click == len(_NODE_FOLDERS) * 2
    assert metrics.action.hover == len(_NODE_FOLDERS) * 2
    # Non-projected keys (dblclick) drop; unset projected keys default to 0.
    assert metrics.action.fill == 0
    assert metrics.action.select_option == 0
    assert metrics.action.scroll == 0
    assert metrics.action.choice_target_count == 0
    assert metrics.action.semantic.search == 0
    assert metrics.action.semantic.filter == 0


def test_semantic_action_counts_are_derived_from_transition_edges_only() -> None:
    """Semantic action buckets classify transition-edge targets, not elements."""
    graph = TransitionGraph(
        nodes={
            "/": GraphNode("/", "https://shop.example/"),
            "/search": GraphNode("/search", "https://shop.example/search"),
            "/collections/<*>": GraphNode(
                "/collections/<*>",
                "https://shop.example/collections/all",
            ),
            "/products/<*>": GraphNode(
                "/products/<*>",
                "https://shop.example/products/red-shirt",
            ),
            "/policies/<*>": GraphNode(
                "/policies/<*>",
                "https://shop.example/policies/privacy-policy",
            ),
            "/cart": GraphNode("/cart", "https://shop.example/cart"),
            "/pages/about": GraphNode("/pages/about", "https://shop.example/pages/about"),
            "state:/:predictive_panel": GraphNode(
                "state:/:predictive_panel",
                "https://shop.example/",
                kind="state",
                state_name="predictive_panel",
            ),
            "state:/collections/<*>:filter_panel_open": GraphNode(
                "state:/collections/<*>:filter_panel_open",
                "https://shop.example/collections/all",
                kind="state",
                state_name="filter_panel_open",
            ),
            "state:/products/<*>:cart_drawer": GraphNode(
                "state:/products/<*>:cart_drawer",
                "https://shop.example/products/red-shirt",
                kind="state",
                state_name="cart_drawer",
            ),
            "state:/:mega_menu": GraphNode(
                "state:/:mega_menu",
                "https://shop.example/",
                kind="state",
                state_name="mega_menu",
            ),
        },
        edges=[
            GraphEdge("/", "/search", "click(/search)"),
            GraphEdge("/", "/collections/<*>", "click(collection)"),
            GraphEdge("/", "/products/<*>", "click(product)"),
            GraphEdge("/", "/policies/<*>", "click(policy)"),
            GraphEdge("/", "/cart", "click(cart)"),
            GraphEdge("/", "/pages/about", "click(about)"),
            GraphEdge("/", "state:/:predictive_panel", "fill(search)"),
            GraphEdge(
                "/collections/<*>",
                "state:/collections/<*>:filter_panel_open",
                "click(filter)",
            ),
            GraphEdge(
                "/products/<*>",
                "state:/products/<*>:cart_drawer",
                "click(add_to_cart)",
            ),
            GraphEdge("/", "state:/:mega_menu", "hover(menu)"),
        ],
        seeds=["/"],
    )

    helper_name = "_semantic_action_counts"
    semantic_action_counts = cast(
        Callable[[TransitionGraph], ActionSemanticCounts],
        getattr(pipeline_mod, helper_name),
    )
    counts = semantic_action_counts(graph)

    assert counts.search == 2
    assert counts.filter == 1
    assert counts.goto_collection == 1
    assert counts.goto_product == 1
    assert counts.goto_policy == 1
    assert counts.goto_cart == 1
    assert counts.open_cart == 1
    assert counts.explore == 2


def test_evaluate_ignores_legacy_action_space_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """Legacy per-bucket action artifacts are replaced by node-level artifacts."""
    del fake_rubric_client
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    action_dir = run_dir / "action"
    action_dir.mkdir()
    seeded = {
        "vocabulary": ["click", "fill"],
        "by_action": {"click": 99, "fill": 7, "scroll": 1},
        "elements": [],
        "subsets": ["chat", "infeas", "bid", "nav", "tab"],
        "heuristic_version": "0.1",
    }
    (action_dir / "homepage.action_space.json").write_text(
        json.dumps(seeded, indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    result = evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    assert not (action_dir / "homepage.action_space.json").exists()
    payload = json.loads((action_dir / "home.action_space.json").read_text(encoding="utf-8"))
    assert payload != seeded
    metrics = load_metrics(result.metrics_path)
    assert metrics.action.click == len(_NODE_FOLDERS) * 2
    assert metrics.action.fill == 0


# ---------------------------------------------------------------------------
# Transition layer (M4) wiring
# ---------------------------------------------------------------------------


def test_evaluate_writes_transition_graph_and_trace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """M4 wires the BFS pass: ``transition/graph.json`` + ``trace.jsonl``."""
    del fake_rubric_client
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    result = evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    transition_dir = run_dir / "transition"
    graph_path = transition_dir / "graph.json"
    trace_path = transition_dir / "trace.jsonl"
    assert graph_path.is_file()
    assert trace_path.is_file()
    node_dir = transition_dir / "node"
    node_index_path = node_dir / "index.json"
    assert node_index_path.is_file()

    graph_payload = json.loads(graph_path.read_text(encoding="utf-8"))
    # One node per ``ok`` measurable bucket (homepage, collection, policy,
    # cart, search). The stub ``page.evaluate`` returns no hrefs so the BFS
    # produces no edges and every node ends up at depth 0.
    canonical_ids = [n["canonical_id"] for n in graph_payload["nodes"]]
    assert canonical_ids == ["/", "/collections/<*>", "/policies/<*>", "/cart", "/search"]
    assert all(node["kind"] == "url" for node in graph_payload["nodes"])
    assert graph_payload["edges"] == []

    node_index = json.loads(node_index_path.read_text(encoding="utf-8"))
    assert [entry["canonical_id"] for entry in node_index["nodes"]] == canonical_ids
    home_dir = node_dir / "home"
    assert (home_dir / "node.json").is_file()
    assert (home_dir / "screenshot.png").is_file()
    assert (home_dir / "axtree.json").is_file()
    assert (home_dir / "axtree.txt").is_file()
    home_node = json.loads((home_dir / "node.json").read_text(encoding="utf-8"))
    assert home_node["canonical_id"] == "/"
    assert home_node["kind"] == "url"
    assert home_node["capture_status"] == "ok"

    # ``trace.jsonl`` records one ``ok`` attempt per BFS seed plus one
    # stateful attempt per applicable rule (10 = 6 homepage + 2 collection +
    # 1 cart + 1 search; product is ``not_found``).  Every stateful attempt
    # resolves to ``no_target`` against the stub axtree (no banner/main).
    trace_lines = [json.loads(line) for line in trace_path.read_text("utf-8").splitlines()]
    bfs_lines = [line for line in trace_lines if line["phase"] == "bfs"]
    stateful_lines = [line for line in trace_lines if line["phase"] == "stateful"]
    assert len(bfs_lines) == len(canonical_ids)
    assert all(line["outcome"] == "ok" for line in bfs_lines)
    assert len(stateful_lines) == 10
    assert all(line["outcome"] == "no_target" for line in stateful_lines)
    assert all(line["state"] is None for line in stateful_lines)

    # Metrics surface the BFS-derived graph (no edges, all dead ends).  No
    # rule fired so no state nodes were appended.
    metrics = load_metrics(result.metrics_path)
    assert metrics.transition.node_count == len(canonical_ids)
    assert metrics.transition.edge_count == 0
    assert metrics.transition.dead_end_count == len(canonical_ids)
    assert metrics.transition.state_node_count == 0
    assert metrics.transition.reachable_pct_from_homepage == 1 / len(canonical_ids)


def test_evaluate_reuses_existing_transition_graph_and_trace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """Pre-existing ``graph.json`` + ``trace.jsonl`` short-circuit the BFS (spec §5.7)."""
    del fake_rubric_client
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    transition_dir = run_dir / "transition"
    transition_dir.mkdir()
    seeded_graph = {
        "nodes": [
            {
                "canonical_id": "/",
                "representative_url": "https://shop/",
                "kind": "url",
                "state_name": None,
            },
            {
                "canonical_id": "/cart",
                "representative_url": "https://shop/cart",
                "kind": "url",
                "state_name": None,
            },
        ],
        "edges": [
            {
                "source": "/",
                "target": "/cart",
                "label": "click(https://shop/cart)",
                "action": "click",
            },
        ],
        "seeds": ["/"],
    }
    graph_path = transition_dir / "graph.json"
    trace_path = transition_dir / "trace.jsonl"
    graph_path.write_text(json.dumps(seeded_graph, indent=2) + "\n", encoding="utf-8")
    trace_path.write_text(
        json.dumps(
            {
                "phase": "bfs",
                "canonical_id": "/",
                "url": "https://shop/",
                "depth": 0,
                "status": 200,
                "outcome": "ok",
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    node_dir = transition_dir / "node"
    node_dir.mkdir()
    (node_dir / "index.json").write_text(
        json.dumps(
            {
                "artifact_version": "0.1",
                "nodes": [
                    {
                        "canonical_id": "/",
                        "folder": "home",
                        "kind": "url",
                        "node_json": "home/node.json",
                    },
                    {
                        "canonical_id": "/cart",
                        "folder": "cart",
                        "kind": "url",
                        "node_json": "cart/node.json",
                    },
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    graph_mtime_before = graph_path.stat().st_mtime_ns
    trace_mtime_before = trace_path.stat().st_mtime_ns
    sessions: list[_StubSession] = []

    @contextlib.contextmanager
    def _capturing_make_env(
        *_args: object,
        **_kwargs: object,
    ) -> Generator[_StubSession, None, None]:
        session = _StubSession()
        sessions.append(session)
        yield session

    monkeypatch.setattr(pipeline_mod, "make_env", _capturing_make_env)

    result = evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    # Reuse: artifacts are not rewritten.
    assert graph_path.stat().st_mtime_ns == graph_mtime_before
    assert trace_path.stat().st_mtime_ns == trace_mtime_before
    # Observation/action now read transition-node artifacts, so no page gotos
    # are needed when the transition graph is reused.
    (session,) = sessions
    assert session.goto_calls == []
    # Metrics are recomputed from the persisted graph.
    metrics = load_metrics(result.metrics_path)
    assert metrics.transition.node_count == 2
    assert metrics.transition.edge_count == 1
    assert metrics.transition.dead_end_count == 1
    assert metrics.transition.reachable_pct_from_homepage == 1.0
    assert metrics.action.semantic.goto_cart == 1


# ---------------------------------------------------------------------------
# Stateful pass (M5) wiring
# ---------------------------------------------------------------------------


def _write_fake_state_node_artifacts(
    *,
    states_dir: Path,
    node_root: Path | None,
    node_id: str,
    homepage_url: str,
) -> Path:
    """Write minimal state artifacts for the fired-rule pipeline test."""
    states_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = states_dir / "homepage_open_cart_drawer.json"
    artifact_path.write_text(
        json.dumps(
            {
                "action": "click",
                "expected_state": "cart_drawer",
                "model": "fake",
                "parse_errors": [],
                "post_axtree": "homepage_open_cart_drawer.post.axtree.json",
                "post_axtree_text": "homepage_open_cart_drawer.post.axtree.txt",
                "post_screenshot": "homepage_open_cart_drawer.post.png",
                "pre_axtree": "homepage_open_cart_drawer.pre.axtree.json",
                "pre_axtree_text": "homepage_open_cart_drawer.pre.axtree.txt",
                "pre_screenshot": "homepage_open_cart_drawer.pre.png",
                "prompt_version": "0.3",
                "raw_response": '{"state":"cart_drawer"}',
                "rule_id": "homepage_open_cart_drawer",
                "state": "cart_drawer",
                "temperature": 0.0,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    pre_png = states_dir / "homepage_open_cart_drawer.pre.png"
    post_png = states_dir / "homepage_open_cart_drawer.post.png"
    pre_axtree_json = states_dir / "homepage_open_cart_drawer.pre.axtree.json"
    pre_axtree_text = states_dir / "homepage_open_cart_drawer.pre.axtree.txt"
    post_axtree_json = states_dir / "homepage_open_cart_drawer.post.axtree.json"
    post_axtree_text = states_dir / "homepage_open_cart_drawer.post.axtree.txt"
    pre_png.write_bytes(b"pre")
    post_png.write_bytes(b"post")
    pre_axtree_json.write_text("{}\n", encoding="utf-8")
    pre_axtree_text.write_text("pre\n", encoding="utf-8")
    post_axtree_json.write_text("{}\n", encoding="utf-8")
    post_axtree_text.write_text("post\n", encoding="utf-8")

    if node_root is None:
        return artifact_path
    return node_artifacts_mod.write_state_node_artifact(
        node_root=node_root,
        canonical_id=node_id,
        representative_url=homepage_url,
        state_name="cart_drawer",
        state_artifact_path=artifact_path,
        pre_screenshot_path=pre_png,
        post_screenshot_path=post_png,
        pre_axtree_json_path=pre_axtree_json,
        pre_axtree_text_path=pre_axtree_text,
        post_axtree_json_path=post_axtree_json,
        post_axtree_text_path=post_axtree_text,
    )


def test_evaluate_writes_state_nodes_and_stateful_trace_for_fired_rules(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """Fired rules append state nodes/edges to ``graph.json`` + trace lines.

    Monkey-patches the stateful executor with a deterministic stub so the
    test stays hermetic (no real Playwright click).  Verifies the pipeline:

    * extends ``transition/graph.json`` with a state node + edge,
    * appends a ``phase="stateful"`` line to ``transition/trace.jsonl``,
    * folds the state-namer LLM call into ``manifest.llm_calls``,
    * recomputes ``metrics.transition`` so ``state_node_count`` is non-zero
      and ``homepage_to_cart_min_clicks`` reflects the new edge.
    """
    del fake_rubric_client
    from shop_arena.env_eval.transition.stateful import (
        STATEFUL_PHASE,
        StatefulAttempt,
        state_node_id,
    )
    # ``node_artifacts_mod`` is imported at module scope for the fake helper.

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)

    def _fake_run_stateful_pass(
        *,
        rules: Any,
        page_targets: dict[str, str],
        derived_query: str | None,
        graph: Any,
        states_dir: Path,
        llm_client: Any,
        goto: Any,
        axtree: Any,
        screenshot_png: Any,
        page: Any,
        canonical_id_for_url: Any,
        run_dir: Path,
        networkidle_timeout_ms: int = 0,
        temperature: float = 0.0,
        rule_filter: Any = None,
        node_root: Path | None = None,
    ) -> tuple[list[StatefulAttempt], int]:
        del rules, derived_query, llm_client, goto, axtree, screenshot_png, page
        del networkidle_timeout_ms, temperature, rule_filter
        # Pretend the homepage cart-drawer rule fired.  Add the state node /
        # edge and one trace attempt; pretend a state-namer LLM call ran.
        homepage_url = page_targets["homepage"]
        node_id = state_node_id(canonical_id_for_url(homepage_url), "cart_drawer")
        artifact_path = _write_fake_state_node_artifacts(
            states_dir=states_dir,
            node_root=node_root,
            node_id=node_id,
            homepage_url=homepage_url,
        )
        graph.add_state_node(
            canonical_id=node_id,
            representative_url=homepage_url,
            state_name="cart_drawer",
        )
        graph.add_edge(
            source=canonical_id_for_url(homepage_url),
            target=node_id,
            label="click(homepage_open_cart_drawer)",
            action="click",
        )
        return (
            [
                StatefulAttempt(
                    rule_id="homepage_open_cart_drawer",
                    page_class="homepage",
                    page_url=homepage_url,
                    outcome="fired",
                    bid="a1",
                    state="cart_drawer",
                    state_node=node_id,
                    artifact=artifact_path.relative_to(run_dir).as_posix(),
                ),
            ],
            1,
        )

    monkeypatch.setattr(pipeline_mod, "run_stateful_pass", _fake_run_stateful_pass)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    result = evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    transition_dir = run_dir / "transition"
    graph_payload = json.loads((transition_dir / "graph.json").read_text(encoding="utf-8"))
    state_nodes = [n for n in graph_payload["nodes"] if n["kind"] == "state"]
    assert len(state_nodes) == 1
    assert state_nodes[0]["state_name"] == "cart_drawer"
    assert state_nodes[0]["canonical_id"] == "state:/:cart_drawer"
    state_edges = [e for e in graph_payload["edges"] if e["target"] == "state:/:cart_drawer"]
    assert len(state_edges) == 1
    assert state_edges[0]["source"] == "/"
    assert state_edges[0]["label"] == "click(homepage_open_cart_drawer)"

    trace_lines = [
        json.loads(line)
        for line in (transition_dir / "trace.jsonl").read_text("utf-8").splitlines()
    ]
    stateful_lines = [line for line in trace_lines if line["phase"] == STATEFUL_PHASE]
    assert len(stateful_lines) == 1
    fired = stateful_lines[0]
    assert fired["outcome"] == "fired"
    assert fired["state"] == "cart_drawer"
    assert fired["state_node"] == "state:/:cart_drawer"
    assert fired["artifact"] == "transition/node/state__home__cart_drawer/node.json"
    state_node_dir = transition_dir / "node" / "state__home__cart_drawer"
    assert (state_node_dir / "node.json").is_file()
    assert (state_node_dir / "pre.png").is_file()
    assert (state_node_dir / "post.png").is_file()

    metrics = load_metrics(result.metrics_path)
    assert metrics.transition.state_node_count == 1
    # Hop from homepage "/" → cart_drawer state node = 1 click.  ``/cart`` is
    # a measurable bucket too (depth 0 from its own seed) but the BFS produces
    # no edges in this stub setup, so the cart_drawer state edge is the only
    # path the homepage can take.
    assert metrics.transition.homepage_to_cart_min_clicks == 1
    assert metrics.action.semantic.open_cart == 1

    from shop_arena.env_eval import _version as _ev_version
    from shop_arena.env_eval.schema.manifest import MANIFEST_JSON_FILENAME, Manifest

    manifest = Manifest.model_validate(
        json.loads((run_dir / MANIFEST_JSON_FILENAME).read_text(encoding="utf-8")),
    )
    assert manifest.eval_version == _ev_version.__version__
    # 6 observation rubric calls (5 URL nodes + 1 state node) + 1 state-namer call.
    assert manifest.llm_calls == 7


def test_evaluate_skips_stateful_pass_under_no_rubric(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``--no-rubric`` short-circuits the stateful pass entirely."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    def _fail_stateful(**_kwargs: object) -> tuple[list[Any], int]:
        msg = "run_stateful_pass must not run under --no-rubric"
        raise AssertionError(msg)

    monkeypatch.setattr(pipeline_mod, "run_stateful_pass", _fail_stateful)

    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir, no_rubric=True))

    trace_lines = [
        json.loads(line)
        for line in (run_dir / "transition" / "trace.jsonl").read_text("utf-8").splitlines()
    ]
    assert all(line["phase"] == "bfs" for line in trace_lines)
    assert not (run_dir / "transition" / "states").exists()
    assert (run_dir / "transition" / "node" / "index.json").is_file()


# ---------------------------------------------------------------------------
# Resume wiring (M6): can_skip per step + manifest StepRecord accounting
# ---------------------------------------------------------------------------


def test_evaluate_records_step_status_first_run_all_ran(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """First-run manifest records ``ran=True`` for every step (impl-plan M6)."""
    del fake_rubric_client
    from shop_arena.env_eval.resume import STEPS
    from shop_arena.env_eval.schema.manifest import MANIFEST_JSON_FILENAME, Manifest, StepRecord

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    payload = json.loads((run_dir / MANIFEST_JSON_FILENAME).read_text(encoding="utf-8"))
    manifest = Manifest.model_validate(payload)
    names = tuple(record.name for record in manifest.steps)
    assert names == STEPS
    # ``pages`` was reused (we seeded ``pages.json``); every other step ran live.
    pages_record = next(r for r in manifest.steps if r.name == "pages")
    assert pages_record == StepRecord(name="pages", ran=False, reused=True)
    for step in ("observation", "action", "transition", "metrics"):
        record = next(r for r in manifest.steps if r.name == step)
        assert record == StepRecord(name=step, ran=True, reused=False)


def test_evaluate_full_reuse_skips_browser_and_llm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A second ``evaluate()`` call with all artifacts on disk skips work entirely.

    Spec §5.7 / impl-plan M6: when every step's required artifacts are present,
    EnvEval does not open a BrowserGym env and does not issue any LLM call.
    The manifest reflects ``browser_navigations=0``, ``llm_calls=0``, and every
    step recorded as ``reused=True`` (SC4 precondition).
    """
    from shop_arena.env_eval.schema.manifest import MANIFEST_JSON_FILENAME, Manifest

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)

    fake = _FakeRubricClient()

    def _build(_config: EvalConfig) -> _FakeRubricClient:
        return fake

    monkeypatch.setattr(pipeline_mod, "_build_rubric_client", _build)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    # First run primes every artifact on disk.
    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))
    metrics_mtime_before = (run_dir / "metrics.json").stat().st_mtime_ns
    fake.calls.clear()

    # Second run must not open a browser or invoke the LLM.
    def _exploding_make_env(*_a: object, **_kw: object) -> Any:
        msg = "make_env must not be called during full-reuse evaluate()"
        raise AssertionError(msg)

    monkeypatch.setattr(pipeline_mod, "make_env", _exploding_make_env)

    result = evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    assert result.run_dir == run_dir
    assert result.metrics_path == run_dir / "metrics.json"
    # ``metrics.json`` is not rewritten on full reuse — file is byte-stable.
    assert (run_dir / "metrics.json").stat().st_mtime_ns == metrics_mtime_before
    # The fake rubric client recorded zero calls between the two invocations.
    assert fake.calls == []

    payload = json.loads((run_dir / MANIFEST_JSON_FILENAME).read_text(encoding="utf-8"))
    manifest = Manifest.model_validate(payload)
    assert manifest.browser_navigations == 0
    assert manifest.llm_calls == 0
    assert all(record.reused is True for record in manifest.steps)
    assert all(record.ran is False for record in manifest.steps)


def test_evaluate_rediscover_blocks_full_reuse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """``--rediscover`` always forces the pages step to re-run (no full-skip)."""
    del fake_rubric_client
    from shop_arena.env_eval.schema.manifest import MANIFEST_JSON_FILENAME, Manifest

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)
    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    # Rerun with ``--rediscover``; the pages step must run live again.
    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir, rediscover=True))

    payload = json.loads((run_dir / MANIFEST_JSON_FILENAME).read_text(encoding="utf-8"))
    manifest = Manifest.model_validate(payload)
    pages_record = next(r for r in manifest.steps if r.name == "pages")
    assert pages_record.ran is True
    assert pages_record.reused is False
    # browser_navigations is non-zero — we opened a session for discovery.
    assert manifest.browser_navigations >= 1


def test_evaluate_rediscover_warns_when_downstream_artifacts_exist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``--rediscover`` warns when downstream artifacts may be stale (impl-plan M6)."""
    del fake_rubric_client
    import logging

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)
    # First run primes downstream artifacts.
    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))
    assert (run_dir / "observation" / "home.png").is_file()

    # Rerun with ``--rediscover``; the warning must mention staleness.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=pipeline_mod.__name__):
        evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir, rediscover=True))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("--rediscover" in r.getMessage() and "stale" in r.getMessage() for r in warnings), (
        f"expected stale-artifact warning; got {[r.getMessage() for r in warnings]!r}"
    )
    # Downstream artifacts are NOT deleted by ``--rediscover``.
    assert (run_dir / "observation" / "home.png").is_file()


def test_evaluate_rediscover_does_not_warn_on_first_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``--rediscover`` is silent when the run dir has no downstream artifacts."""
    del fake_rubric_client
    import logging

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    monkeypatch.setattr(pipeline_mod, "make_env", _stub_make_env)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=pipeline_mod.__name__):
        evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir, rediscover=True))
    stale_warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and "stale" in r.getMessage()
    ]
    assert stale_warnings == []


def test_evaluate_ignores_legacy_observation_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """Legacy per-bucket observation artifacts are replaced by node artifacts."""
    del fake_rubric_client
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)
    obs_dir = run_dir / "observation"
    obs_dir.mkdir()
    seeded_axtree = _sample_axtree()
    (obs_dir / "homepage.png").write_bytes(b"\x89PNG\r\n\x1a\nstub")
    (obs_dir / "homepage.axtree.json").write_text(
        json.dumps(seeded_axtree, indent=2) + "\n",
        encoding="utf-8",
    )
    (obs_dir / "homepage.axtree.txt").write_text("home\n", encoding="utf-8")
    seeded_artifact = RubricArtifact(
        prompt_version=RUBRIC_PROMPT_VERSION,
        model="claude-sonnet-4-6",
        temperature=0.0,
        counts=Rubric(nav=11),
        raw_response='{"nav": 11}',
        parse_errors=(),
    )
    write_rubric_artifact(seeded_artifact, obs_dir / "homepage.rubric.json")

    captured: list[_StubSession] = []

    @contextlib.contextmanager
    def _capturing_make_env(
        *_args: object,
        **_kwargs: object,
    ) -> Generator[_StubSession, None, None]:
        session = _StubSession()
        captured.append(session)
        yield session

    monkeypatch.setattr(pipeline_mod, "make_env", _capturing_make_env)

    result = evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir, no_rubric=True))

    (session,) = captured
    # Observation/action read transition-node artifacts; the legacy per-bucket
    # files are removed when transition reruns and the node layer is reset.
    assert session.goto_calls.count("https://example-shop.com/") == 2
    assert not (obs_dir / "homepage.png").exists()
    assert (obs_dir / "home.png").is_file()
    metrics = load_metrics(result.metrics_path)
    assert metrics.observation.rubric.nav == 0


# ---------------------------------------------------------------------------
# /pages classifier pipeline wiring.
# ---------------------------------------------------------------------------


class _PagesEmittingPage:
    """Stub :class:`playwright.sync_api.Page` whose ``evaluate`` returns hrefs.

    BFS scrapes the active page exactly once per ``goto``; the homepage
    response carries two distinct ``/pages/<slug>`` hrefs so the pipeline
    triggers the classifier callback. Every other URL returns an empty list.
    """

    url: str = "about:blank"

    _HOMEPAGE_HREFS: tuple[str, ...] = (
        "https://example-shop.com/pages/warranty",
        "https://example-shop.com/pages/spring-sale",
    )

    def evaluate(self, _expression: str, *_args: object) -> list[str]:
        if self.url == "https://example-shop.com/":
            return list(self._HOMEPAGE_HREFS)
        return []


class _PagesEmittingSession(_StubSession):
    """:class:`_StubSession` whose page emits ``/pages/<slug>`` hrefs."""

    def __init__(self) -> None:
        super().__init__()
        self.page = cast("_StubPage", _PagesEmittingPage())


@dataclass
class _FakeClassifierClient:
    """Fake :class:`LLMVisionClient` that records ``call_text`` invocations."""

    model: str = "gpt-5"
    text_calls: list[dict[str, Any]] = field(
        default_factory=lambda: cast("list[dict[str, Any]]", []),
    )

    def call(
        self,
        *,
        prompt: str,
        images: Sequence[bytes],
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:  # pragma: no cover — unused
        del prompt, images, schema, temperature
        msg = "_FakeClassifierClient does not implement vision call()"
        raise NotImplementedError(msg)

    def call_text(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        self.text_calls.append(
            {"prompt": prompt, "schema": schema, "temperature": temperature},
        )
        # Mark every emitted slug as ``marketing`` so it lands in the collapse set.
        parsed = {
            "entries": [
                {"path": "warranty", "label": "marketing", "reason": "stub"},
                {"path": "spring-sale", "label": "marketing", "reason": "stub"},
            ],
        }
        return VisionResponse(
            parsed=parsed,
            raw_response=json.dumps(parsed, sort_keys=True),
        )


@contextlib.contextmanager
def _pages_emitting_make_env(
    *_args: object,
    **_kwargs: object,
) -> Generator[_PagesEmittingSession, None, None]:
    yield _PagesEmittingSession()


def test_evaluate_invokes_pages_classifier_when_pages_hrefs_discovered(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """The classifier client is built and called when BFS surfaces ``/pages/`` hrefs."""
    del fake_rubric_client
    from shop_arena.env_eval.transition.pages_classifier import (
        PAGES_CLASSIFICATION_FILENAME,
        PagesClassification,
        read_pages_classification,
    )

    classifier = _FakeClassifierClient()

    def _build_classifier(_config: EvalConfig) -> _FakeClassifierClient:
        return classifier

    monkeypatch.setattr(pipeline_mod, "_build_pages_classifier_client", _build_classifier)
    monkeypatch.setattr(pipeline_mod, "make_env", _pages_emitting_make_env)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)

    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    artifact_path = run_dir / "transition" / PAGES_CLASSIFICATION_FILENAME
    assert artifact_path.is_file()
    assert len(classifier.text_calls) >= 1
    doc: PagesClassification = read_pages_classification(run_dir)
    assert {entry.path for entry in doc.entries} == {"warranty", "spring-sale"}
    assert all(entry.label == "marketing" for entry in doc.entries)


def test_evaluate_no_rubric_writes_stub_pages_classification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``--no-rubric`` stubs the classifier alongside the rubric and writes the doc."""
    from shop_arena.env_eval.transition.pages_classifier import (
        PAGES_CLASSIFICATION_FILENAME,
        read_pages_classification,
    )

    monkeypatch.setattr(pipeline_mod, "make_env", _pages_emitting_make_env)

    def _fail_build(_config: EvalConfig) -> object:  # pragma: no cover
        msg = "classifier client must not be built under --no-rubric"
        raise AssertionError(msg)

    monkeypatch.setattr(pipeline_mod, "_build_pages_classifier_client", _fail_build)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)

    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir, no_rubric=True))

    artifact_path = run_dir / "transition" / PAGES_CLASSIFICATION_FILENAME
    assert artifact_path.is_file()
    doc = read_pages_classification(run_dir)
    assert doc.model == "stub"
    # Every emitted slug is recorded with the conservative ``unknown`` label.
    assert {entry.path for entry in doc.entries} == {"warranty", "spring-sale"}
    assert all(entry.label == "unknown" for entry in doc.entries)


def test_evaluate_records_pages_classifier_model_in_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_rubric_client: _FakeRubricClient,
) -> None:
    """The CLI-supplied ``pages_classifier_model`` lands on ``manifest.config``."""
    del fake_rubric_client
    from shop_arena.env_eval.schema.manifest import MANIFEST_JSON_FILENAME, Manifest
    from shop_arena.env_eval.transition.pages_classifier import (
        PAGES_CLASSIFIER_VERSION,
    )

    classifier = _FakeClassifierClient(model="gpt-5-nano")

    def _build_classifier(_config: EvalConfig) -> _FakeClassifierClient:
        return classifier

    monkeypatch.setattr(pipeline_mod, "_build_pages_classifier_client", _build_classifier)
    monkeypatch.setattr(pipeline_mod, "make_env", _pages_emitting_make_env)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_pages_json(run_dir)

    evaluate(
        EvalConfig(
            url=_BASE_URL,
            out_dir=run_dir,
            pages_classifier_model="gpt-5-nano",
        ),
    )

    manifest = Manifest.model_validate_json(
        (run_dir / MANIFEST_JSON_FILENAME).read_text(encoding="utf-8"),
    )
    assert manifest.config.pages_classifier_model == "gpt-5-nano"
    assert manifest.pages_classifier_version == PAGES_CLASSIFIER_VERSION
