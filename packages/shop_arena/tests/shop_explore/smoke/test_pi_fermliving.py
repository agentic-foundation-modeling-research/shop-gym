"""Live e2e validation against ``https://fermliving.com`` (T4.5).

This is the **M4 manual milestone gate**, not a recurring CI test.
It runs the full :func:`shop_explore.explore` pipeline against the
live Ferm Living storefront with the real ``pi`` runtime and verifies
the seven assertions enumerated in
``docs/impl/shop_explore_implementation.md`` §T4.5:

1. ``prefetch/`` populates the seven canonical artefacts, none flagged
   as bot-blocked.
2. ``plan.md`` covers the documented feature set of the storefront
   (homepage_sections, header_navigation, collection_filters,
   product_variants, cart_drawer, search_predictive, info_pages).
3. Harness ``final_status == completed``; ≥ 80 % of planner-emitted
   tasks reach :class:`TaskStatus.DONE`.
4. ``capabilities.json`` validates and reports the spec-required
   feature-rich sentinels (cart drawer, predictive search, mega menu,
   locale switcher, non-empty filters/sort).
5. ``stats.json`` reports ``products_total >= 50`` and a non-empty
   ``variant_axes_observed``.
6. ``manual.md`` is ≥ 1500 chars and the anonymization regex scan
   (mirroring T3.4) finds zero leaks of the brand, source domain, or
   any of the first 20 product titles from prefetch.
7. ≥ 1 full-page screenshot per executor task under
   ``evidence/<task_id>/screenshots/``.

The test is gated behind ``SHOP_EXPLORE_LIVE_FERMLIVING=1`` and skipped
in CI; intended as a manual milestone gate, not a recurring CI job.

When run, captured artefacts are written to
``tests/shop_explore/fixtures/fermliving_live/`` (committed for
diff-reviewable regression tracking) when ``SHOP_EXPLORE_LIVE_PERSIST=1``
is also set; otherwise the run uses a tmp dir and is discarded.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from harness.config import FinalStatus
from harness.plan_parser import parse as parse_plan
from harness.types import TaskStatus
from shop_explore import Capabilities, ExploreConfig, Stats, explore

_GATE_ENV_VAR = "SHOP_EXPLORE_LIVE_FERMLIVING"
_PERSIST_ENV_VAR = "SHOP_EXPLORE_LIVE_PERSIST"

_LIVE_URL = "https://fermliving.com"
_LIVE_TIMEOUT_SECONDS = 1800.0
_LIVE_MAX_ITERS = 24

_SCREENSHOT_SUFFIXES: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp"})

# Assertion 1 — canonical prefetch artefacts that must be populated.
_REQUIRED_PREFETCH_FILES: tuple[str, ...] = (
    "index.html",
    "sitemap.xml",
    "products.json",
    "collections.json",
    "cart.js",
)
# Assertion 1 — at least 4 of these policy / info pages must be saved.
_INFO_PAGE_CANDIDATES: tuple[str, ...] = (
    "policies/refund-policy.html",
    "policies/privacy-policy.html",
    "policies/terms-of-service.html",
    "policies/shipping-policy.html",
    "pages/about.html",
    "pages/contact.html",
    "pages/faq.html",
)
_INFO_PAGES_REQUIRED = 4

# Assertion 2 — plan task ids that must appear (or be plausibly aliased).
_REQUIRED_PLAN_TASK_IDS: tuple[str, ...] = (
    "homepage_sections",
    "header_navigation",
    "collection_filters",
    "product_variants",
    "cart_drawer",
    "search_predictive",
    "info_pages",
)

# Assertion 3 — at least 80 % of emitted tasks must end DONE.
_MIN_DONE_RATIO = 0.80

# Assertion 5 — minimum catalog size for a feature-rich Shopify shop.
_MIN_PRODUCTS_TOTAL = 50

# Assertion 6 — manual.md size floor.
_MANUAL_MIN_CHARS = 1500
# Assertion 6 — leak markers we forbid in manual.md / capabilities.json.
_BRAND_LEAK_MARKERS: tuple[str, ...] = (
    "fermliving",
    "ferm living",
    "fermliving.com",
)


@pytest.mark.smoke
@pytest.mark.skipif(
    os.environ.get(_GATE_ENV_VAR) != "1",
    reason=f"{_GATE_ENV_VAR}!=1; M4 manual gate skipped",
)
def test_shop_explore_live_fermliving(tmp_path: Path) -> None:
    """Drive the full pipeline live against ``https://fermliving.com``.

    See module docstring for the seven assertions enforced.
    """
    out_dir = _resolve_out_dir(tmp_path)

    config = ExploreConfig(
        url=_LIVE_URL,
        out_dir=out_dir,
        runtime="pi",
        max_iters=_LIVE_MAX_ITERS,
        timeout=_LIVE_TIMEOUT_SECONDS,
    )
    result = explore(config)

    artifact_dir = result.run_dir / "artifact"
    prefetch_dir = artifact_dir / "prefetch"
    evidence_root = artifact_dir / "evidence"

    # ─── Assertion 1: prefetch populated, no bot-block. ────────────────
    _assert_prefetch_complete(prefetch_dir)

    # ─── Assertion 2: plan covers the documented feature set. ──────────
    plan_md = (result.run_dir / "plan.md").read_text(encoding="utf-8")
    plan = parse_plan(plan_md)
    task_ids = [task.id for task in plan.tasks]
    assert task_ids, "plan.md emitted no tasks"

    plan_text_lower = plan_md.lower()
    missing_required = [
        required
        for required in _REQUIRED_PLAN_TASK_IDS
        if required not in task_ids and required not in plan_text_lower
    ]
    assert not missing_required, f"plan.md missing required coverage areas: {missing_required}"

    # ─── Assertion 3: harness completed; ≥ 80 % of tasks DONE. ─────────
    assert result.final_status is FinalStatus.COMPLETED, (
        f"harness final_status was {result.final_status!r}, expected COMPLETED"
    )
    done = sum(1 for task in plan.tasks if task.status is TaskStatus.DONE)
    ratio = done / len(plan.tasks)
    assert ratio >= _MIN_DONE_RATIO, (
        f"only {done}/{len(plan.tasks)} tasks DONE ({ratio:.0%}); floor is {_MIN_DONE_RATIO:.0%}"
    )

    # ─── Assertion 4: capabilities sentinels for a feature-rich shop. ──
    capabilities_payload = json.loads(result.capabilities_path.read_text(encoding="utf-8"))
    capabilities = Capabilities.model_validate(capabilities_payload)
    assert capabilities.cart.type == "drawer", (
        f"cart.type expected 'drawer', got {capabilities.cart.type!r}"
    )
    assert capabilities.search.has_predictive is True, (
        "search.has_predictive must be True for fermliving.com"
    )
    assert capabilities.site_shell.has_mega_menu is True, (
        "site_shell.has_mega_menu must be True for fermliving.com"
    )
    assert capabilities.intl.has_locale_switcher is True, (
        "intl.has_locale_switcher must be True for fermliving.com"
    )
    assert capabilities.collection.filters, (
        "collection.filters must be non-empty for fermliving.com"
    )
    assert capabilities.collection.sort, "collection.sort must be non-empty for fermliving.com"

    # ─── Assertion 5: stats reports a non-trivial catalog. ─────────────
    stats_payload = json.loads(result.stats_path.read_text(encoding="utf-8"))
    stats = Stats.model_validate(stats_payload)
    assert stats.products_total >= _MIN_PRODUCTS_TOTAL, (
        f"stats.products_total={stats.products_total}; "
        f"expected >= {_MIN_PRODUCTS_TOTAL} (truncated flag is acceptable)"
    )
    assert stats.variant_axes_observed, (
        "stats.variant_axes_observed must be non-empty for fermliving.com"
    )

    # ─── Assertion 6: manual size + anonymization scan. ────────────────
    manual_text = result.manual_path.read_text(encoding="utf-8")
    assert len(manual_text) >= _MANUAL_MIN_CHARS, (
        f"manual.md is {len(manual_text)} chars; floor is {_MANUAL_MIN_CHARS}"
    )

    leak_markers = _build_leak_markers(prefetch_dir)
    capabilities_text = result.capabilities_path.read_text(encoding="utf-8")
    manual_leaks = _scan_for_leaks(manual_text, leak_markers)
    capabilities_leaks = _scan_for_leaks(capabilities_text, leak_markers)
    assert manual_leaks == [], f"manual.md leaked: {manual_leaks}"
    assert capabilities_leaks == [], f"capabilities.json leaked: {capabilities_leaks}"

    # ─── Assertion 7: ≥ 1 screenshot per executor task. ────────────────
    missing_screenshots = [
        task_id for task_id in task_ids if not _has_screenshot(evidence_root / task_id)
    ]
    assert not missing_screenshots, (
        f"tasks missing ≥ 1 screenshot under evidence/: {missing_screenshots}"
    )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _resolve_out_dir(tmp_path: Path) -> Path:
    """Return the run output dir, persisting under fixtures/ when requested.

    When ``SHOP_EXPLORE_LIVE_PERSIST=1`` is set, the run is captured under
    ``tests/shop_explore/fixtures/fermliving_live/`` so the artifacts are
    diff-reviewable across regressions on the same shop. The destination
    is wiped first (live runs are not idempotent across timestamps).
    """
    if os.environ.get(_PERSIST_ENV_VAR) != "1":
        return tmp_path / "run"
    fixtures_root = Path(__file__).resolve().parents[1] / "fixtures" / "fermliving_live"
    if fixtures_root.exists():
        shutil.rmtree(fixtures_root)
    fixtures_root.mkdir(parents=True)
    return fixtures_root


def _assert_prefetch_complete(prefetch_dir: Path) -> None:
    """Enforce assertion 1: required artefacts present, no bot-block."""
    assert prefetch_dir.is_dir(), f"prefetch dir missing: {prefetch_dir}"
    missing = [
        name
        for name in _REQUIRED_PREFETCH_FILES
        if not (prefetch_dir / name).is_file() or (prefetch_dir / name).stat().st_size == 0
    ]
    assert not missing, f"prefetch missing required files: {missing}"

    info_present = sum(
        1
        for name in _INFO_PAGE_CANDIDATES
        if (prefetch_dir / name).is_file() and (prefetch_dir / name).stat().st_size > 0
    )
    assert info_present >= _INFO_PAGES_REQUIRED, (
        f"prefetch saved only {info_present} info/policy pages; need >= {_INFO_PAGES_REQUIRED}"
    )

    summary_path = prefetch_dir / "prefetch.json"
    assert summary_path.is_file(), "prefetch/prefetch.json missing"
    summary: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8"))
    entries = summary.get("entries") or []
    blocked = [
        entry for entry in entries if entry.get("error") in {"cloudflare_challenge", "bot_blocked"}
    ]
    assert not blocked, f"prefetch flagged bot-blocked entries: {blocked}"


def _build_leak_markers(prefetch_dir: Path) -> tuple[str, ...]:
    """Brand markers + first 20 product titles from prefetch products.json."""
    markers: list[str] = list(_BRAND_LEAK_MARKERS)
    products_path = prefetch_dir / "products.json"
    if not products_path.is_file():
        return tuple(markers)
    payload: dict[str, Any] = json.loads(products_path.read_text(encoding="utf-8"))
    products = payload.get("products")
    if not isinstance(products, list):
        return tuple(markers)
    titles = [
        product["title"]
        for product in products[:20]
        if isinstance(product, dict)
        and isinstance(product.get("title"), str)
        and product["title"].strip()
    ]
    markers.extend(titles)
    return tuple(markers)


def _scan_for_leaks(text: str, markers: tuple[str, ...]) -> list[str]:
    """Return every leak marker that appears in ``text`` (case-insensitive)."""
    found: list[str] = []
    for marker in markers:
        if re.search(re.escape(marker), text, flags=re.IGNORECASE):
            found.append(marker)
    return found


def _has_screenshot(task_evidence_dir: Path) -> bool:
    """Return ``True`` iff ``task_evidence_dir`` contains a screenshot file."""
    if not task_evidence_dir.is_dir():
        return False
    return any(_iter_image_files(task_evidence_dir))


def _iter_image_files(root: Path) -> Iterable[Path]:
    """Yield every file under ``root`` whose suffix is a known image type."""
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in _SCREENSHOT_SUFFIXES:
            yield path
