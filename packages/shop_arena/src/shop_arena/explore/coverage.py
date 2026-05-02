"""Deterministic SC5 coverage check for ``shop_arena.explore`` (T4.4).

Implements the test-side gate for spec §4.2 success criterion SC5:

> On the fixture set, every coverage-taxonomy area that prefetch
> evidence indicates is present (§5.3) appears as either a planner task
> or a justified omission in ``manifest.json``.

The check is deterministic — no LLM, no network. It compares two
sets derived from a finished ``run_dir``:

* **Evidenced areas.** Coverage-taxonomy leaves (or evidence-grouped
  bundles, e.g. all ``product_*`` areas) that the §5.9 prefetch step
  successfully confirmed are present on the storefront. Conservative by
  design: only areas that ``prefetch/`` can definitively prove are
  flagged. Areas that require browser interaction (mega menu,
  announcement bar, locale switcher, floating widgets) are intentionally
  out of scope here — prefetch can neither confirm nor deny them, so
  flagging them would force every plan to omit them by default.
* **Covered areas.** Areas that the planner addressed by emitting a
  task in ``plan.md`` *or* listing under ``## Omitted Areas``. Covers
  both the canonical ``shop_arena.explore`` task ids (per ``planner.md``
  "Suggested task ids") and the §5.3 taxonomy labels.

A *gap* is an evidenced area with no task and no omission. SC5 is
satisfied iff :func:`coverage_gaps` returns an empty list.

This module is **not** part of the public ``shop_arena.explore`` surface
(spec §8.1). It is consumed by tests and by the M4 live-fixture gate
(T4.5). Keeping it test-side mirrors the anonymization scan in T3.4.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True)
class Area:
    """One coverage-taxonomy entry the SC5 gate can verify.

    Attributes:
        name: Canonical area name. Also accepted verbatim as the
            ``area`` slug under ``## Omitted Areas`` and as a plan
            ``task_id``.
        task_ids: Plan task ids whose presence under ``## Tasks`` counts
            as covering this area. Each id matches the
            ``planner.md`` "Suggested task ids" list.
        omission_aliases: Additional slugs accepted as the ``area``
            field of an ``## Omitted Areas`` entry. Lets planners use
            either the area-level name or a parent taxonomy label
            (e.g. ``info_pages`` covers all ``info_*`` leaves).
    """

    name: str
    task_ids: tuple[str, ...]
    omission_aliases: tuple[str, ...] = ()


# Areas whose presence is definitively confirmed by the §5.9 prefetch
# fetch plan. Order is informative; the check itself uses set membership.
#
# Spec §5.3 ("Coverage taxonomy") lists every leaf the planner is
# expected to consider. Many of those leaves require browser interaction
# to confirm (mega menu, locale switcher, age gate, …) and therefore
# *cannot* be evidenced by prefetch alone — they are deliberately absent
# from this list. Adding a leaf here would require a corresponding
# addition to :func:`evidenced_areas` so the evidence rule is auditable.
_AREAS: tuple[Area, ...] = (
    Area(
        name="homepage_sections",
        task_ids=("homepage_sections",),
        omission_aliases=("homepage", "hero", "sections", "newsletter", "popups"),
    ),
    Area(
        name="header_navigation",
        task_ids=("header_navigation", "homepage_sections"),
        omission_aliases=("site_shell", "header"),
    ),
    Area(
        name="footer",
        task_ids=("footer", "homepage_sections"),
        omission_aliases=("site_shell",),
    ),
    Area(
        name="cart",
        task_ids=("cart_drawer", "cart_page"),
        omission_aliases=("cart_drawer_or_page",),
    ),
    Area(
        name="search_predictive",
        task_ids=("search_predictive",),
        omission_aliases=("predictive",),
    ),
    Area(
        name="search_results",
        task_ids=("search_results", "search_predictive"),
        omission_aliases=("results_layout", "search"),
    ),
    Area(
        name="product_detail",
        task_ids=(
            "product_variants",
            "product_gallery",
            "product_extras",
            "product_detail",
        ),
        omission_aliases=("product", "gallery", "variant_selectors"),
    ),
    Area(
        name="collection",
        task_ids=(
            "collection_filters",
            "collection_layout",
            "collection_listing",
        ),
        omission_aliases=(
            "collection_listing",
            "filters",
            "sort",
            "pagination",
            "listing_layout",
        ),
    ),
    Area(
        name="info_about",
        task_ids=("info_pages",),
        omission_aliases=("about", "info_pages"),
    ),
    Area(
        name="info_contact",
        task_ids=("info_pages",),
        omission_aliases=("contact", "info_pages"),
    ),
    Area(
        name="info_faq",
        task_ids=("info_pages",),
        omission_aliases=("faq", "info_pages"),
    ),
    Area(
        name="info_shipping",
        task_ids=("info_pages",),
        omission_aliases=("shipping", "shipping_policy", "info_pages"),
    ),
    Area(
        name="info_returns",
        task_ids=("info_pages",),
        omission_aliases=("returns", "returns_policy", "refund_policy", "info_pages"),
    ),
    Area(
        name="info_privacy",
        task_ids=("info_pages",),
        omission_aliases=("privacy", "privacy_policy", "info_pages"),
    ),
    Area(
        name="info_tos",
        task_ids=("info_pages",),
        omission_aliases=("tos", "terms_of_service", "info_pages"),
    ),
)
"""Closed list of areas the SC5 gate verifies. See module docstring."""


_INFO_FILES: dict[str, str] = {
    "pages/about.html": "info_about",
    "pages/contact.html": "info_contact",
    "pages/faq.html": "info_faq",
    "policies/shipping-policy.html": "info_shipping",
    "policies/refund-policy.html": "info_returns",
    "policies/privacy-policy.html": "info_privacy",
    "policies/terms-of-service.html": "info_tos",
}
"""Maps prefetch-relative info-page filenames to evidenced area names."""


def evidenced_areas(prefetch_dir: Path) -> set[str]:
    """Return the set of taxonomy areas confirmed present by prefetch.

    Reads the saved-file layout under ``prefetch_dir`` (the
    :func:`shop_arena.explore.prefetch.run` output). A file's existence is
    sufficient evidence: prefetch only writes a file on a 200 response
    with a non-empty body, so missing files mean either the storefront
    returned an error, the endpoint does not exist, or the body was
    empty — none of which counts as "present".

    Args:
        prefetch_dir: Directory containing the prefetch output, i.e.
            the ``artifact/prefetch/`` tree of a finished run.

    Returns:
        Set of canonical area names. Empty when the prefetch directory
        is missing or empty.
    """
    if not prefetch_dir.is_dir():
        return set()

    found: set[str] = set()

    if (prefetch_dir / "index.html").is_file():
        found.update({"homepage_sections", "header_navigation", "footer"})

    if (prefetch_dir / "cart.js").is_file() or (prefetch_dir / "cart.html").is_file():
        found.add("cart")

    if (prefetch_dir / "search_suggest.json").is_file():
        found.add("search_predictive")

    if (prefetch_dir / "search.html").is_file():
        found.add("search_results")

    if _has_nonempty_collection(prefetch_dir / "products.json", "products"):
        found.add("product_detail")

    if _has_nonempty_collection(prefetch_dir / "collections.json", "collections"):
        found.add("collection")

    for relative, area in _INFO_FILES.items():
        if (prefetch_dir / relative).is_file():
            found.add(area)

    return found


def parse_plan_coverage(plan_md: str) -> tuple[set[str], set[str]]:
    """Extract task ids and omitted-area slugs from a ``plan.md``.

    Mirrors the lightweight parsing done by
    :func:`shop_arena.explore.synthesize.manifest._count_plan_tasks` and
    :func:`shop_arena.explore.synthesize.manifest._parse_omitted_areas`, but
    returns raw slug sets rather than counts / records.

    Args:
        plan_md: Contents of ``plan.md``. May be empty.

    Returns:
        ``(task_ids, omitted_area_slugs)``: snake_case slugs as written.
        Slugs are not normalized beyond stripping whitespace.
    """
    return _parse_task_ids(plan_md), _parse_omitted_slugs(plan_md)


def coverage_gaps(run_dir: Path) -> list[str]:
    """Return evidenced areas not covered by tasks or omissions.

    SC5 is satisfied iff this function returns an empty list. The
    return value is sorted for stable test failure messages.

    Args:
        run_dir: Finished ShopExplore ``run_dir`` (the harness work
            directory). Must contain ``plan.md`` and
            ``artifact/prefetch/``.

    Returns:
        Sorted list of canonical area names that are evidenced by
        prefetch but neither addressed by a planner task nor listed
        under ``## Omitted Areas``. Empty list ⇒ SC5 satisfied.
    """
    prefetch_dir = run_dir / "artifact" / "prefetch"
    plan_md_path = run_dir / "plan.md"
    plan_md = plan_md_path.read_text(encoding="utf-8") if plan_md_path.is_file() else ""

    evidenced = evidenced_areas(prefetch_dir)
    task_ids, omitted = parse_plan_coverage(plan_md)

    gaps: list[str] = []
    for area in _AREAS:
        if area.name not in evidenced:
            continue
        if _is_covered(area, task_ids=task_ids, omitted=omitted):
            continue
        gaps.append(area.name)
    return sorted(gaps)


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _is_covered(area: Area, *, task_ids: set[str], omitted: set[str]) -> bool:
    """Decide whether ``area`` is addressed by tasks or omissions."""
    if area.name in task_ids:
        return True
    if any(tid in task_ids for tid in area.task_ids):
        return True
    if area.name in omitted:
        return True
    return any(alias in omitted for alias in area.omission_aliases)


def _has_nonempty_collection(path: Path, key: str) -> bool:
    """Return ``True`` iff ``path`` is a JSON object with a non-empty list at ``key``."""
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    items = cast(dict[str, Any], payload).get(key)
    return isinstance(items, list) and len(cast(list[Any], items)) > 0


def _parse_task_ids(plan_md: str) -> set[str]:
    """Return the set of ``task_id`` slugs under the ``## Tasks`` heading."""
    ids: set[str] = set()
    in_tasks = False
    for line in plan_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_tasks = stripped.lower().startswith("## tasks")
            continue
        if not in_tasks or not stripped.startswith("- ["):
            continue
        # Form: "- [ ] <task_id> — …"  (also tolerate "- [x]" / "- [!]")
        rest = stripped[3:]  # drop "- ["
        close = rest.find("]")
        if close < 0:
            continue
        rest = rest[close + 1 :].lstrip()
        token, _, _ = rest.partition(" ")
        token = token.strip()
        if token:
            ids.add(token)
    return ids


def _parse_omitted_slugs(plan_md: str) -> set[str]:
    """Return the set of ``area`` slugs under the ``## Omitted Areas`` heading."""
    slugs: set[str] = set()
    in_block = False
    for line in plan_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_block = stripped.lower().startswith("## omitted")
            continue
        if not in_block or not stripped.startswith("- "):
            continue
        body = stripped[2:].strip()
        if " — " in body:
            slug, _, _ = body.partition(" — ")
        elif " - " in body:
            slug, _, _ = body.partition(" - ")
        else:
            slug = body
        slug = slug.strip()
        if slug:
            slugs.add(slug)
    return slugs
