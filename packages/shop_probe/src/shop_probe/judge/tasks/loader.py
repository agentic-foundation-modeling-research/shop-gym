"""Load + validate + content-hash judge task YAML.

Implements the loader half of T4.3 (spec §5.5 step 1 + §5.8). The task
YAML is the canonical artifact: the ``content_hash`` we compute is over
the raw UTF-8 file bytes, not over a re-serialized normalisation. That
keeps reproducibility honest — reviewers re-hash the same file we
shipped.

Expected YAML shape::

    version: v1
    tasks:
      - id: filter_pdp_variant_cart_locale
        description: |
          On the bestsellers collection, filter by Product Type, ...
        surfaces: [collection, product, cart]
        interactions: [filter, open_pdp, variant_select, add_to_cart, locale_switch]
        rationale: |
          Multi-page navigation with ...
      - ...
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from shop_probe.judge.tasks.schema import JudgeTaskSet


class JudgeTaskLoadError(ValueError):
    """Raised when judge task YAML is malformed or fails schema validation.

    Wraps the underlying YAML / pydantic error so callers can ``except
    JudgeTaskLoadError`` without depending on either library directly.
    """


def compute_content_hash(content: bytes) -> str:
    """Compute the canonical content hash for a judge task YAML payload.

    Args:
        content: Raw UTF-8 bytes of the judge task YAML file.

    Returns:
        Lowercase hex SHA-256 digest (64 chars).
    """
    return hashlib.sha256(content).hexdigest()


def load_judge_tasks(path: str | Path) -> JudgeTaskSet:
    """Load and validate a judge task YAML file.

    Args:
        path: Path to a judge task YAML file. Read as raw bytes; the
            ``content_hash`` on the returned :class:`JudgeTaskSet` is
            the SHA-256 of those bytes.

    Returns:
        A validated :class:`JudgeTaskSet` with ``content_hash``
        populated.

    Raises:
        FileNotFoundError: ``path`` does not exist.
        JudgeTaskLoadError: YAML is malformed, top-level shape is
            wrong, or any task fails :class:`JudgeTask` validation.
    """
    yaml_path = Path(path)
    raw = yaml_path.read_bytes()
    return load_judge_tasks_bytes(raw)


def load_judge_tasks_bytes(content: bytes) -> JudgeTaskSet:
    """Load and validate a judge task list from in-memory YAML bytes.

    Used by tests that want to assert deterministic hashing without
    touching the filesystem, and by :func:`load_judge_tasks` after
    reading the source file.

    Args:
        content: Raw UTF-8 bytes of the judge task YAML payload.

    Returns:
        A validated :class:`JudgeTaskSet` with ``content_hash``
        populated.

    Raises:
        JudgeTaskLoadError: YAML is malformed or fails schema
            validation.
    """
    try:
        parsed: Any = yaml.safe_load(content)
    except yaml.YAMLError as err:
        msg = f"judge task YAML failed to parse: {err}"
        raise JudgeTaskLoadError(msg) from err

    if not isinstance(parsed, dict):
        msg = (
            "judge task YAML must be a mapping with 'version' and 'tasks' keys "
            f"(got {type(parsed).__name__})"
        )
        raise JudgeTaskLoadError(msg)

    payload = dict(parsed)  # type: ignore[arg-type]
    payload["content_hash"] = compute_content_hash(content)

    try:
        return JudgeTaskSet.model_validate(payload)
    except ValidationError as err:
        msg = f"judge task YAML failed schema validation: {err}"
        raise JudgeTaskLoadError(msg) from err
