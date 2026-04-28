"""Load + validate cohort YAML (T2.4 — spec §7 M2, §8.2).

The cohort schemas (:class:`~shop_probe.targets.Cohort`,
:class:`~shop_probe.targets.Pair`, :class:`~shop_probe.targets.Target`)
live in :mod:`shop_probe.targets` per spec §5.2. That module is
import-safe by design; this is the I/O sibling that turns the YAML
sketched in spec §8.2 into a validated :class:`Cohort`.

Expected YAML shape::

    version: "0.1"
    pairs:
      - id: pair_1
        source:  { label: ..., base_url: ..., kind: source,  pair_id: pair_1 }
        sandbox: { label: ..., base_url: ..., kind: sandbox, pair_id: pair_1 }
      - ...
    real_unpaired:
      - { label: ..., base_url: ..., kind: real_unpaired }
      - ...
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from shop_probe.targets import Cohort


class CohortLoadError(ValueError):
    """Raised when cohort YAML is malformed or fails schema validation.

    Wraps the underlying YAML / pydantic error so callers can ``except
    CohortLoadError`` without depending on either library directly.
    """


def load_cohort(path: str | Path) -> Cohort:
    """Load and validate a cohort YAML file.

    Args:
        path: Path to a cohort YAML file.

    Returns:
        A validated :class:`Cohort`.

    Raises:
        FileNotFoundError: ``path`` does not exist.
        CohortLoadError: YAML is malformed, top-level shape is wrong,
            or any entry fails :class:`Cohort` / :class:`Pair` /
            :class:`Target` validation.
    """
    return load_cohort_bytes(Path(path).read_bytes())


def load_cohort_bytes(content: bytes) -> Cohort:
    """Load and validate a cohort from in-memory YAML bytes.

    Used by tests that want to assert validation behaviour without
    touching the filesystem, and by :func:`load_cohort` after reading
    the source file.

    Args:
        content: Raw UTF-8 bytes of the cohort YAML payload.

    Returns:
        A validated :class:`Cohort`.

    Raises:
        CohortLoadError: YAML is malformed or fails schema validation.
    """
    try:
        parsed: Any = yaml.safe_load(content)
    except yaml.YAMLError as err:
        msg = f"cohort YAML failed to parse: {err}"
        raise CohortLoadError(msg) from err

    if not isinstance(parsed, dict):
        msg = (
            "cohort YAML must be a mapping with 'version' / 'pairs' / "
            f"'real_unpaired' keys (got {type(parsed).__name__})"
        )
        raise CohortLoadError(msg)

    try:
        return Cohort.model_validate(parsed)
    except ValidationError as err:
        msg = f"cohort YAML failed schema validation: {err}"
        raise CohortLoadError(msg) from err
