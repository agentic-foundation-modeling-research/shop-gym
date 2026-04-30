"""Read product / collection counts from a target's ``data_dir``.

The ``type: scale`` rubric entry surfaces catalog scale by reading
two JSON files from the target's :attr:`shop_probe.targets.Target.data_dir`:

* ``products.json``    — either a list of products at the root, or a
  ``{"products": [...]}`` wrapper.
* ``collections.json`` — either a list of collections at the root, or
  a ``{"collections": [...]}`` wrapper.

Both shapes are valid in practice today: the sandbox-shop pipeline
emits lists at the root, while real-shop prefetch dumps wrap the list
under a top-level key. This module auto-detects the shape per file
and returns ``None`` for any file we couldn't decode in either form.

The module is import-safe — file reads happen only inside
:func:`read_catalog_counts`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

_PRODUCTS_FILE: Final[str] = "products.json"
_COLLECTIONS_FILE: Final[str] = "collections.json"
_PRODUCTS_KEY: Final[str] = "products"
_COLLECTIONS_KEY: Final[str] = "collections"


def _count_list(payload: object, wrapper_key: str) -> int | None:
    """Return ``len(payload)`` for a list, or ``len(payload[wrapper_key])`` for a wrapped list.

    Args:
        payload: Decoded JSON value.
        wrapper_key: Top-level key whose value is the list (e.g.
            ``"products"`` or ``"collections"``).

    Returns:
        The count, or ``None`` when the payload is in neither
        recognised shape.
    """
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        inner = payload.get(wrapper_key)
        if isinstance(inner, list):
            return len(inner)
    return None


def _read_count(file_path: Path, wrapper_key: str) -> int | None:
    """Decode ``file_path`` and return a list count.

    Returns ``None`` when the file does not exist, is unreadable, or
    decodes to an unrecognised shape. Errors are swallowed by design:
    the scale runner must not abort one target's report because its
    catalog dump is malformed.
    """
    if not file_path.is_file():
        return None
    try:
        with file_path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return _count_list(payload, wrapper_key)


def read_catalog_counts(data_dir: Path) -> tuple[int | None, int | None]:
    """Return ``(products_count, collections_count)`` for ``data_dir``.

    Auto-detects the two on-disk shapes documented at module top:
    a list at the root (sandbox dumps) or a ``{"<key>": [...]}``
    wrapper (real-shop prefetch). Missing files or unrecognised
    shapes yield ``None`` for that one count without affecting the
    other.

    Args:
        data_dir: Directory containing ``products.json`` and / or
            ``collections.json``.

    Returns:
        A 2-tuple ``(products, collections)``; either entry may be
        ``None`` when its file is missing or unrecognised.
    """
    products = _read_count(data_dir / _PRODUCTS_FILE, _PRODUCTS_KEY)
    collections = _read_count(data_dir / _COLLECTIONS_FILE, _COLLECTIONS_KEY)
    return products, collections
