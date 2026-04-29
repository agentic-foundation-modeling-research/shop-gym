"""Unit tests for :mod:`shop_gen.final_eval.visual_sweep` (impl plan T5.1).

Covers the M5 driver scope: the all-pages page-bucket fan-out spec
§5.6 lifecycle, exercised end-to-end against a stub
:class:`~harness.runtimes.base.AgentRuntime` so the per-bucket
sub-iter dirs, screenshot promotion, and ``report.md`` body are
locked without booting Playwright.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import pytest

from harness.runtimes.base import RuntimeIterationResult
from harness.trajectory import Trajectory
from shop_gen.build.verifiers._task_routes import TASK_BUCKETS, BucketCaps
from shop_gen.final_eval.visual_sweep import PlaywrightSkillUnavailableError, run_visual_sweep

# --------------------------------------------------------------------------- #
# Fixtures + stubs
# --------------------------------------------------------------------------- #

_BASE_URL: Final[str] = "http://127.0.0.1:54321"
_EXPECTED_BUCKETS: Final[frozenset[str]] = TASK_BUCKETS["consolidate"]


_STUB_PROMPT: Final[str] = (
    "BASE_URL={base_url}\n"
    "BUCKET={bucket}\n"
    "ROUTES:\n{route_list}\n"
    "CAPABILITIES:\n{capabilities_slice}\n"
    "SCHEMA:\n{verdict_schema}\n"
    "PRIOR:{prior_feedback_or_empty}\n"
)


_MINIMAL_CAPABILITIES: dict[str, Any] = {
    "home.hero": {"present": True},
    "navigation.header": {"depth": 1},
    "footer": {"present": True},
    "collection.filters": ["price"],
    "product.variant_selectors": [],
    "page.about": {"present": True},
    "policies.privacy": {"present": True},
    "search.predictive_types": [],
    "cart.summary": {"present": True},
}


@contextlib.contextmanager
def _stub_dev_server_factory(hydrogen_dir: Path) -> Iterator[str]:
    """Stub :class:`DevServerFactory` — yields :data:`_BASE_URL`, no subprocess."""
    assert hydrogen_dir.is_dir()
    yield _BASE_URL


def _seed_data_dir(data_dir: Path) -> None:
    """Populate the data dir with the minimum fixture for every bucket."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "collections.json").write_text(
        json.dumps(
            [
                {"handle": "outerwear", "product_handles": ["jacket"]},
            ],
        ),
        encoding="utf-8",
    )
    (data_dir / "products.json").write_text(
        json.dumps([{"handle": "jacket", "title": "Heavy Wool Jacket"}]),
        encoding="utf-8",
    )
    (data_dir / "pages.json").write_text(
        json.dumps([{"handle": "about"}]),
        encoding="utf-8",
    )


def _pass_body(*, bucket: str, score: float = 8.0) -> str:
    return json.dumps(
        {
            "verdict": "pass",
            "score": score,
            "category_scores": {"structure": 8, "components": 7, "visual_tone": 9},
            "feedback": f"{bucket}: looks good",
            "pages_judged": 2,
            "issues": [],
        },
    )


def _fail_body(*, bucket: str) -> str:
    return json.dumps(
        {
            "verdict": "fail",
            "score": 5.0,
            "category_scores": {},
            "feedback": f"{bucket}: hero is broken",
            "pages_judged": 2,
            "issues": [
                {
                    "route": "/",
                    "viewport": "mobile",
                    "screenshot": "screenshots/home__mobile.png",
                    "severity": "major",
                    "summary": "hero overflows",
                    "capability": "home.hero",
                },
            ],
        },
    )


