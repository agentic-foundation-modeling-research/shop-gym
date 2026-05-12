"""Anonymization regression scan over the M2 fixture (T3.4 / SC3).

Spec reference: ``docs/specs/shop_arena/shop_arena.explore.md`` §4.2 SC3 — the
synthesized ``manual.md`` and ``capabilities.json`` must contain no
occurrence of the source domain, source store name, or any product
title from prefetched ``products.json``.

This test seeds a run_dir from the hand-crafted ``fixture_drawer_shop``
cassette (the only fixture available at the M2/M3 milestone) but
augments the seeded ``prefetch/products.json`` with 20 distinctive,
brand-specific product titles and a brand-specific domain / store name
so a leak would actually be detectable. The cassette parts themselves
are anonymized; the LLM stub returns a manual body that mirrors the
parts content. The regex scan then asserts that none of the leak
markers appear in either published artifact.

Two tests live here:

* The positive case proves the M2 fixture survives the scan clean
  (``SC3`` satisfied on the fixture).
* The negative case forces a leak in the LLM response and asserts the
  same scan flags it — guarding against a future false-negative scanner.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from shop_arena.explore.synthesize import synthesize

_CASSETTE_DIR = Path(__file__).resolve().parent.parent / "cassettes" / "fixture_drawer_shop"
_FINAL_ITER_DIR = _CASSETTE_DIR / "exec-0004"
_TASK_IDS: tuple[str, ...] = (
    "homepage_sections",
    "cart_drawer",
    "search_predictive",
    "collection_filters",
)
_MANUAL_PROMPT = "Merge the per-task notes into one anonymized Shop Manual."

# Distinctive brand-specific markers that must not leak into the
# published artifacts. Constructed to be unmistakable strings (no
# generic English words) so the regex scan has zero false positives.
_SOURCE_DOMAIN = "brand-leakcanary.example.com"
_SOURCE_STORE_NAME = "Brand Leakcanary"
_LEAK_PRODUCT_TITLES: tuple[str, ...] = tuple(
    f"LeakCanary{i:02d}-Brutalist-Vase-Limited-Edition" for i in range(20)
)

# An anonymized manual body; long enough to clear ``MANUAL_MIN_CHARS``
# and free of any leak markers above. Mirrors the shape the merge
# prompt asks the LLM to produce.
_CLEAN_MANUAL_BODY = (
    "# Shop Manual\n\n"
    "## Site shell\n\n"
    "The storefront uses a horizontal header with a two-column mega menu, "
    "a fixed announcement bar, and a four-group footer with a newsletter "
    "form.\n\n"
    "## Homepage\n\n"
    "Five sections in order: hero carousel, featured collection grid, "
    "promotional banner, testimonials, newsletter sign-up. A first-visit "
    "popup advertises the newsletter.\n\n"
    "## Cart\n\n"
    "Slide-in drawer anchored to the right edge with empty / filled / "
    "quantity-change states, promo-code input, and an upsell row. "
    "Shipping is estimated only on the dedicated cart page.\n\n"
    "## Search\n\n"
    "Predictive search opens from a header icon and surfaces product and "
    "collection suggestions; the results layout is a grid with filters.\n\n"
    "## Collection\n\n"
    "Four-column grid with size, color, and price filters and "
    "featured / price / newest sort options. Pagination is load-more.\n"
)


def _seed_run_dir(tmp_path: Path) -> Path:
    """Build a populated ``run_dir`` from the M2 cassette + leak-bait prefetch.

    Mirrors :func:`tests.explore.test_synthesize._seed_run_dir`
    but seeds ``prefetch/products.json`` with 20 brand-specific titles
    and uses a brand-specific ``run_dir.parent.name`` so the regex scan
    has real strings to look for.
    """
    domain_dir = tmp_path / _SOURCE_DOMAIN
    run_dir = domain_dir / "20251024T120000Z-deadbeef"
    artifact_dir = run_dir / "artifact"
    parts_dir = artifact_dir / "parts"
    prefetch_dir = artifact_dir / "prefetch"
    parts_dir.mkdir(parents=True)
    prefetch_dir.mkdir(parents=True)

    for task_id, exec_dir in zip(
        _TASK_IDS,
        ("exec-0001", "exec-0002", "exec-0003", "exec-0004"),
        strict=True,
    ):
        src_parts = _CASSETTE_DIR / exec_dir / "workspace_after" / "artifact" / "parts"
        shutil.copy2(src_parts / f"{task_id}.md", parts_dir / f"{task_id}.md")
        shutil.copy2(src_parts / f"{task_id}.caps.json", parts_dir / f"{task_id}.caps.json")

    shutil.copy2(_FINAL_ITER_DIR / "workspace_after" / "plan.md", run_dir / "plan.md")

    products = [
        {
            "id": idx,
            "title": title,
            "options": [{"name": "Size"}],
            "variants": [{"id": idx * 10, "price": "12.00"}],
        }
        for idx, title in enumerate(_LEAK_PRODUCT_TITLES, start=1)
    ]
    (prefetch_dir / "products.json").write_text(
        json.dumps({"products": products}), encoding="utf-8"
    )
    (prefetch_dir / "collections.json").write_text(
        json.dumps({"collections": []}), encoding="utf-8"
    )
    (prefetch_dir / "cart.js").write_text(
        json.dumps({"items": [], "currency": "USD"}), encoding="utf-8"
    )
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "final_status": "completed",
                "plan_iter_count": 1,
                "exec_iter_count": 4,
                "trajectory_paths": [],
                "tasks_final": [],
                "config_snapshot": {"runtime": "pi"},
                "runtime": "pi",
            }
        ),
        encoding="utf-8",
    )
    return run_dir


class _StubLLM:
    """Returns a fixed completion verbatim, recording the prompt."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._response


