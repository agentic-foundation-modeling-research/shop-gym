"""Write generated tasks to disk as a single per-skill JSON file."""
from __future__ import annotations

import json
from pathlib import Path

from shop_guru.config import Shop
from shop_guru.io import load_json


def make_id(shop_slug: str, skill_slug: str, index: int) -> str:
    """Canonical task ID. Keeps IDs stable across regenerations."""
    return f"{shop_slug}-{skill_slug}-{index}"


def emit_tasks(
    tasks: list[dict],
    shop: Shop,
    out_dir: str | Path,
    filename_stem: str,
) -> list[Path]:
    """Write a single ``{filename_stem}.json`` benchmark file.

    Each task dict is expected to have an ``id`` and no ``url`` field; the
    ``url`` is attached from :attr:`Shop.shop_url`.

    Tasks are merged with any existing file contents by task ID, keeping the
    incoming task when IDs collide. This makes ``emit_tasks`` safe to call per
    shop without overwriting other shops' tasks in the same file.

    Returns a list with the single path that was written.
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    enriched = [dict(t, url=shop.shop_url) for t in tasks]
    target = out_path / f"{filename_stem}.json"
    _merge_and_write(target, enriched)
    return [target]


def _merge_and_write(path: Path, new_tasks: list[dict]) -> None:
    """Merge ``new_tasks`` into ``path`` by id, then sort and rewrite.

    Task order is deterministic (sorted by id) so diffs stay minimal across
    regenerations.
    """
    existing: list[dict] = []
    if path.exists():
        try:
            existing = load_json(path)
        except (json.JSONDecodeError, OSError):
            # Corrupt/partial file: start fresh rather than crash. The new
            # tasks supersede anything that was there.
            existing = []

    by_id: dict[str, dict] = {t["id"]: t for t in existing if "id" in t}
    for t in new_tasks:
        if "id" not in t:
            raise ValueError(f"Task missing 'id': {t!r}")
        by_id[t["id"]] = t

    merged = sorted(by_id.values(), key=lambda t: t["id"])
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
