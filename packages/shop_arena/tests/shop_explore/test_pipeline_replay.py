"""End-to-end replay test for :func:`shop_explore.pipeline.explore` (T2.6).

Drives the full pipeline against the hand-crafted ``fixture_drawer_shop``
cassette under :class:`harness.runtimes.replay.ReplayRuntime`. No real
LLM, no real network: storefront prefetch is stubbed via ``respx`` and
the runtime selector is monkey-patched to return a ``ReplayRuntime``
rooted at the cassette directory.

This is the milestone gate for SC4 ("replayable"): a recorded
`shop_explore` run drives end-to-end against `harness.runtimes.replay`.
SC1 is partially satisfied here too — the loop runs end-to-end and
populates ``plan.md`` + ``artifact/parts/`` + ``artifact/evidence/``;
the synthesis pass that completes SC1 lands in M3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import respx

from harness.config import FinalStatus
from harness.plan_parser import parse as parse_plan
from harness.runtimes.replay import ReplayRuntime
from harness.types import TaskStatus
from shop_explore import pipeline as pipeline_mod
from shop_explore.config import ExploreConfig

_BASE_URL = "https://example-shop.com"
_CASSETTE_DIR = Path(__file__).resolve().parent / "cassettes" / "fixture_drawer_shop"
_EXPECTED_TASKS: tuple[str, ...] = (
    "homepage_sections",
    "cart_drawer",
    "search_predictive",
    "collection_filters",
)
_PREFETCH_TIMEOUT_SECONDS = 30.0
_REPLAY_MAX_ITERS = 6


def _ok(content: str | bytes, *, content_type: str = "text/html; charset=utf-8") -> httpx.Response:
    body = content.encode("utf-8") if isinstance(content, str) else content
    return httpx.Response(200, content=body, headers={"content-type": content_type})


def _stub_storefront(mock: respx.MockRouter) -> None:
    """Stub every URL the §5.9 prefetch plan hits with a 200 response."""
    mock.get(f"{_BASE_URL}/robots.txt").mock(
        return_value=_ok("User-agent: *\nAllow: /\n", content_type="text/plain")
    )
    mock.get(f"{_BASE_URL}/").mock(return_value=_ok("<!doctype html><html></html>"))
    mock.get(f"{_BASE_URL}/sitemap.xml").mock(
        return_value=_ok(
            "<?xml version='1.0'?><urlset></urlset>",
            content_type="application/xml",
        )
    )
    mock.get(f"{_BASE_URL}/products.json", params={"limit": "50"}).mock(
        return_value=_ok('{"products": []}', content_type="application/json")
    )
    mock.get(f"{_BASE_URL}/collections.json", params={"limit": "50"}).mock(
        return_value=_ok('{"collections": []}', content_type="application/json")
    )
    mock.get(
        f"{_BASE_URL}/search/suggest.json",
        params={"q": "a", "resources[type]": "product"},
    ).mock(return_value=_ok('{"resources": {}}', content_type="application/json"))
    mock.get(f"{_BASE_URL}/cart.js").mock(
        return_value=_ok('{"items": []}', content_type="application/json")
    )
    mock.get(f"{_BASE_URL}/cart").mock(return_value=_ok("<html>cart</html>"))
    mock.get(f"{_BASE_URL}/search").mock(return_value=_ok("<html>search</html>"))
    for slug in ("refund-policy", "privacy-policy", "terms-of-service", "shipping-policy"):
        mock.get(f"{_BASE_URL}/policies/{slug}").mock(return_value=_ok(f"<html>{slug}</html>"))
    for slug in ("about", "contact", "faq"):
        mock.get(f"{_BASE_URL}/pages/{slug}").mock(return_value=_ok(f"<html>{slug}</html>"))


@respx.mock
def test_pipeline_replay_runs_end_to_end_against_drawer_shop_cassette(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Full pipeline drives the cassette through replay and yields the §5.4 artifact tree."""
    _stub_storefront(respx.mock)

    def fake_get_runtime(name: str) -> Any:
        # The pipeline asks for the configured runtime by name; for the
        # replay test we hand back a ReplayRuntime rooted at the
        # hand-crafted cassette regardless of name.
        assert name == "pi"
        return ReplayRuntime(scenario_dir=_CASSETTE_DIR)

    monkeypatch.setattr(pipeline_mod, "get_runtime", fake_get_runtime)

    out_dir = tmp_path / "run"
    config = ExploreConfig(
        url=_BASE_URL,
        out_dir=out_dir,
        runtime="pi",
        max_iters=_REPLAY_MAX_ITERS,
        timeout=_PREFETCH_TIMEOUT_SECONDS,
    )

    result = pipeline_mod.explore(config)

    # Harness drained all four PENDING tasks within budget.
    assert result.final_status is FinalStatus.COMPLETED
    assert result.run_dir == out_dir

    # plan.md is populated with every task flipped to [x] in priority order.
    plan_md = (out_dir / "plan.md").read_text(encoding="utf-8")
    tasks = parse_plan(plan_md).tasks
    assert tuple(t.id for t in tasks) == _EXPECTED_TASKS
    assert all(t.status is TaskStatus.DONE for t in tasks)

    # artifact/parts/ and artifact/evidence/ are populated for every task.
    artifact = out_dir / "artifact"
    parts_dir = artifact / "parts"
    evidence_dir = artifact / "evidence"
    for task_id in _EXPECTED_TASKS:
        part_md = parts_dir / f"{task_id}.md"
        part_caps = parts_dir / f"{task_id}.caps.json"
        evidence_task_dir = evidence_dir / task_id
        assert part_md.is_file(), f"missing parts markdown: {part_md}"
        assert part_md.read_text(encoding="utf-8").strip(), f"empty parts markdown: {part_md}"
        assert part_caps.is_file(), f"missing caps fragment: {part_caps}"
        assert evidence_task_dir.is_dir(), f"missing evidence dir: {evidence_task_dir}"
        evidence_files = [p for p in evidence_task_dir.rglob("*") if p.is_file()]
        assert evidence_files, f"evidence dir is empty: {evidence_task_dir}"

    # Prefetch seed survived as artifact/prefetch/.
    prefetch_dir = artifact / "prefetch"
    assert prefetch_dir.is_dir()
    assert (prefetch_dir / "prefetch.json").is_file()
    assert (prefetch_dir / "index.html").is_file()
    assert (prefetch_dir / "products.json").is_file()
    assert (prefetch_dir / "cart.js").is_file()

    # Telemetry surfaces match the harness §5.3 layout: plan + 4 execs.
    iters_root = out_dir / "iters"
    for iter_id in ("plan", "exec-0001", "exec-0002", "exec-0003", "exec-0004"):
        assert (iters_root / iter_id / "trajectory.json").is_file(), (
            f"missing trajectory.json for iter {iter_id}"
        )
    assert (out_dir / "run.json").is_file()

    # ExploreResult forward-declares the §5.4 published paths under run_dir/artifact/.
    assert result.prefetch_dir == prefetch_dir
    assert result.manual_path == artifact / "manual.md"
    assert result.capabilities_path == artifact / "capabilities.json"
    assert result.stats_path == artifact / "stats.json"
    assert result.manifest_path == artifact / "manifest.json"
