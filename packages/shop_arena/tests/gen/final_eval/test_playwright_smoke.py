"""Unit tests for :mod:`shop_arena.gen.final_eval.playwright_smoke` (T6.1).

The Playwright + ``pnpm dev`` integration lands with T6.2 / T6.3; T6.1
ships the smoke runner against its protocol seams. The tests inject:

* a stub :class:`DevServerFactory` that yields a fake base URL without
  spawning Node;
* a stub :class:`BrowserDriver` that fabricates deterministic screenshot
  bytes and surfaces both the happy path and the failure path.

Together they exercise:

1. flow resolution against the M5 fixture artifact (``runs/build/artifact/``
   produced by the Phase 4 build-loop replay) — real product /
   collection handles flow through to the resolved URLs;
2. screenshots-directory creation;
3. report aggregation — both successful screenshots and driver-reported
   failures land on :class:`SmokeReport`;
4. defensive fallback when ``data/products.json`` is missing or empty.
"""

from __future__ import annotations

import contextlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from shop_arena.gen.final_eval.playwright_smoke import (
    DEFAULT_VIEWPORTS,
    Screenshot,
    SmokeAction,
    SmokeFailure,
    SmokeFlow,
    SmokeReport,
    SmokeStep,
    Viewport,
    resolve_smoke_flow,
    run_playwright_smoke,
)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

_DATA_FIXTURE_DIR: Final[Path] = (
    Path(__file__).resolve().parent.parent / "data_synth" / "fixtures" / "sandbox_shop_v0"
)
"""Canonical M4 dataset fixture shared across phases (re-used as M5 substrate)."""

_BASE_URL: Final[str] = "http://127.0.0.1:54321"
"""Stub base URL the fake dev server reports."""

_EXPECTED_FIRST_PRODUCT: Final[str] = "tickless-anti-tick-collar"
"""First handle in the M4 ``products.json`` fixture."""

_EXPECTED_FIRST_COLLECTION: Final[str] = "dog-essentials"
"""First handle in the M4 ``collections.json`` fixture."""

_EXPECTED_STEP_ORDER: Final[tuple[str, ...]] = (
    "home",
    "collection",
    "product",
    "add_to_cart",
    "checkout_redirect",
)
"""Spec §5.5.5 smoke-flow step order."""


# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


class _RecordingBrowserDriver:
    """Stub :class:`BrowserDriver` that records its inputs and writes PNG stubs.

    Production drivers boot Playwright; this stand-in fabricates a
    deterministic 8-byte payload per (step, viewport) pair so the
    runner-level assertions can read screenshot files back without
    needing a real browser.
    """

    def __init__(self) -> None:
        """Initialise with empty recording buffers."""
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        *,
        base_url: str,
        flow: SmokeFlow,
        screenshots_dir: Path,
    ) -> tuple[tuple[Screenshot, ...], tuple[SmokeFailure, ...]]:
        """Walk ``flow`` and emit one screenshot file per (step, viewport) pair."""
        self.calls.append(
            {
                "base_url": base_url,
                "flow": flow,
                "screenshots_dir": screenshots_dir,
            },
        )
        screenshots: list[Screenshot] = []
        for step in flow.steps:
            for viewport in flow.viewports:
                path = screenshots_dir / f"{step.name}-{viewport.name}.png"
                path.write_bytes(b"PNGSTUB\n")
                final_url = (
                    f"{base_url}/checkout?session=stub"
                    if step.action is SmokeAction.CHECKOUT_REDIRECT
                    else f"{base_url}{step.url}"
                )
                screenshots.append(
                    Screenshot(
                        step=step.name,
                        viewport=viewport.name,
                        path=path,
                        url=final_url,
                    ),
                )
        return tuple(screenshots), ()


