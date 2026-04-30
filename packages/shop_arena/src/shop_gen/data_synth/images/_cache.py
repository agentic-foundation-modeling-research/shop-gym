"""Content-addressed disk cache for AI-generated image bytes (spec §5.2).

Re-runs of ``gen_images`` against the same prompt + model + size +
quality + prompt_version skip the API entirely once an image has been
fetched. Required to keep the v0.1 fingerprint-based staleness contract
working with a stochastic backend (different bytes every call).

Cache layout (per workspace):

```
<out_dir>/.shop_gen/image_cache/<sha256>.png
```

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Final

_CACHE_DIR: Final[Path] = Path(".shop_gen") / "image_cache"


def cache_dir(out_dir: Path) -> Path:
    """Return ``<out_dir>/.shop_gen/image_cache`` (the directory is not created here)."""
    return out_dir / _CACHE_DIR


def compute_cache_key(
    *,
    prompt: str,
    model: str,
    size: str,
    quality: str,
    prompt_version: int,
) -> str:
    """Return the sha256 hex digest used as the cache filename stem.

    The key is sha256 over the canonicalized JSON payload so any change
    to the rendered prompt, model id, size, quality, or prompt template
    version invalidates the cache for that entry — without affecting
    siblings whose inputs are unchanged.

    Args:
        prompt: Final rendered prompt sent to the model.
        model: Model identifier (e.g. ``gpt-image-1``).
        size: Canvas size string (e.g. ``1024x1024``).
        quality: Quality tier (e.g. ``medium``).
        prompt_version: Integer version of the prompt template; bump to
            bust every cache entry on the next run when the template
            (or its brand-safety suffix) changes.

    Returns:
        A 64-character hex digest (``hashlib.sha256``).
    """
    payload = json.dumps(
        {
            "prompt": prompt,
            "model": model,
            "size": size,
            "quality": quality,
            "prompt_version": prompt_version,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cache_get(out_dir: Path, key: str, *, extension: str) -> bytes | None:
    """Return cached bytes for ``key`` or ``None`` on miss.

    Args:
        out_dir: Run workspace.
        key: Cache key from :func:`compute_cache_key`.
        extension: Image extension (with leading dot) — matches the
            backend's ``extension`` attribute (e.g. ``".png"``).

    Returns:
        The cached bytes if the entry exists; ``None`` otherwise.
    """
    path = cache_dir(out_dir) / f"{key}{extension}"
    if not path.exists():
        return None
    return path.read_bytes()


def cache_put(out_dir: Path, key: str, payload: bytes, *, extension: str) -> None:
    """Persist ``payload`` for ``key`` atomically.

    Writes to a ``.tmp`` sibling then renames into place, so a partial
    write from a crashing process never publishes a truncated entry that
    a future run would treat as a hit.
    """
    target_dir = cache_dir(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = target_dir / f"{key}{extension}"
    tmp_path = target_dir / f"{key}{extension}.tmp"
    tmp_path.write_bytes(payload)
    os.replace(tmp_path, final_path)


__all__ = [
    "cache_dir",
    "cache_get",
    "cache_put",
    "compute_cache_key",
]
