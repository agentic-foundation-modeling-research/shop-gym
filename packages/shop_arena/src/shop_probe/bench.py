"""Load + validate bench YAML (``web_probe_patch.md``).

Replaces the prior ``shop_probe.cohort`` module per
``docs/specs/shop_arena/web_probe_patch.md``.

Expected YAML shape::

    version: "0.1"
    sandboxes:
      - { name: shop_alpha, base_url: https://..., label: sandbox }
      - { name: shop_beta,  base_url: https://..., label: sandbox }
    reals:
      - { name: real_a, base_url: https://..., label: real }
      - { name: real_b, base_url: https://..., label: real }
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from shop_probe.targets import Bench


class BenchLoadError(ValueError):
    """Raised when bench YAML is malformed or fails schema validation."""


def load_bench(path: str | Path) -> Bench:
    """Load and validate a bench YAML file.

    Args:
        path: Path to a bench YAML file.

    Returns:
        A validated :class:`Bench`.

    Raises:
        FileNotFoundError: ``path`` does not exist.
        BenchLoadError: YAML is malformed, top-level shape is wrong, or
            any entry fails :class:`Bench` / :class:`Target` validation.
    """
    return load_bench_bytes(Path(path).read_bytes())


def load_bench_bytes(content: bytes) -> Bench:
    """Load and validate a bench from in-memory YAML bytes.

    Args:
        content: Raw UTF-8 bytes of the bench YAML payload.

    Returns:
        A validated :class:`Bench`.

    Raises:
        BenchLoadError: YAML is malformed or fails schema validation.
    """
    try:
        parsed: Any = yaml.safe_load(content)
    except yaml.YAMLError as err:
        msg = f"bench YAML failed to parse: {err}"
        raise BenchLoadError(msg) from err

    if not isinstance(parsed, dict):
        msg = (
            "bench YAML must be a mapping with 'version' / 'sandboxes' / "
            f"'reals' keys (got {type(parsed).__name__})"
        )
        raise BenchLoadError(msg)

    try:
        return Bench.model_validate(parsed)
    except ValidationError as err:
        msg = f"bench YAML failed schema validation: {err}"
        raise BenchLoadError(msg) from err