def _leak_markers() -> tuple[str, ...]:
    """Strings that must not appear in published artifacts."""
    return (_SOURCE_DOMAIN, _SOURCE_STORE_NAME, *_LEAK_PRODUCT_TITLES)


def _scan_for_leaks(text: str) -> list[str]:
    """Return every leak marker that appears in ``text`` (case-insensitive)."""
    found: list[str] = []
    for marker in _leak_markers():
        if re.search(re.escape(marker), text, flags=re.IGNORECASE):
            found.append(marker)
    return found


def test_synthesized_artifacts_contain_no_leaks_on_m2_fixture(tmp_path: Path) -> None:
    """SC3: the M2 fixture survives a regex anonymization scan clean."""
    run_dir = _seed_run_dir(tmp_path)
    llm = _StubLLM(_CLEAN_MANUAL_BODY)

    result = synthesize(run_dir, llm=llm, manual_prompt=_MANUAL_PROMPT)

    manual_text = result.manual_path.read_text(encoding="utf-8")
    capabilities_text = result.capabilities_path.read_text(encoding="utf-8")

    manual_leaks = _scan_for_leaks(manual_text)
    capabilities_leaks = _scan_for_leaks(capabilities_text)

    assert manual_leaks == [], f"manual.md leaked: {manual_leaks}"
    assert capabilities_leaks == [], f"capabilities.json leaked: {capabilities_leaks}"


@pytest.mark.parametrize(
    "leaked_marker",
    [
        _SOURCE_DOMAIN,
        _SOURCE_STORE_NAME,
        _LEAK_PRODUCT_TITLES[0],
        _LEAK_PRODUCT_TITLES[19],
    ],
)
def test_anonymization_scan_detects_leaks_when_present(tmp_path: Path, leaked_marker: str) -> None:
    """Negative control: forcing a leak into the LLM body trips the scan.

    Guards against a silently-disabled regex / future anonymizer
    refactor that turns the positive test into a vacuous pass.
    """
    run_dir = _seed_run_dir(tmp_path)
    leaked_body = _CLEAN_MANUAL_BODY + f"\n\nSold exclusively at {leaked_marker}.\n"
    llm = _StubLLM(leaked_body)

    result = synthesize(run_dir, llm=llm, manual_prompt=_MANUAL_PROMPT)

    manual_leaks = _scan_for_leaks(result.manual_path.read_text(encoding="utf-8"))
    assert leaked_marker in manual_leaks