class _PartiallyFailingBrowserDriver:
    """Stub driver that fails the ``add_to_cart`` step.

    Used to exercise the report-aggregation path on driver failures —
    spec §5.5.5 is advisory: a failure does not raise from
    :func:`run_playwright_smoke`.
    """

    def __call__(
        self,
        *,
        base_url: str,
        flow: SmokeFlow,
        screenshots_dir: Path,
    ) -> tuple[tuple[Screenshot, ...], tuple[SmokeFailure, ...]]:
        """Succeed on every step except ``add_to_cart``."""
        screenshots: list[Screenshot] = []
        failures: list[SmokeFailure] = []
        for step in flow.steps:
            for viewport in flow.viewports:
                if step.name == "add_to_cart":
                    failures.append(
                        SmokeFailure(
                            step=step.name,
                            viewport=viewport.name,
                            error="add-to-cart selector not found",
                        ),
                    )
                    continue
                path = screenshots_dir / f"{step.name}-{viewport.name}.png"
                path.write_bytes(b"PNGSTUB\n")
                screenshots.append(
                    Screenshot(
                        step=step.name,
                        viewport=viewport.name,
                        path=path,
                        url=f"{base_url}{step.url}",
                    ),
                )
        return tuple(screenshots), tuple(failures)


@contextlib.contextmanager
def _stub_dev_server_factory(hydrogen_dir: Path) -> Iterator[str]:
    """Stub :class:`DevServerFactory` — yields :data:`_BASE_URL`, no subprocess."""
    assert hydrogen_dir.is_dir()
    yield _BASE_URL


@contextlib.contextmanager
def _exploding_dev_server_factory(hydrogen_dir: Path) -> Iterator[str]:
    """Stub factory that fails to boot — exercises propagation."""
    del hydrogen_dir
    raise RuntimeError("pnpm dev refused to boot")
    yield ""  # unreachable; keeps the function a generator


# --------------------------------------------------------------------------- #
# Workspace helpers
# --------------------------------------------------------------------------- #


def _materialise_m5_artifact(out_dir: Path) -> Path:
    """Lay out the post-build M5 artifact tree the smoke flow runs against.

    Mirrors the directory shape :class:`RunBuildHarnessLoopStep`
    produces under ``runs/build/artifact/``: a ``hydrogen/`` subtree
    (the cloned + mutated template) and a ``data/`` subtree (the
    canonical M4 fixture). The smoke runner reads handles from
    ``<out_dir>/data/`` (per :func:`resolve_smoke_flow`'s contract)
    and walks the dev server rooted at ``<out_dir>/hydrogen/``.

    Returns:
        Path to ``out_dir`` for ergonomic chaining.
    """
    hydrogen_dir = out_dir / "hydrogen"
    (hydrogen_dir / "app").mkdir(parents=True)
    (hydrogen_dir / "package.json").write_text(
        '{"name":"hydrogen"}\n',
        encoding="utf-8",
    )
    (hydrogen_dir / "app" / "root.tsx").write_text("// root\n", encoding="utf-8")

    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True)
    for name in (
        "store.json",
        "products.json",
        "collections.json",
        "pages.json",
        "policies.json",
        "navigation.json",
    ):
        shutil.copy(_DATA_FIXTURE_DIR / name, data_dir / name)
    return out_dir


# --------------------------------------------------------------------------- #
# resolve_smoke_flow
# --------------------------------------------------------------------------- #


def test_resolve_smoke_flow_uses_first_handles_from_m5_artifact(tmp_path: Path) -> None:
    """``resolve_smoke_flow`` substitutes real handles from the M5 artifact.

    Asserts the canonical step order, the resolved URLs, and the
    default viewport list (spec §5.5.5).
    """
    out_dir = _materialise_m5_artifact(tmp_path)

    flow = resolve_smoke_flow(out_dir=out_dir)

    assert tuple(step.name for step in flow.steps) == _EXPECTED_STEP_ORDER

    home, collection, product, add_to_cart, checkout = flow.steps
    assert home.url == "/"
    assert home.action is SmokeAction.NONE

    assert collection.url == f"/collections/{_EXPECTED_FIRST_COLLECTION}"
    assert collection.action is SmokeAction.NONE

    assert product.url == f"/products/{_EXPECTED_FIRST_PRODUCT}"
    assert product.action is SmokeAction.NONE

    assert add_to_cart.url == f"/products/{_EXPECTED_FIRST_PRODUCT}"
    assert add_to_cart.action is SmokeAction.ADD_TO_CART
    assert add_to_cart.selector is not None and add_to_cart.selector

    assert checkout.url == "/cart"
    assert checkout.action is SmokeAction.CHECKOUT_REDIRECT
    assert checkout.selector is not None and checkout.selector

    assert flow.viewports == DEFAULT_VIEWPORTS