@dataclass
class _RecordingRuntime:
    """Stub runtime that emits a per-bucket verdict + screenshot."""

    body_factory: Callable[[str], str]
    write_screenshot: bool = True
    sleep_per_call: float = 0.0
    calls: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        if self.sleep_per_call > 0:
            time.sleep(self.sleep_per_call)
        bucket = _bucket_from_prompt(prompt)
        with self._lock:
            self.calls.append(
                {
                    "run_dir": run_dir,
                    "iter_dir": iter_dir,
                    "prompt": prompt,
                    "timeout": timeout,
                    "bucket": bucket,
                },
            )
        (run_dir / "verdict.json").write_text(self.body_factory(bucket), encoding="utf-8")
        if self.write_screenshot:
            shots = run_dir / "screenshots"
            shots.mkdir(exist_ok=True)
            slug = bucket.replace("_", "-")
            (shots / f"{slug}__desktop.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (shots / f"{slug}__mobile.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        return RuntimeIterationResult(
            trajectory=Trajectory(
                iter_id=f"sweep-{bucket}",
                runtime="stub",
                started_at=now,
                ended_at=now,
                exit_code=0,
                prompt_sha256="0" * 64,
            ),
        )


def _bucket_from_prompt(prompt: str) -> str:
    """Recover the bucket name from a stub-rendered prompt body."""
    for line in prompt.splitlines():
        if line.startswith("BUCKET="):
            return line[len("BUCKET=") :]
    msg = f"prompt body missing BUCKET= line: {prompt!r}"
    raise AssertionError(msg)


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    return tmp_path / "out"


@pytest.fixture
def hydrogen_dir(tmp_path: Path) -> Path:
    target = tmp_path / "hydrogen"
    target.mkdir()
    return target


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    _seed_data_dir(target)
    return target


@pytest.fixture(autouse=True)
def _stub_skill_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default the playwright skill probe to ``True`` for the unit suite.

    The real probe shells out to ``pnpm root -g`` / ``npm root -g`` which
    is slow and depends on the host. Tests that exercise the probe-failure
    path opt back into the False branch via their own monkeypatch.
    """
    monkeypatch.setattr(
        "shop_gen.final_eval.visual_sweep.is_playwright_skill_available",
        lambda: True,
    )


# --------------------------------------------------------------------------- #
# Fan-out lifecycle
# --------------------------------------------------------------------------- #


def test_run_visual_sweep_walks_every_consolidate_bucket(
    out_dir: Path,
    hydrogen_dir: Path,
    data_dir: Path,
) -> None:
    """SC: the sweep dispatches one iteration per `consolidate` bucket.

    Spec §5.6 step 4 — six buckets, six runtime calls, six per-bucket
    sub-iter dirs.
    """
    runtime = _RecordingRuntime(body_factory=lambda b: _pass_body(bucket=b))

    report = run_visual_sweep(
        out_dir=out_dir,
        data_dir=data_dir,
        hydrogen_dir=hydrogen_dir,
        runtime=runtime,
        dev_server_factory=_stub_dev_server_factory,
        capabilities=_MINIMAL_CAPABILITIES,
        prompt_template=_STUB_PROMPT,
    )

    assert report["base_url"] == _BASE_URL
    assert set(report["buckets"]) == _EXPECTED_BUCKETS
    assert len(runtime.calls) == len(_EXPECTED_BUCKETS)
    called_buckets = {call["bucket"] for call in runtime.calls}
    assert called_buckets == _EXPECTED_BUCKETS

    # Each bucket has a sub-workspace under visual_eval/work/<bucket>/
    work_root = out_dir / "visual_eval" / "work"
    for bucket in _EXPECTED_BUCKETS:
        bucket_work = work_root / bucket / "work"
        assert bucket_work.is_dir(), f"missing sub-workspace for {bucket}"
        assert (bucket_work / "verdict.json").is_file()
        assert (bucket_work / "prompt.md").is_file()
        assert (bucket_work / "routes.json").is_file()


def test_run_visual_sweep_promotes_screenshots_per_bucket(
    out_dir: Path,
    hydrogen_dir: Path,
    data_dir: Path,
) -> None:
    """Screenshots land under `visual_eval/screenshots/<bucket>/<page>/<viewport>.png`."""
    runtime = _RecordingRuntime(body_factory=lambda b: _pass_body(bucket=b))

    run_visual_sweep(
        out_dir=out_dir,
        data_dir=data_dir,
        hydrogen_dir=hydrogen_dir,
        runtime=runtime,
        dev_server_factory=_stub_dev_server_factory,
        capabilities=_MINIMAL_CAPABILITIES,
        prompt_template=_STUB_PROMPT,
    )

    screenshots_root = out_dir / "visual_eval" / "screenshots"
    for bucket in _EXPECTED_BUCKETS:
        slug = bucket.replace("_", "-")
        bucket_dir = screenshots_root / bucket
        assert bucket_dir.is_dir(), f"missing screenshot dir for {bucket}"
        # `<bucket>/<slug>/desktop.png` + `<bucket>/<slug>/mobile.png`
        assert (bucket_dir / slug / "desktop.png").is_file()
        assert (bucket_dir / slug / "mobile.png").is_file()


def test_run_visual_sweep_writes_non_empty_report(
    out_dir: Path,
    hydrogen_dir: Path,
    data_dir: Path,
) -> None:
    """`report.md` is written and carries a section per bucket."""
    runtime = _RecordingRuntime(body_factory=lambda b: _pass_body(bucket=b))

    report = run_visual_sweep(
        out_dir=out_dir,
        data_dir=data_dir,
        hydrogen_dir=hydrogen_dir,
        runtime=runtime,
        dev_server_factory=_stub_dev_server_factory,
        capabilities=_MINIMAL_CAPABILITIES,
        prompt_template=_STUB_PROMPT,
    )

    report_path = out_dir / "visual_eval" / "report.md"
    assert report_path.is_file()
    body = report_path.read_text(encoding="utf-8")
    assert body.strip() != ""
    assert "Visual sweep report" in body
    assert _BASE_URL in body
    for bucket in _EXPECTED_BUCKETS:
        assert f"`{bucket}`" in body, f"missing bucket section: {bucket}"
    assert report["report_path"] == "visual_eval/report.md"
    assert report["pages_judged"] == 2 * len(_EXPECTED_BUCKETS)


def test_run_visual_sweep_records_failed_bucket_and_continues(
    out_dir: Path,
    hydrogen_dir: Path,
    data_dir: Path,
) -> None:
    """A failing bucket is recorded; the other buckets still run."""

    def _body_factory(bucket: str) -> str:
        if bucket == "homepage":
            return _fail_body(bucket=bucket)
        return _pass_body(bucket=bucket)

    runtime = _RecordingRuntime(body_factory=_body_factory)

    report = run_visual_sweep(
        out_dir=out_dir,
        data_dir=data_dir,
        hydrogen_dir=hydrogen_dir,
        runtime=runtime,
        dev_server_factory=_stub_dev_server_factory,
        capabilities=_MINIMAL_CAPABILITIES,
        prompt_template=_STUB_PROMPT,
    )

    by_bucket = {entry["bucket"]: entry for entry in report["per_bucket"]}
    assert by_bucket["homepage"]["verdict"] == "fail"
    assert by_bucket["homepage"]["issues"][0]["severity"] == "major"
    assert by_bucket["product"]["verdict"] == "pass"
    assert len(runtime.calls) == len(_EXPECTED_BUCKETS)


def test_run_visual_sweep_records_missing_verdict_as_error(
    out_dir: Path,
    hydrogen_dir: Path,
    data_dir: Path,
) -> None:
    """A bucket whose runtime call never emits `verdict.json` records an error."""

    def _body_factory(bucket: str) -> str:
        # Return junk for one bucket so the parser drops it.
        if bucket == "homepage":
            return "{ not even json"
        return _pass_body(bucket=bucket)

    runtime = _RecordingRuntime(body_factory=_body_factory)

    report = run_visual_sweep(
        out_dir=out_dir,
        data_dir=data_dir,
        hydrogen_dir=hydrogen_dir,
        runtime=runtime,
        dev_server_factory=_stub_dev_server_factory,
        capabilities=_MINIMAL_CAPABILITIES,
        prompt_template=_STUB_PROMPT,
    )

    by_bucket = {entry["bucket"]: entry for entry in report["per_bucket"]}
    assert by_bucket["homepage"]["verdict"] is None
    assert by_bucket["homepage"]["error"] == "missing or malformed verdict.json"
    # Other buckets still produced PASS verdicts.
    assert by_bucket["collections"]["verdict"] == "pass"


def test_run_visual_sweep_skips_bucket_when_dataset_yields_no_routes(
    out_dir: Path,
    hydrogen_dir: Path,
    tmp_path: Path,
) -> None:
    """A bucket whose dataset is empty short-circuits without calling the runtime."""
    # Build a data dir that only seeds collections; products, pages
    # JSON missing → product / cart_search / info_pages buckets resolve
    # to fewer (or zero) routes for some.
    sparse = tmp_path / "sparse"
    sparse.mkdir()
    # Empty pages.json → info_pages still has /policies/privacy hard-coded,
    # so we drop that file entirely. Same for products.json → product
    # bucket resolves to no routes.
    runtime = _RecordingRuntime(body_factory=lambda b: _pass_body(bucket=b))

    report = run_visual_sweep(
        out_dir=out_dir,
        data_dir=sparse,
        hydrogen_dir=hydrogen_dir,
        runtime=runtime,
        dev_server_factory=_stub_dev_server_factory,
        capabilities=_MINIMAL_CAPABILITIES,
        prompt_template=_STUB_PROMPT,
    )

    by_bucket = {entry["bucket"]: entry for entry in report["per_bucket"]}
    # `product` resolves to no routes (empty collections.json) — recorded
    # as a skip with verdict=None.
    assert by_bucket["product"]["verdict"] is None
    assert by_bucket["product"]["error"] == "no routes resolved for bucket"
    # The runtime was *not* called for the empty bucket(s).
    called_buckets = {call["bucket"] for call in runtime.calls}
    assert "product" not in called_buckets


def test_run_visual_sweep_filters_capabilities_per_bucket(
    out_dir: Path,
    hydrogen_dir: Path,
    data_dir: Path,
) -> None:
    """The capabilities slice handed to each bucket excludes other-bucket keys."""
    captured: dict[str, str] = {}

    def _body_factory(bucket: str) -> str:
        return _pass_body(bucket=bucket)

    runtime = _RecordingRuntime(body_factory=_body_factory)
    run_visual_sweep(
        out_dir=out_dir,
        data_dir=data_dir,
        hydrogen_dir=hydrogen_dir,
        runtime=runtime,
        dev_server_factory=_stub_dev_server_factory,
        capabilities=_MINIMAL_CAPABILITIES,
        prompt_template=_STUB_PROMPT,
    )
    for call in runtime.calls:
        captured[call["bucket"]] = call["prompt"]

    homepage_prompt = captured["homepage"]
    assert "home.hero" in homepage_prompt
    # Capabilities outside the homepage slice never reach the prompt.
    assert "product.variant_selectors" not in homepage_prompt
    assert "search.predictive_types" not in homepage_prompt

    product_prompt = captured["product"]
    assert "product.variant_selectors" in product_prompt
    assert "home.hero" not in product_prompt


def test_run_visual_sweep_fan_out_scales_with_longest_bucket(
    out_dir: Path,
    hydrogen_dir: Path,
    data_dir: Path,
) -> None:
    """Wall clock approximates max(per-bucket) when concurrency >= bucket count.

    Spec §5.6 step 4: the fan-out runs under a `ThreadPoolExecutor`, so
    six 0.1s sleeps complete in ~0.1s when the pool is wide enough,
    not 0.6s. We allow generous slack for CI variance.
    """
    sleep_s = 0.05
    runtime = _RecordingRuntime(
        body_factory=lambda b: _pass_body(bucket=b),
        sleep_per_call=sleep_s,
    )

    started = time.monotonic()
    run_visual_sweep(
        out_dir=out_dir,
        data_dir=data_dir,
        hydrogen_dir=hydrogen_dir,
        runtime=runtime,
        dev_server_factory=_stub_dev_server_factory,
        capabilities=_MINIMAL_CAPABILITIES,
        prompt_template=_STUB_PROMPT,
        max_concurrency=len(_EXPECTED_BUCKETS),
    )
    elapsed = time.monotonic() - started

    # Six serial calls would take ~0.3s; under the pool the wall clock
    # should be well under half of that. Generous bound for slow CI.
    serial_floor = sleep_s * len(_EXPECTED_BUCKETS)
    assert elapsed < serial_floor * 0.75, (
        f"fan-out took {elapsed:.3f}s, expected < {serial_floor * 0.75:.3f}s"
    )


def test_run_visual_sweep_uses_sweep_caps_by_default(
    out_dir: Path,
    hydrogen_dir: Path,
    tmp_path: Path,
) -> None:
    """`SWEEP_CAPS` widens the per-bucket route count beyond the `DEFAULT_CAPS` limit."""
    data_dir = tmp_path / "wide_data"
    data_dir.mkdir()
    # Four collections — DEFAULT_CAPS would surface only one.
    (data_dir / "collections.json").write_text(
        json.dumps(
            [{"handle": f"col-{i}", "product_handles": [f"p-{i}"]} for i in range(4)],
        ),
        encoding="utf-8",
    )
    (data_dir / "products.json").write_text(
        json.dumps(
            [{"handle": f"p-{i}", "title": f"Product {i}"} for i in range(4)],
        ),
        encoding="utf-8",
    )
    (data_dir / "pages.json").write_text(json.dumps([{"handle": "about"}]), encoding="utf-8")
    runtime = _RecordingRuntime(body_factory=lambda b: _pass_body(bucket=b))

    report = run_visual_sweep(
        out_dir=out_dir,
        data_dir=data_dir,
        hydrogen_dir=hydrogen_dir,
        runtime=runtime,
        dev_server_factory=_stub_dev_server_factory,
        capabilities=_MINIMAL_CAPABILITIES,
        prompt_template=_STUB_PROMPT,
    )

    by_bucket = {entry["bucket"]: entry for entry in report["per_bucket"]}
    # SWEEP_CAPS allows up to 8 collections * 1 product/coll = 4 PDPs.
    assert len(by_bucket["product"]["routes"]) == 4  # noqa: PLR2004 -- mirrors SWEEP_CAPS
    # Tight `DEFAULT_CAPS` would have capped at 1; the override is observable.


def test_run_visual_sweep_caps_override_observable(
    out_dir: Path,
    hydrogen_dir: Path,
    data_dir: Path,
) -> None:
    """Custom `BucketCaps` flow into `bucket_routes` — observable via route count."""
    runtime = _RecordingRuntime(body_factory=lambda b: _pass_body(bucket=b))
    tight = BucketCaps(max_collections=1, products_per_collection=1, max_pages=1)

    report = run_visual_sweep(
        out_dir=out_dir,
        data_dir=data_dir,
        hydrogen_dir=hydrogen_dir,
        runtime=runtime,
        dev_server_factory=_stub_dev_server_factory,
        capabilities=_MINIMAL_CAPABILITIES,
        prompt_template=_STUB_PROMPT,
        caps=tight,
    )

    by_bucket = {entry["bucket"]: entry for entry in report["per_bucket"]}
    # tight caps → exactly 1 collection route under `/collections/<handle>`
    # plus the `/collections` index, so 2 routes total.
    assert len(by_bucket["collections"]["routes"]) == 2  # noqa: PLR2004 -- /collections + 1 handle


# --------------------------------------------------------------------------- #
# Skill probe (T5.6, spec §5.5.1)
# --------------------------------------------------------------------------- #


def test_run_visual_sweep_raises_when_skill_unavailable(
    out_dir: Path,
    hydrogen_dir: Path,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Probe failure raises `PlaywrightSkillUnavailableError` before any I/O."""
    monkeypatch.setattr(
        "shop_gen.final_eval.visual_sweep.is_playwright_skill_available",
        lambda: False,
    )
    runtime = _RecordingRuntime(body_factory=lambda b: _pass_body(bucket=b))

    with (
        caplog.at_level("WARNING", logger="shop_gen.final_eval.visual_sweep"),
        pytest.raises(PlaywrightSkillUnavailableError, match="playwright skill not available"),
    ):
        run_visual_sweep(
            out_dir=out_dir,
            data_dir=data_dir,
            hydrogen_dir=hydrogen_dir,
            runtime=runtime,
            dev_server_factory=_stub_dev_server_factory,
            capabilities=_MINIMAL_CAPABILITIES,
            prompt_template=_STUB_PROMPT,
        )

    # Single warning emitted with the install hint.
    skill_warnings = [rec for rec in caplog.records if "pi-playwright" in rec.getMessage()]
    assert len(skill_warnings) == 1
    # No on-disk artifacts created on probe failure.
    assert not (out_dir / "visual_eval").exists()
    # Runtime never invoked.
    assert runtime.calls == []
