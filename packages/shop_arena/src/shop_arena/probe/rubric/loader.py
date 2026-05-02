"""Load + validate + content-hash rubric YAML.

The rubric YAML is the canonical artifact: ``content_hash`` is computed
over the raw UTF-8 file bytes, not a re-serialized normalization, so
reviewers can re-hash the same file we shipped.

Expected YAML shape (v1.0)::

    version: "1.0"
    entries:
      - id: observation.shape
        family: observation
        kind: shape
        page_types: [homepage, collection, product, search, cart]
        modalities: [a11y, screenshot]

      - id: observation.product.title
        family: observation
        kind: info_slot
        page_type: product
        modalities: [a11y, screenshot]
        prompt: prompts/info_slots/product_title.md
        description: PDP exposes a clearly-identifiable product title.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from shop_arena.probe.rubric.schema import Rubric


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