def test_resolve_smoke_flow_falls_back_when_data_is_missing(tmp_path: Path) -> None:
    """Missing ``data/`` files yield a well-formed flow with placeholder handles."""
    flow = resolve_smoke_flow(out_dir=tmp_path)  # tmp_path has no data/.

    # Step order is unchanged; URLs use the placeholder handles.
    assert tuple(step.name for step in flow.steps) == _EXPECTED_STEP_ORDER
    assert flow.steps[1].url == "/collections/placeholder-collection"
    assert flow.steps[2].url == "/products/placeholder-product"
    assert flow.steps[3].url == "/products/placeholder-product"
    assert flow.steps[4].url == "/cart"


def test_resolve_smoke_flow_falls_back_when_data_is_empty_array(tmp_path: Path) -> None:
    """Empty JSON arrays trip the fallback (defensive — Phase 2 fills them)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "products.json").write_text("[]", encoding="utf-8")
    (data_dir / "collections.json").write_text("[]", encoding="utf-8")

    flow = resolve_smoke_flow(out_dir=tmp_path)

    assert flow.steps[1].url == "/collections/placeholder-collection"
    assert flow.steps[2].url == "/products/placeholder-product"


def test_resolve_smoke_flow_accepts_custom_viewports(tmp_path: Path) -> None:
    """Caller-supplied viewports flow through unchanged."""
    out_dir = _materialise_m5_artifact(tmp_path)
    custom = (Viewport(name="tablet", width=768, height=1024),)

    flow = resolve_smoke_flow(out_dir=out_dir, viewports=custom)

    assert flow.viewports == custom


# --------------------------------------------------------------------------- #
# run_playwright_smoke — happy path
# --------------------------------------------------------------------------- #


def test_run_playwright_smoke_walks_full_flow_and_captures_screenshots(
    tmp_path: Path,
) -> None:
    """Happy path: every (step, viewport) pair yields a screenshot file."""
    out_dir = _materialise_m5_artifact(tmp_path)
    flow = resolve_smoke_flow(out_dir=out_dir)
    screenshots_dir = out_dir / "runs" / "build" / "final_eval" / "screenshots"
    driver = _RecordingBrowserDriver()

    report = run_playwright_smoke(
        hydrogen_dir=out_dir / "hydrogen",
        screenshots_dir=screenshots_dir,
        flow=flow,
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=driver,
    )

    # Driver was invoked exactly once with the correct wiring.
    assert len(driver.calls) == 1
    call = driver.calls[0]
    assert call["base_url"] == _BASE_URL
    assert call["flow"] is flow
    assert call["screenshots_dir"] == screenshots_dir

    # Screenshots dir was pre-created.
    assert screenshots_dir.is_dir()

    # Every (step, viewport) pair produced a screenshot file.
    expected = {(step.name, viewport.name) for step in flow.steps for viewport in flow.viewports}
    actual = {(s.step, s.viewport) for s in report.screenshots}
    assert actual == expected
    for shot in report.screenshots:
        assert shot.path.is_file()
        assert shot.path.read_bytes() == b"PNGSTUB\n"

    # Report shape.
    assert isinstance(report, SmokeReport)
    assert report.base_url == _BASE_URL
    assert report.flow is flow
    assert report.failures == ()
    assert report.ok is True


def test_run_playwright_smoke_records_checkout_redirect_url(tmp_path: Path) -> None:
    """The checkout step's recorded URL reflects the post-redirect landing page."""
    out_dir = _materialise_m5_artifact(tmp_path)
    flow = resolve_smoke_flow(out_dir=out_dir)
    driver = _RecordingBrowserDriver()

    report = run_playwright_smoke(
        hydrogen_dir=out_dir / "hydrogen",
        screenshots_dir=out_dir / "screens",
        flow=flow,
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=driver,
    )

    checkout_shots = [s for s in report.screenshots if s.step == "checkout_redirect"]
    assert checkout_shots, "checkout_redirect step did not yield a screenshot"
    for shot in checkout_shots:
        # Stub driver appends ``/checkout?session=stub`` for the
        # checkout-redirect step — this asserts the field is populated
        # rather than identical to the seed URL.
        assert "checkout" in shot.url


