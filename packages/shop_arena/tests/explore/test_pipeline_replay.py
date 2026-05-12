"""End-to-end replay test for :func:`shop_arena.explore.pipeline.explore` (T2.6 + T3.3).

Drives the full pipeline against the hand-crafted ``fixture_drawer_shop``
cassette under :class:`harness.runtimes.replay.ReplayRuntime`. No real
LLM, no real network: storefront prefetch is stubbed via ``respx``, the
runtime selector is monkey-patched to return a ``ReplayRuntime`` rooted
at the cassette directory, and a :class:`_StubLLM` is injected explicitly
so the §5.10 synthesis call has a usable client (``ReplayRuntime`` does
not implement :class:`harness.runtimes.LLMCompleter`).

This is the milestone gate for SC1 ("end-to-end") and SC4
("replayable"): a recorded `shop_arena.explore` run drives end-to-end through
`harness.runtimes.replay` *and* publishes the four §5.10 artifacts
(``manual.md`` / ``capabilities.json`` / ``stats.json`` /
``manifest.json``) under ``run_dir/artifact/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from harness.config import FinalStatus
from harness.plan import parse as parse_plan
from harness.plan.tasks import TaskStatus
from harness.runtimes.replay import ReplayRuntime
from shop_arena.explore import pipeline as pipeline_mod
from shop_arena.explore.config import ExploreConfig

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

# Synthesized manual body used by the injected stub LLM. Must clear
# :data:`shop_arena.explore.synthesize.manual.MANUAL_MIN_CHARS` (200 chars
# stripped) so the pipeline's loud-failure guard does not trip.
_STUB_MANUAL_BODY = (
    "# Shop Manual\n\n"
    "## Overview\n\n"
    "Anonymized synthesized manual produced by the replay test stub.\n\n"
    + ("Structured prose summarizing per-task parts. " * 8)
    + "\n"
)


class _StubLLM:
    """Minimal :class:`shop_arena.explore.synthesize.LLMClient` stub for replay tests.

    The replay runtime does not implement
    :class:`harness.runtimes.LLMCompleter`, so :func:`explore` would
    raise :class:`shop_arena.explore.synthesize.SynthesisError` if called
    without an explicit ``llm=`` argument. Tests inject this stub to
    keep the synthesis call deterministic and credential-less.
    """

    def __init__(self, response: str = _STUB_MANUAL_BODY) -> None:
        self._response = response
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._response


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
    mock.get(f"{_BASE_URL}/products.json", params={"page": "1", "limit": "250"}).mock(
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

    def fake_get_runtime(name: str, **_kwargs: Any) -> Any:
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

    result = pipeline_mod.explore(config, llm=_StubLLM())

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

    # Synthesis (§5.10) ran after the harness loop and published all four files.
    _assert_synthesis_artifacts_published(result)


def _assert_synthesis_artifacts_published(result: Any) -> None:
    """Validate the four §5.10 artifacts the pipeline writes after the harness loop.

    Split out from the main test body to keep the test under ruff's
    statement-count budget; behavior is the same as inlined assertions.
    """
    assert result.manual_path.is_file()
    assert result.capabilities_path.is_file()
    assert result.stats_path.is_file()
    assert result.manifest_path.is_file()

    # Capabilities deep-merged from the four cassette fragments.
    caps = json.loads(result.capabilities_path.read_text(encoding="utf-8"))
    assert caps["cart"]["type"] == "drawer"
    assert caps["search"]["has_predictive"] is True
    assert caps["site_shell"]["has_mega_menu"] is True

    # Manifest mirrors the harness summary. ``manual_fallback`` was removed
    # in M3 — synthesis now fails loudly when the LLM call misbehaves.
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert "manual_fallback" not in manifest
    assert manifest["harness_status"] == "completed"
    assert manifest["plan_tasks_total"] == len(_EXPECTED_TASKS)
    assert manifest["plan_tasks_done"] == len(_EXPECTED_TASKS)

    # Manual is whatever the injected stub returned — the replay test
    # uses :data:`_STUB_MANUAL_BODY`, which has the same `# Shop Manual`
    # heading the synthesis prompt would normally produce.
    manual_text = result.manual_path.read_text(encoding="utf-8")
    assert manual_text.startswith("# Shop Manual")


@dataclass(frozen=True)
class _ReplayFixture:
    """One fixture-storefront slug + the assertions the replay pipeline must satisfy."""

    name: str
    base_url: str
    tasks: tuple[str, ...]
    sentinel_caps: tuple[tuple[tuple[str, ...], object], ...]


_DEMO_STOREFRONT_FIXTURE = _ReplayFixture(
    name="fixture_demo_storefront",
    base_url="https://demo-storefront.example.invalid",
    tasks=("homepage_sections", "info_pages", "cart_drawer"),
    sentinel_caps=(
        (("cart", "type"), "drawer"),
        (("site_shell", "has_mega_menu"), False),
        (("homepage", "section_count"), 2),
    ),
)

_FEATURE_RICH_FIXTURE = _ReplayFixture(
    name="fixture_feature_rich",
    base_url="https://feature-rich-shop.example",
    tasks=(
        "homepage_sections",
        "header_navigation",
        "collection_filters",
        "cart_drawer",
    ),
    sentinel_caps=(
        (("cart", "type"), "drawer"),
        (("site_shell", "has_mega_menu"), True),
        (("site_shell", "nav_depth"), 2),
        (("search", "has_predictive"), True),
    ),
)

_ALT_FIXTURES: tuple[_ReplayFixture, ...] = (_DEMO_STOREFRONT_FIXTURE, _FEATURE_RICH_FIXTURE)


def _stub_storefront_at(mock: respx.MockRouter, base_url: str) -> None:
    """Re-bind the §5.9 prefetch URL plan against an arbitrary base URL."""
    mock.get(f"{base_url}/robots.txt").mock(
        return_value=_ok("User-agent: *\nAllow: /\n", content_type="text/plain")
    )
    mock.get(f"{base_url}/").mock(return_value=_ok("<!doctype html><html></html>"))
    mock.get(f"{base_url}/sitemap.xml").mock(
        return_value=_ok(
            "<?xml version='1.0'?><urlset></urlset>",
            content_type="application/xml",
        )
    )
    mock.get(f"{base_url}/products.json", params={"page": "1", "limit": "250"}).mock(
        return_value=_ok('{"products": []}', content_type="application/json")
    )
    mock.get(f"{base_url}/collections.json", params={"limit": "50"}).mock(
        return_value=_ok('{"collections": []}', content_type="application/json")
    )
    mock.get(
        f"{base_url}/search/suggest.json",
        params={"q": "a", "resources[type]": "product"},
    ).mock(return_value=_ok('{"resources": {}}', content_type="application/json"))
    mock.get(f"{base_url}/cart.js").mock(
        return_value=_ok('{"items": []}', content_type="application/json")
    )
    mock.get(f"{base_url}/cart").mock(return_value=_ok("<html>cart</html>"))
    mock.get(f"{base_url}/search").mock(return_value=_ok("<html>search</html>"))
    for slug in ("refund-policy", "privacy-policy", "terms-of-service", "shipping-policy"):
        mock.get(f"{base_url}/policies/{slug}").mock(return_value=_ok(f"<html>{slug}</html>"))
    for slug in ("about", "contact", "faq"):
        mock.get(f"{base_url}/pages/{slug}").mock(return_value=_ok(f"<html>{slug}</html>"))


@pytest.mark.parametrize("fixture", _ALT_FIXTURES, ids=lambda fx: fx.name)
@respx.mock
def test_pipeline_replay_runs_end_to_end_against_alt_cassettes(
    fixture: _ReplayFixture, tmp_path: Path, monkeypatch: Any
) -> None:
    """Parameterised replay coverage for the M4 fixture cassettes (T4.2).

    Same end-to-end shape as the drawer-shop test above: prefetch is
    stubbed via ``respx`` and the runtime is monkey-patched to a
    :class:`~harness.runtimes.replay.ReplayRuntime` rooted at the
    fixture cassette. The fixture spec drives the expected task list
    and the sentinel capability claims each cassette is meant to
    advertise.
    """
    cassette_dir = Path(__file__).resolve().parent / "cassettes" / fixture.name
    _stub_storefront_at(respx.mock, fixture.base_url)

    def fake_get_runtime(name: str, **_kwargs: Any) -> Any:
        assert name == "pi"
        return ReplayRuntime(scenario_dir=cassette_dir)

    monkeypatch.setattr(pipeline_mod, "get_runtime", fake_get_runtime)

    out_dir = tmp_path / "run"
    config = ExploreConfig(
        url=fixture.base_url,
        out_dir=out_dir,
        runtime="pi",
        max_iters=len(fixture.tasks) + 2,
        timeout=_PREFETCH_TIMEOUT_SECONDS,
    )

    result = pipeline_mod.explore(config, llm=_StubLLM())

    assert result.final_status is FinalStatus.COMPLETED
    plan_md = (out_dir / "plan.md").read_text(encoding="utf-8")
    parsed_tasks = parse_plan(plan_md).tasks
    assert tuple(t.id for t in parsed_tasks) == fixture.tasks
    assert all(t.status is TaskStatus.DONE for t in parsed_tasks)

    artifact = out_dir / "artifact"
    for task_id in fixture.tasks:
        assert (artifact / "parts" / f"{task_id}.md").is_file()
        assert (artifact / "parts" / f"{task_id}.caps.json").is_file()
        evidence = artifact / "evidence" / task_id
        assert evidence.is_dir() and any(p.is_file() for p in evidence.rglob("*"))

    iters_root = out_dir / "iters"
    assert (iters_root / "plan" / "trajectory.json").is_file()
    for n in range(1, len(fixture.tasks) + 1):
        assert (iters_root / f"exec-{n:04d}" / "trajectory.json").is_file()

    _assert_alt_synthesis_artifacts(result, fixture)


def _assert_alt_synthesis_artifacts(result: Any, fixture: _ReplayFixture) -> None:
    """Validate the §5.10 publication step for a parameterised fixture."""
    assert result.manual_path.is_file()
    assert result.capabilities_path.is_file()
    assert result.stats_path.is_file()
    assert result.manifest_path.is_file()

    caps = json.loads(result.capabilities_path.read_text(encoding="utf-8"))
    for path, expected in fixture.sentinel_caps:
        node: Any = caps
        for key in path:
            node = node[key]
        assert node == expected, (
            f"{fixture.name}: expected {'.'.join(path)}={expected!r}, got {node!r}"
        )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert "manual_fallback" not in manifest
    assert manifest["harness_status"] == "completed"
    assert manifest["plan_tasks_total"] == len(fixture.tasks)
    assert manifest["plan_tasks_done"] == len(fixture.tasks)

    # Manual is whatever the injected stub returned (see ``_StubLLM``).
    manual_text = result.manual_path.read_text(encoding="utf-8")
    assert manual_text.startswith("# Shop Manual")
