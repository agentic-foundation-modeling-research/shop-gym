"""Full pipeline replay (impl-plan M6 / spec §5.10).

Drives :func:`shop_arena.env_eval.pipeline.evaluate` end-to-end against a
recorded fixture run under ``fixtures/replay_run/`` with no live browser
and no live LLM.  The test asserts:

* every per-bucket / per-layer artifact is produced;
* ``metrics.json`` is schema-valid and matches the recorded golden
  values for observation, action, transition, and the manifest;
* a second :func:`evaluate` call on the same run directory short-
  circuits entirely — zero browser navigations, zero LLM calls, every
  step recorded as ``reused=True`` (SC4 precondition).

The fixture set is intentionally small (one realistic axtree per
measurable bucket plus per-bucket recorded rubric counts).  Stateful
rules find no banner / main landmarks in the recorded axtrees so every
rule resolves to ``no_target``; this keeps the M5 pass exercised
without introducing a state-namer LLM call.
"""

from __future__ import annotations

import contextlib
import json
import shutil
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from shop_arena.env_eval import pipeline as pipeline_mod
from shop_arena.env_eval.config import EvalConfig
from shop_arena.env_eval.pipeline import evaluate
from shop_arena.env_eval.schema.manifest import MANIFEST_JSON_FILENAME, Manifest
from shop_arena.env_eval.schema.metrics import (
    METRICS_SCHEMA_VERSION,
    NotFound,
    PageOk,
    SearchPageOk,
    load_metrics,
)
from shop_arena.util._llm import VisionResponse

# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------

_FIXTURE_DIR: Path = Path(__file__).parent / "fixtures" / "replay_run"
_BASE_URL: str = "https://replay-shop.example/"


def _load_fixture(name: str) -> Any:
    """Return the parsed JSON contents of ``fixtures/replay_run/<name>``."""
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Fake browser session: replays recorded axtree per URL.
# ---------------------------------------------------------------------------


class _ReplayPage:
    """Inert ``page`` stand-in — BFS link scans always return no hrefs."""

    url: str = "about:blank"

    def evaluate(self, _expression: str, *_args: object) -> list[Any]:
        return []