# --------------------------------------------------------------------------- #
# run_playwright_smoke — failure paths
# --------------------------------------------------------------------------- #


def test_run_playwright_smoke_aggregates_driver_failures(tmp_path: Path) -> None:
    """Driver-reported failures end up on :attr:`SmokeReport.failures`."""
    out_dir = _materialise_m5_artifact(tmp_path)
    flow = resolve_smoke_flow(out_dir=out_dir)

    report = run_playwright_smoke(
        hydrogen_dir=out_dir / "hydrogen",
        screenshots_dir=out_dir / "screens",
        flow=flow,
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=_PartiallyFailingBrowserDriver(),
    )

    # Failures present, ok = False, but the function did not raise.
    assert report.ok is False
    assert len(report.failures) == len(flow.viewports)
    assert {f.step for f in report.failures} == {"add_to_cart"}
    for failure in report.failures:
        assert "add-to-cart" in failure.error

    # Successful steps still produced screenshots.
    successful_steps = {s.step for s in report.screenshots}
    assert "add_to_cart" not in successful_steps
    expected_successful = {step for step in _EXPECTED_STEP_ORDER if step != "add_to_cart"}
    assert successful_steps == expected_successful


def test_run_playwright_smoke_raises_when_hydrogen_dir_missing(tmp_path: Path) -> None:
    """A missing hydrogen tree is a wiring bug, not advisory — raise."""
    flow = SmokeFlow(steps=(SmokeStep(name="home", url="/"),), viewports=DEFAULT_VIEWPORTS)
    with pytest.raises(FileNotFoundError, match="hydrogen tree not found"):
        run_playwright_smoke(
            hydrogen_dir=tmp_path / "missing",
            screenshots_dir=tmp_path / "screens",
            flow=flow,
            dev_server_factory=_stub_dev_server_factory,
            browser_driver=_RecordingBrowserDriver(),
        )


def test_run_playwright_smoke_propagates_dev_server_boot_failure(tmp_path: Path) -> None:
    """A dev-server boot failure surfaces to the caller."""
    out_dir = _materialise_m5_artifact(tmp_path)
    flow = resolve_smoke_flow(out_dir=out_dir)

    with pytest.raises(RuntimeError, match="pnpm dev refused to boot"):
        run_playwright_smoke(
            hydrogen_dir=out_dir / "hydrogen",
            screenshots_dir=out_dir / "screens",
            flow=flow,
            dev_server_factory=_exploding_dev_server_factory,
            browser_driver=_RecordingBrowserDriver(),
        )


# --------------------------------------------------------------------------- #
# Sanity — fixture preconditions
# --------------------------------------------------------------------------- #


def test_data_fixture_has_expected_first_handles() -> None:
    """Hardening: the M4 fixture's first handles match the expected smoke targets.

    If the fixture is regenerated this test surfaces the breakage early
    rather than letting :func:`resolve_smoke_flow`'s assertions fail.
    """
    products = json.loads((_DATA_FIXTURE_DIR / "products.json").read_text(encoding="utf-8"))
    collections = json.loads(
        (_DATA_FIXTURE_DIR / "collections.json").read_text(encoding="utf-8"),
    )
    assert products[0]["handle"] == _EXPECTED_FIRST_PRODUCT
    assert collections[0]["handle"] == _EXPECTED_FIRST_COLLECTION
