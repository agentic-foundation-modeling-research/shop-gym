"""Write generated tasks to disk as paired ``_real`` / ``_sandbox`` files."""
from __future__ import annotations

import json
from pathlib import Path

from shop_guru.config import Shop
from shop_guru.io import load_json


def make_id(shop_slug: str, skill_slug: str, index: int) -> str:
    """Canonical task ID. Keeps IDs stable across regenerations."""
    return f"{shop_slug}-{skill_slug}-{index}"


def emit_pair(
    tasks: list[dict],
    shop: Shop,
    out_dir: str | Path,
    filename_stem: str,
    skip_real: bool = False,
) -> list[Path]:
    """Write paired ``_real.json`` and ``_sandbox.json`` benchmark files.

    Each task dict is expected to have an ``id`` and no ``url`` field; the
    ``url`` is attached per variant from :attr:`Shop.real_url` and
    :attr:`Shop.sandbox_url` respectively.

    When ``skip_real`` is True, the ``_real.json`` file generation is
    skipped entirely.

    When the shop's ``sandbox_url`` is missing, a ``_sandbox.TBD`` sentinel
    file is written instead so ``build_all`` surfaces the skip clearly.

    Tasks are merged with any existing file contents by task ID, keeping the
    incoming task when IDs collide. This makes `emit_pair` safe to call per
    shop without overwriting other shops' tasks in the same file.

    Returns a list of paths that were written (real file if not skipped, plus
    either sandbox file or TBD sentinel).
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    if not skip_real:
        real_tasks = [dict(t, url=shop.real_url) for t in tasks]
        real_file = out_path / f"{filename_stem}_real.json"
        _merge_and_write(real_file, real_tasks)
        written.append(real_file)

    if shop.sandbox_url:
        sandbox_tasks = [dict(t, url=shop.sandbox_url) for t in tasks]
        sandbox_file = out_path / f"{filename_stem}_sandbox.json"
        _merge_and_write(sandbox_file, sandbox_tasks)
        written.append(sandbox_file)
    else:
        sentinel = out_path / f"{filename_stem}_sandbox.TBD"
        sentinel.write_text(
            f"sandbox URL for shop {shop.slug} is TBD; rerun after shops.yml is updated\n"
        )
        written.append(sentinel)

    return written


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
