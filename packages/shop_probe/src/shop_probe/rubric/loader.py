"""Load + validate + content-hash rubric YAML.

Implements the loader half of T1.3 (spec §5.3 + §5.8). The rubric YAML
is the canonical artifact: the ``content_hash`` we compute is over the
raw UTF-8 file bytes, not over a re-serialized normalization. That
keeps reproducibility honest — reviewers re-hash the same file we
shipped.

Expected YAML shape::

    version: v1
    entries:
      - id: product.gallery.thumbnails
        category: product
        level: modern
        weight: 2
        probe: probes.product.gallery_has_thumbnails
        description: PDP gallery exposes a thumbnail strip ...
        authenticated: false
        transactional: false
      - ...
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from shop_probe.rubric.schema import Rubric


class RubricLoadError(ValueError):
    """Raised when rubric YAML is malformed or fails schema validation.

    Wraps the underlying YAML / pydantic error so callers can ``except
    RubricLoadError`` without depending on either library directly.
    """


def compute_content_hash(content: bytes) -> str:
    """Compute the canonical content hash for a rubric YAML payload.

    Args:
        content: Raw UTF-8 bytes of the rubric YAML file.

    Returns:
        Lowercase hex SHA-256 digest (64 chars).
    """
    return hashlib.sha256(content).hexdigest()


def load_rubric(path: str | Path) -> Rubric:
    """Load and validate a rubric YAML file.

    Args:
        path: Path to a rubric YAML file. Read as raw bytes; the
            ``content_hash`` on the returned :class:`Rubric` is the
            SHA-256 of those bytes.

    Returns:
        A validated :class:`Rubric` with ``content_hash`` populated.

    Raises:
        FileNotFoundError: ``path`` does not exist.
        RubricLoadError: YAML is malformed, top-level shape is wrong,
            or any entry fails :class:`RubricEntry` validation.
    """
    yaml_path = Path(path)
    raw = yaml_path.read_bytes()
    return load_rubric_bytes(raw)


def load_rubric_bytes(content: bytes) -> Rubric:
    """Load and validate a rubric from in-memory YAML bytes.

    Used by tests that want to assert deterministic hashing without
    touching the filesystem, and by ``load_rubric`` after reading the
    source file.

    Args:
        content: Raw UTF-8 bytes of the rubric YAML payload.

    Returns:
        A validated :class:`Rubric` with ``content_hash`` populated.

    Raises:
        RubricLoadError: YAML is malformed or fails schema validation.
    """
    try:
        parsed: Any = yaml.safe_load(content)
    except yaml.YAMLError as err:
        msg = f"rubric YAML failed to parse: {err}"
        raise RubricLoadError(msg) from err

    if not isinstance(parsed, dict):
        msg = (
            "rubric YAML must be a mapping with 'version' and 'entries' keys "
            f"(got {type(parsed).__name__})"
        )
        raise RubricLoadError(msg)

    payload = dict(parsed)  # type: ignore[arg-type]
    payload["content_hash"] = compute_content_hash(content)

    try:
        return Rubric.model_validate(payload)
    except ValidationError as err:
        msg = f"rubric YAML failed schema validation: {err}"
        raise RubricLoadError(msg) from err
