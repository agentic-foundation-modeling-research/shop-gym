"""Filesystem helpers for reading shop-arena extractions."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from shop_guru.config import Shop

SHOP_DATA_FILES = (
    "store.json",
    "products.json",
    "collections.json",
    "pages.json",
    "policies.json",
    "navigation.json",
    "stats.json",
)

# Files that the multi-shop composite pipeline writes into a sibling
# ``raw_data/`` directory rather than ``data/``. We fall back to those when
# ``data/<filename>`` is missing so shop_guru can run on composite shops
# without a manual copy step. See ``shop_arena.gen.multi_pipeline``.
_RAW_DATA_FALLBACKS: frozenset[str] = frozenset({"stats.json"})

log = logging.getLogger(__name__)


def load_json(path: str | Path) -> Any:
    """Read and parse a JSON file."""
    with Path(path).open() as fh:
        return json.load(fh)


def load_shop_data(shop: Shop) -> dict[str, Any]:
    """Load every extracted JSON under a shop's ``data/`` directory.

    Returns a dict keyed by file stem (e.g. ``"products"``) with each value
    being the parsed JSON.

    For files listed in ``_RAW_DATA_FALLBACKS`` (currently ``stats.json``),
    we additionally probe ``<shop.data_dir>/raw_data/<filename>`` when
    ``data/<filename>`` is absent. Multi-shop composite shops written by
    ``shop_arena.gen.multi_pipeline`` keep their stats under ``raw_data/``;
    without this fallback ``data["stats"]`` would default to ``{}`` and
    every dimension-aware generator would silently emit zero tasks.

    Raises:
        FileNotFoundError: if the shop's ``data/`` directory is missing.
    """
    base = shop.abs_data_dir()
    if not base.exists():
        raise FileNotFoundError(
            f"{base} not found. Run the shop-arena extractor for "
            f"'{shop.data_dir}' first."
        )

    raw_data_dir = base.parent / "raw_data"

    out: dict[str, Any] = {}
    for filename in SHOP_DATA_FILES:
        file_path = base / filename
        if file_path.exists():
            out[file_path.stem] = load_json(file_path)
            continue

        if filename in _RAW_DATA_FALLBACKS:
            fallback = raw_data_dir / filename
            if fallback.exists():
                log.warning(
                    "shop_guru.io: %s missing for shop %r; falling back to %s",
                    file_path,
                    shop.slug,
                    fallback,
                )
                out[file_path.stem] = load_json(fallback)
                continue

        out[file_path.stem] = _empty_default(filename)
    return out


def _empty_default(filename: str) -> Any:
    return {} if filename in {"store.json", "stats.json", "navigation.json"} else []
