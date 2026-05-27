"""Load ShopGuru benchmark task dicts from the bundled per-shop JSON files.

Walks ``<benchmarks_root>/<shop.slug>/benchmarks/`` for files matching
``ShopGuru_<skill>_<config_stem>.json`` and applies optional
shop / skill / task-id filters. The returned list is a flat sequence of
task dicts ready to feed into ``register_shopguru_tasks``.

The loader is path-agnostic on purpose — callers (``run.py``,
``rejudge.py``, tests) own anchoring and pass ``benchmarks_root``
explicitly. Keeps this module free of ``__file__`` magic.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from shop_guru.config import Shop, load_shops

logger = logging.getLogger(__name__)

BENCH_PREFIX = "ShopGuru_"


def _benchmark_dir(benchmarks_root: Path, shop: Shop) -> Path:
    return Path(benchmarks_root) / shop.slug / "benchmarks"


def _bench_pattern(config_stem: str) -> re.Pattern[str]:
    # Matches e.g. ShopGuru_prod_discovery_exact_default.json →
    # captures "prod_discovery_exact" as skill.
    return re.compile(
        rf"^{re.escape(BENCH_PREFIX)}(?P<skill>.+)_{re.escape(config_stem)}\.json$"
    )


def _iter_shop_benchmarks(
    benchmarks_root: Path,
    shop: Shop,
    config_stem: str,
    skill_filter: set[str] | None,
) -> list[tuple[str, Path]]:
    """Return ``[(skill, path), ...]`` for every benchmark file of this shop."""
    bench_dir = _benchmark_dir(benchmarks_root, shop)
    if not bench_dir.is_dir():
        logger.warning("no benchmarks dir for shop %s at %s", shop.slug, bench_dir)
        return []

    pattern = _bench_pattern(config_stem)
    out: list[tuple[str, Path]] = []
    for entry in sorted(bench_dir.iterdir()):
        if not entry.is_file():
            continue
        match = pattern.match(entry.name)
        if not match:
            continue
        skill = match.group("skill")
        if skill_filter is not None and skill not in skill_filter:
            continue
        out.append((skill, entry))
    return out


def load_shopguru_tasks(
    config_path: Path,
    benchmarks_root: Path,
    shops: list[str] | None = None,
    skills: list[str] | None = None,
    task_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Load + filter every ShopGuru task across the featured shops.

    Args:
        config_path: Path to a shops YAML (e.g. ``configs/default.yaml``).
        benchmarks_root: Directory containing ``<shop.slug>/ShopGuru_*.json``.
            Required — callers anchor this (typically
            ``<repo>/outputs/shop_guru``) and pass it in.
        shops: Optional allow-list of shop slugs.
        skills: Optional allow-list of skill names (file stem pieces like
            ``"e2e"``, ``"prod_discovery_exact"``, ``"find_policy_shipping"``).
        task_ids: Optional allow-list of specific task ids to keep.

    Returns:
        A list of task dicts with keys ``id``, ``intent``, ``url``,
        ``type``, optional ``success_criteria``, plus the injected
        ``shop_slug`` and ``skill`` fields for downstream bookkeeping.
    """
    config_path = Path(config_path).resolve()
    benchmarks_root = Path(benchmarks_root).resolve()
    config_stem = config_path.stem  # e.g. "default"

    all_shops = load_shops(config_path)
    shop_filter = set(shops) if shops else None
    skill_filter = set(skills) if skills else None
    id_filter = set(task_ids) if task_ids else None

    picked_shops = [s for s in all_shops if shop_filter is None or s.slug in shop_filter]
    if not picked_shops:
        raise ValueError(
            f"no shops matched filter {shops!r}; available: "
            + ", ".join(s.slug for s in all_shops)
        )

    tasks: list[dict[str, Any]] = []
    for shop in picked_shops:
        for skill, path in _iter_shop_benchmarks(
            benchmarks_root, shop, config_stem, skill_filter
        ):
            raw = json.loads(path.read_text())
            if not isinstance(raw, list):
                logger.warning("benchmark file is not a list: %s", path)
                continue
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                if id_filter is not None and entry.get("id") not in id_filter:
                    continue
                enriched = dict(entry)
                enriched.setdefault("shop_slug", shop.slug)
                enriched.setdefault("skill", skill)
                tasks.append(enriched)

    # Stable order: shop slug → skill → id — makes the gym task list
    # deterministic across runs and matches the CLI listing the user sees.
    tasks.sort(
        key=lambda t: (t.get("shop_slug", ""), t.get("skill", ""), t.get("id", ""))
    )

    if id_filter is not None:
        missing = id_filter - {t.get("id") for t in tasks}
        if missing:
            raise ValueError(
                f"requested task ids were not found: {sorted(missing)}"
            )

    return tasks