@dataclass
class _ReplaySession:
    """Fake :class:`EnvEvalSession` backed by recorded axtrees.

    ``axtrees`` maps an absolute URL to the recorded axtree returned on
    the next ``axtree()`` call after a matching ``goto``.  An unrecognised
    URL fails loudly so a regression in URL routing surfaces in the test
    output rather than as zeroed metrics.
    """

    axtrees: Mapping[str, Mapping[str, Any]]
    goto_calls: list[str] = field(default_factory=lambda: cast("list[str]", []))
    nav_count: int = 0
    page: _ReplayPage = field(default_factory=_ReplayPage)
    _current_url: str | None = None

    def goto(self, url: str) -> None:
        if url not in self.axtrees:
            raise AssertionError(f"replay fixture has no recording for url={url!r}")
        self.goto_calls.append(url)
        self.nav_count += 1
        self._current_url = url
        self.page.url = url

    def axtree(self) -> Mapping[str, Any]:
        if self._current_url is None:
            raise AssertionError("axtree() called before goto()")
        return self.axtrees[self._current_url]

    def screenshot(self) -> Any:
        # 1x1 black image — the rubric layer cares about bytes only;
        # the recorded responses are keyed off the call sequence.
        return np.zeros((1, 1, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Fake vision client: serves recorded rubric counts in pipeline order.
# ---------------------------------------------------------------------------


@dataclass
class _ReplayVisionClient:
    """Fake :class:`LLMVisionClient` that replays rubric responses by call order.

    The pipeline's observation step walks measurable buckets in a fixed
    order (homepage → collection → policy → cart → search; ``product`` is
    ``not_found`` in the fixture and skipped).  ``responses`` is the list
    of recorded rubric payloads for those buckets in that order; calls
    are popped left-to-right.
    """

    model: str = "claude-sonnet-4-6"
    responses: list[Mapping[str, Any]] = field(
        default_factory=lambda: cast("list[Mapping[str, Any]]", []),
    )
    calls: list[dict[str, Any]] = field(default_factory=lambda: cast("list[dict[str, Any]]", []))

    def call(
        self,
        *,
        prompt: str,
        images: Sequence[bytes],
        schema: Mapping[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        if not self.responses:
            raise AssertionError("replay vision client exhausted recorded responses")
        payload = self.responses.pop(0)
        self.calls.append(
            {
                "prompt": prompt,
                "image_bytes_total": sum(len(img) for img in images),
                "image_count": len(images),
                "schema_keys": tuple(sorted(schema)),
                "temperature": temperature,
            },
        )
        return VisionResponse(parsed=payload, raw_response=json.dumps(payload, sort_keys=True))


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


_BUCKET_ORDER: tuple[str, ...] = (
    "homepage",
    "collection",
    "policy",
    "cart_and_search.cart",
    "cart_and_search.search",
)
_NODE_FOLDERS: tuple[str, ...] = (
    "home",
    "collections__template",
    "policies__template",
    "cart",
    "search",
)


def _seed_run_dir(run_dir: Path) -> None:
    """Drop the recorded ``pages.json`` into ``run_dir`` so discovery is reused."""
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(_FIXTURE_DIR / "pages.json", run_dir / "pages.json")


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    session_holder: list[_ReplaySession],
    rubric_client: _ReplayVisionClient,
) -> None:
    """Wire the replay session + vision client into the pipeline module."""
    axtrees = cast("dict[str, Mapping[str, Any]]", _load_fixture("axtrees.json"))

    @contextlib.contextmanager
    def _fake_make_env(*_args: object, **_kwargs: object) -> Generator[_ReplaySession, None, None]:
        session = _ReplaySession(axtrees=axtrees)
        session_holder.append(session)
        yield session

    monkeypatch.setattr(pipeline_mod, "make_env", _fake_make_env)

    def _build(_config: EvalConfig) -> _ReplayVisionClient:
        return rubric_client

    monkeypatch.setattr(pipeline_mod, "_build_rubric_client", _build)


def _drive_replay_first_run(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> tuple[_ReplayVisionClient, list[_ReplaySession]]:
    """Drive the first ``evaluate()`` call against the fixture run dir.

    Wires the replay session + rubric client into the pipeline, runs
    :func:`evaluate`, and returns the rubric client + the captured
    sessions so callers can extend assertions.
    """
    rubric_fixture = cast("dict[str, dict[str, int]]", _load_fixture("rubric.json"))
    rubric_client = _ReplayVisionClient(
        responses=[rubric_fixture[bucket] for bucket in _BUCKET_ORDER],
    )
    sessions: list[_ReplaySession] = []
    _seed_run_dir(run_dir)
    _install_fakes(monkeypatch, sessions, rubric_client)
    evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))
    return rubric_client, sessions


# ---------------------------------------------------------------------------
# The replay tests
# ---------------------------------------------------------------------------


def test_evaluate_replay_writes_full_pipeline_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """End-to-end pipeline against recorded fixtures produces every artifact."""
    run_dir = tmp_path / "run"
    rubric_client, _ = _drive_replay_first_run(monkeypatch, run_dir)

    # -- Per-node artifacts: observation + action ------------------------------
    obs_dir = run_dir / "observation"
    action_dir = run_dir / "action"
    assert (obs_dir / "index.json").is_file()
    assert (action_dir / "index.json").is_file()
    for folder in _NODE_FOLDERS:
        for suffix in (".png", ".axtree.json", ".axtree.txt", ".rubric.json"):
            assert (obs_dir / f"{folder}{suffix}").is_file(), (
                f"missing observation artifact: {folder}{suffix}"
            )
        assert (action_dir / f"{folder}.action_space.json").is_file(), (
            f"missing action artifact: {folder}"
        )
    assert not (obs_dir / "products__template.png").exists()
    assert not (action_dir / "products__template.action_space.json").exists()

    # -- Transition layer artifacts --------------------------------------------
    transition_dir = run_dir / "transition"
    assert (transition_dir / "graph.json").is_file()
    assert (transition_dir / "trace.jsonl").is_file()
    assert (transition_dir / "node" / "index.json").is_file()
    assert (transition_dir / "node" / "home" / "node.json").is_file()
    assert (transition_dir / "node" / "home" / "screenshot.png").is_file()
    assert (transition_dir / "node" / "home" / "axtree.json").is_file()

    # -- Trace.jsonl carries one BFS line per seed plus stateful attempts -----
    trace_lines = [
        json.loads(line)
        for line in (transition_dir / "trace.jsonl").read_text("utf-8").splitlines()
    ]
    bfs_lines = [line for line in trace_lines if line["phase"] == "bfs"]
    stateful_lines = [line for line in trace_lines if line["phase"] == "stateful"]
    assert len(bfs_lines) == 5
    assert all(line["outcome"] == "ok" for line in bfs_lines)
    # Every stateful attempt against the fixture axtrees resolves to no_target.
    assert stateful_lines  # at least one rule attempted
    assert all(line["outcome"] == "no_target" for line in stateful_lines)

    # 5 measurable buckets, 1 rubric call each — no state-namer call.
    assert len(rubric_client.calls) == 5


def test_evaluate_replay_metrics_match_recorded_golden(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``metrics.json`` + manifest match recorded golden values across all layers."""
    run_dir = tmp_path / "run"
    _drive_replay_first_run(monkeypatch, run_dir)

    metrics = load_metrics(run_dir / "metrics.json")
    assert metrics.version == METRICS_SCHEMA_VERSION
    assert metrics.shop.url == _BASE_URL
    assert metrics.shop.domain == "replay-shop.example"

    # Pages: five buckets surfaced; product is closed-status NotFound.
    assert isinstance(metrics.pages.homepage, PageOk)
    assert isinstance(metrics.pages.collection, PageOk)
    assert isinstance(metrics.pages.product, NotFound)
    assert isinstance(metrics.pages.policy, PageOk)
    assert isinstance(metrics.pages.cart_and_search.cart, PageOk)
    assert isinstance(metrics.pages.cart_and_search.search, SearchPageOk)
    assert metrics.pages.cart_and_search.search.query == "coat"

    # Observation: website-level aggregates over captured graph nodes.
    assert metrics.observation.node_count == 19
    assert metrics.observation.interactive_count == 13
    assert metrics.observation.max_depth == 1
    assert metrics.observation.semantic_max_depth == 1
    assert metrics.observation.rubric.nav == 14
    assert metrics.observation.rubric.product_card == 20
    assert metrics.observation.rubric.filter_chip == 5

    # Action: raw counts aggregate over captured graph nodes; semantic counts
    # are derived only from transition edges, and this replay has none.
    assert metrics.action.click == 10
    assert metrics.action.fill == 2
    assert metrics.action.hover == 10
    assert metrics.action.select_option == 1
    assert metrics.action.scroll == 0
    assert metrics.action.choice_target_count == 2
    assert metrics.action.semantic.search == 0
    assert metrics.action.semantic.filter == 0

    # Transition: 5 URL seeds, no edges, no state nodes (no banner/main).
    assert metrics.transition.node_count == 5
    assert metrics.transition.edge_count == 0
    assert metrics.transition.state_node_count == 0
    assert metrics.transition.dead_end_count == 5
    assert metrics.transition.reachable_pct_from_homepage == 1 / 5
    assert metrics.transition.homepage_to_cart_min_clicks is None

    # Manifest: pages reused (we seeded it); other steps ran live.
    manifest = Manifest.model_validate(
        json.loads((run_dir / MANIFEST_JSON_FILENAME).read_text(encoding="utf-8")),
    )
    assert manifest.llm_calls == 5
    # Browser navigations: setup + BFS seeds + stateful gotos + URL-node capture.
    assert manifest.browser_navigations >= 11
    pages_record = next(r for r in manifest.steps if r.name == "pages")
    assert pages_record.ran is False
    assert pages_record.reused is True
    for step in ("observation", "action", "transition", "metrics"):
        record = next(r for r in manifest.steps if r.name == step)
        assert record.ran is True, f"step {step!r} should have ran live"
        assert record.reused is False


def test_evaluate_replay_second_call_is_full_reuse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Re-running ``evaluate()`` on the same run dir issues 0 nav + 0 LLM (SC4)."""
    run_dir = tmp_path / "run"
    rubric_client, sessions = _drive_replay_first_run(monkeypatch, run_dir)
    sessions.clear()
    rubric_client.calls.clear()
    rubric_client.responses.clear()  # any further call would be a regression.
    metrics_mtime_before = (run_dir / "metrics.json").stat().st_mtime_ns

    def _exploding_make_env(*_args: object, **_kwargs: object) -> Any:
        msg = "make_env must not be called during full-reuse evaluate()"
        raise AssertionError(msg)

    monkeypatch.setattr(pipeline_mod, "make_env", _exploding_make_env)

    second = evaluate(EvalConfig(url=_BASE_URL, out_dir=run_dir))

    assert second.run_dir == run_dir
    assert second.metrics_path == run_dir / "metrics.json"
    # ``metrics.json`` is byte-stable across the reuse boundary.
    assert (run_dir / "metrics.json").stat().st_mtime_ns == metrics_mtime_before
    # No browser session opened, no LLM call issued.
    assert sessions == []
    assert rubric_client.calls == []

    manifest = Manifest.model_validate(
        json.loads((run_dir / MANIFEST_JSON_FILENAME).read_text(encoding="utf-8")),
    )
    assert manifest.browser_navigations == 0
    assert manifest.llm_calls == 0
    assert all(r.reused is True for r in manifest.steps)
    assert all(r.ran is False for r in manifest.steps)
