"""Orchestration: compose generators + manual sources into a full build.

The headline entry point is :func:`build` which takes a single shop and emits
every enabled benchmark for it. :func:`build_all` iterates across every shop
in a config file (default ``configs/featured_v1.yml``) and also processes
hand-authored source files.

Output layout
-------------

Benchmarks are written to one of two locations, or both:

- **Per-shop** (default): the shop's benchmark files land under the
  repo's shared ``outputs/`` tree at
  ``<repo>/outputs/shop_guru/<slug>/benchmarks/``, sibling to per-shop
  eval study directories. Each file contains only that shop's tasks.
  This is the authoritative location for per-shop artifacts and the
  path reviewers cite.

- **Flat mirror** (optional): every shop's tasks are merged into a single
  file per skill at a user-supplied path (e.g. ``outputs/benchmarks/``).
  This is the drop-in-replacement layout for the existing SimGym ShopGuru
  datasets — one file per skill, all shops combined.

The CLI enables per-shop by default; pass ``--flat-out PATH`` to also
emit the flat mirror. Pass ``--no-per-shop`` to skip per-shop writes.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shop_guru._paths import repo_root
from shop_guru.config import Shop, load_shops
from shop_guru.emit import emit_tasks
from shop_guru.generators import (
    collection_browse,
    collection_filter,
    e2e,
    exact_search,
    find_policy,
    substitute_search,
)
from shop_guru.io import load_json, load_shop_data
from shop_guru.validate import Issue, validate_tasks

GeneratorFn = Callable[..., list[dict]]


@dataclass(frozen=True)
class GeneratorSpec:
    """Config describing one automated task generator."""

    filename_stem: str
    fn: GeneratorFn
    kwargs: dict[str, Any]


def default_generators() -> list[GeneratorSpec]:
    """Return the ShopGuru v1 set of automated generators.

    Callers can extend or replace this list to produce custom benchmark
    suites.
    """
    return [
        GeneratorSpec(
            "ShopGuru_prod_discovery_exact_featured_v1",
            exact_search.generate,
            {"count": 5},
        ),
        GeneratorSpec(
            "ShopGuru_prod_discovery_substitute_featured_v1",
            substitute_search.generate,
            {"count": 5},
        ),
        GeneratorSpec(
            "ShopGuru_collection_browse_featured_v1",
            collection_browse.generate,
            {"count": 5},
        ),
        GeneratorSpec(
            "ShopGuru_collection_filter_featured_v1",
            collection_filter.generate,
            {"count": 3},
        ),
        GeneratorSpec(
            "ShopGuru_find_policy_shipping_featured_v1",
            find_policy.generate_shipping,
            {},
        ),
        GeneratorSpec(
            "ShopGuru_find_policy_returns_featured_v1",
            find_policy.generate_returns,
            {},
        ),
        GeneratorSpec(
            "ShopGuru_e2e_featured_v1",
            e2e.generate,
            {"count": 16},
        ),
    ]


# Maps a data_sources/<name>.json file to the emitted benchmark filename stem.
DEFAULT_MANUAL_SOURCES: dict[str, str] = {
    "smoke_test": "ShopGuru_smoke_test_featured_v1",
    "e2e_v1": "ShopGuru_e2e_featured_v1",
}


def per_shop_out_dir(shop: Shop) -> Path:
    """Return the canonical per-shop benchmark output directory.

    This is ``<repo>/outputs/shop_guru/<slug>/benchmarks/``, sibling
    to per-shop eval study dirs at ``outputs/shop_guru/<slug>/``.
    """
    return repo_root() / "outputs" / "shop_guru" / shop.slug / "benchmarks"


def build(
    shop: Shop,
    data: dict[str, Any],
    out_dirs: Sequence[str | Path],
    generators: Sequence[GeneratorSpec] | None = None,
    logger: Callable[[str], None] | None = None,
) -> None:
    """Run every generator in ``generators`` for a single ``shop``.

    Args:
        shop: The shop to generate for.
        data: Result of :func:`shop_guru.io.load_shop_data`.
        out_dirs: One or more directories to write benchmark JSONs into.
            Each directory receives an independent copy of the emitted
            tasks (the flat mirror will accumulate tasks from multiple
            shops across calls).
        generators: Custom generator list. Defaults to
            :func:`default_generators`.
        logger: Optional status-line callback. Defaults to ``print``.
    """
    log = logger or print
    dirs = [Path(d) for d in out_dirs if d is not None]
    if not dirs:
        raise ValueError("build() requires at least one output directory")

    for spec in generators or default_generators():
        tasks = spec.fn(shop, data, **spec.kwargs)
        if not tasks:
            log(f"  [skip] {spec.filename_stem} (no tasks generated)")
            continue
        written_names: list[str] = []
        for out_dir in dirs:
            written = emit_tasks(tasks, shop, out_dir, spec.filename_stem)
            written_names.extend(p.name for p in written)
        log(
            f"  [ok]  {spec.filename_stem} ({len(tasks)} tasks) \u2192 "
            f"{', '.join(sorted(set(written_names)))}"
        )


def build_all(
    config: str | Path,
    *,
    flat_out: str | Path | None = None,
    skip_per_shop: bool = False,
    shop_filter: str | None = None,
    skip_auto: bool = False,
    skip_manual: bool = False,
    data_sources_dir: str | Path | None = None,
    manual_sources: dict[str, str] | None = None,
    generators: Sequence[GeneratorSpec] | None = None,
    validate: bool = True,
    logger: Callable[[str], None] | None = None,
) -> list[Issue]:
    """Build every benchmark file for every shop in ``config``.

    Args:
        config: Path to a shops YAML config (e.g. ``configs/featured_v1.yml``).
        flat_out: Optional directory to additionally write a flat,
            all-shops-merged mirror into. Enables the drop-in-replacement
            SimGym layout.
        skip_per_shop: If True, do not write to the default per-shop
            location. Requires ``flat_out`` to be set.
        shop_filter: If set, only build the shop with this slug.
        skip_auto: Skip automated generators.
        skip_manual: Skip hand-authored data sources.
        data_sources_dir: Directory containing hand-authored source JSONs.
        manual_sources: Override the default ``{source_stem: out_stem}`` map.
        generators: Override the default generator list.
        validate: Run :mod:`shop_guru.validate` over every emitted benchmark
            file after generation. Logs each finding via ``logger``. Defaults
            to True.
        logger: Custom status-line callback.

    Returns:
        The aggregated list of :class:`shop_guru.validate.Issue` records
        produced by validation. Empty when ``validate=False`` or when no
        problems were detected.
    """
    log = logger or print

    if skip_per_shop and flat_out is None:
        raise ValueError(
            "skip_per_shop=True requires flat_out to be set; "
            "otherwise nothing would be written."
        )

    all_shops = load_shops(config)
    shops = [s for s in all_shops if shop_filter is None or s.slug == shop_filter]
    if not shops:
        raise SystemExit(f"No shops matched filter {shop_filter!r}")

    flat_out_path = Path(flat_out) if flat_out else None
    if flat_out_path is not None:
        flat_out_path.mkdir(parents=True, exist_ok=True)

    if not skip_auto:
        gens = generators if generators is not None else default_generators()

        for shop in shops:
            log(f"\n== [auto] {shop.slug} ({shop.name}) ==")
            data = load_shop_data(shop)
            out_dirs: list[Path] = []
            if not skip_per_shop:
                out_dirs.append(per_shop_out_dir(shop))
            if flat_out_path is not None:
                out_dirs.append(flat_out_path)
            build(shop, data, out_dirs, generators=gens, logger=log)

    if not skip_manual:
        sources_dir = Path(data_sources_dir) if data_sources_dir else None
        if sources_dir and sources_dir.exists():
            _emit_manual_sources(
                shops=shops,
                sources_dir=sources_dir,
                flat_out=flat_out_path,
                skip_per_shop=skip_per_shop,
                manual_sources=manual_sources or DEFAULT_MANUAL_SOURCES,
                shop_filter=shop_filter,
                logger=log,
            )

    if not validate:
        return []
    return validate_all(
        shops=shops,
        flat_out=flat_out_path,
        skip_per_shop=skip_per_shop,
        logger=log,
    )


def validate_all(
    shops: Sequence[Shop],
    *,
    flat_out: Path | None = None,
    skip_per_shop: bool = False,
    logger: Callable[[str], None] | None = None,
) -> list[Issue]:
    """Validate every benchmark file emitted for ``shops``.

    Reads JSON benchmark files from each shop's per-shop output directory
    (and/or ``flat_out``), groups tasks by shop, and runs
    :func:`shop_guru.validate.validate_tasks` against the matching shop's
    extracted data. Results are logged in stable, grouped order.

    Returns the flat list of all issues across shops (errors and warnings).
    """
    log = logger or print
    issues: list[Issue] = []
    by_slug = {s.slug: s for s in shops}
    data_cache: dict[str, dict[str, Any]] = {}

    log("\n== [validate] benchmark consistency ==")

    for shop in shops:
        shop_files: list[Path] = []
        if not skip_per_shop:
            per_dir = per_shop_out_dir(shop)
            if per_dir.exists():
                shop_files.extend(sorted(per_dir.glob("*.json")))
        # Group tasks from the flat mirror by shop_slug below; here we only
        # collect files that belong to a single shop.
        shop_issues = _validate_shop_files(shop, shop_files, data_cache)
        for issue in shop_issues:
            log(f"  {issue}")
        issues.extend(shop_issues)

    if flat_out is not None and flat_out.exists():
        flat_issues = _validate_flat_out(flat_out, by_slug, data_cache)
        for issue in flat_issues:
            log(f"  {issue}")
        issues.extend(flat_issues)

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    log(
        f"\nvalidation: {len(errors)} error(s), {len(warnings)} warning(s) "
        f"across {len(shops)} shop(s)"
    )
    return issues


def _validate_shop_files(
    shop: Shop,
    files: Sequence[Path],
    data_cache: dict[str, dict[str, Any]],
) -> list[Issue]:
    if not files:
        return []
    data = data_cache.get(shop.slug)
    if data is None:
        data = load_shop_data(shop)
        data_cache[shop.slug] = data

    issues: list[Issue] = []
    for path in files:
        try:
            tasks = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(tasks, list):
            continue
        for issue in validate_tasks(tasks, shop, data):
            issues.append(
                Issue(
                    rule=issue.rule,
                    severity=issue.severity,
                    task_id=f"{path.name}:{issue.task_id}",
                    message=issue.message,
                )
            )
    return issues


def _validate_flat_out(
    flat_out: Path,
    by_slug: dict[str, Shop],
    data_cache: dict[str, dict[str, Any]],
) -> list[Issue]:
    issues: list[Issue] = []
    for path in sorted(flat_out.glob("*.json")):
        try:
            tasks = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(tasks, list):
            continue
        grouped: dict[str, list[dict]] = {}
        for task in tasks:
            tid = str(task.get("id") or "")
            slug = tid.split("-", 1)[0]
            if slug in by_slug:
                grouped.setdefault(slug, []).append(task)
        for slug, shop_tasks in grouped.items():
            shop = by_slug[slug]
            data = data_cache.get(slug)
            if data is None:
                data = load_shop_data(shop)
                data_cache[slug] = data
            for issue in validate_tasks(shop_tasks, shop, data):
                issues.append(
                    Issue(
                        rule=issue.rule,
                        severity=issue.severity,
                        task_id=f"{path.name}:{issue.task_id}",
                        message=issue.message,
                    )
                )
    return issues


def _emit_manual_sources(
    *,
    shops: list[Shop],
    sources_dir: Path,
    flat_out: Path | None,
    skip_per_shop: bool,
    manual_sources: dict[str, str],
    shop_filter: str | None,
    logger: Callable[[str], None],
) -> None:
    by_slug = {s.slug: s for s in shops}

    for source_stem, out_stem in manual_sources.items():
        source_path = sources_dir / f"{source_stem}.json"
        if not source_path.exists():
            continue
        with source_path.open() as fh:
            all_tasks: list[dict] = json.load(fh)

        grouped: dict[str, list[dict]] = {}
        for task in all_tasks:
            slug = task.pop("shop_slug", None)
            if not slug:
                raise ValueError(
                    f"{source_path.name}: task {task.get('id', '?')} is missing `shop_slug`"
                )
            if shop_filter and slug != shop_filter:
                continue
            if slug not in by_slug:
                raise ValueError(
                    f"{source_path.name}: task {task.get('id', '?')} references unknown "
                    f"shop_slug {slug!r}"
                )
            grouped.setdefault(slug, []).append(task)

        if not grouped:
            continue

        logger(f"\n== [manual] {source_path.name} \u2192 {out_stem} ==")
        for slug, shop_tasks in grouped.items():
            shop = by_slug[slug]
            written_names: list[str] = []
            if not skip_per_shop:
                out_dir = per_shop_out_dir(shop)
                for p in emit_tasks(shop_tasks, shop, out_dir, out_stem):
                    written_names.append(p.name)
            if flat_out is not None:
                for p in emit_tasks(shop_tasks, shop, flat_out, out_stem):
                    written_names.append(p.name)
            logger(
                f"  [ok]  {shop.slug}: {len(shop_tasks)} tasks \u2192 "
                f"{', '.join(sorted(set(written_names)))}"
            )
