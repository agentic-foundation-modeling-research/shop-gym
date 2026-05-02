"""Shop configuration loading.

A `shops.yml` file is the single source of truth for which storefronts the
benchmark covers and how to reach both the production seed site and its
SandboxShop deployment. See `shops.yml` at the repo root for the expected
schema.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from shop_guru._paths import repo_root


@dataclass(frozen=True)
class Shop:
    """A single featured storefront.

    Attributes:
        slug: Short identifier used as a prefix in task IDs (e.g. ``mock_shop``).
        name: Human-readable store name.
        real_url: Production seed storefront URL (no trailing slash).
        sandbox_url: SandboxShop URL with any required auth query string (no
            trailing slash), or ``None`` if not yet deployed.
        data_dir: Path to the extracted shop directory. Relative paths are
            anchored at the repo root (e.g. ``outputs/shops/<domain>`` —
            written there by ``shop_arena``); absolute paths are used as-is.
        country: ISO 3166-1 alpha-2 country code of the seed store.
        currency: ISO 4217 currency code.
        language: ISO 639-1 language code of the seed store.
        image_tag: Artifact Registry tag for the SandboxShop Docker image.
        notes: Free-form merchant-specific commentary.
    """

    slug: str
    name: str
    real_url: str
    sandbox_url: str | None
    data_dir: str
    country: str
    currency: str
    language: str
    image_tag: str
    notes: str = ""

    def abs_data_dir(self) -> Path:
        """Absolute path to this shop's extracted ``data/`` directory.

        Resolves :attr:`data_dir` against the repo root for relative
        paths, leaving absolute paths untouched.
        """
        base = Path(self.data_dir)
        if not base.is_absolute():
            base = repo_root() / base
        return base / "data"


def load_shops(path: str | Path) -> list[Shop]:
    """Parse a `shops.yml` file and return a list of :class:`Shop` records.

    ``sandbox_url: TBD`` is interpreted as "SandboxShop not yet deployed" and
    becomes ``None``. All URLs have any trailing slash stripped so callers
    can concatenate paths safely.
    """
    doc = _load_yaml(Path(path))
    shops_section = doc.get("shops")
    if not shops_section:
        raise ValueError(f"{path}: missing top-level `shops:` section")

    shops: list[Shop] = []
    for entry in shops_section:
        shops.append(_shop_from_dict(entry))
    return shops


def _shop_from_dict(entry: dict[str, Any]) -> Shop:
    sandbox = entry.get("sandbox_url")
    if sandbox in (None, "", "TBD"):
        sandbox_normalized: str | None = None
    else:
        sandbox_normalized = str(sandbox).rstrip("/")

    return Shop(
        slug=entry["slug"],
        name=entry["name"],
        real_url=str(entry["real_url"]).rstrip("/"),
        sandbox_url=sandbox_normalized,
        data_dir=entry["data_dir"],
        country=entry["country"],
        currency=entry["currency"],
        language=entry["language"],
        image_tag=entry["image_tag"],
        notes=entry.get("notes", ""),
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"shops.yml not found: {path}")
    with path.open() as fh:
        doc = yaml.safe_load(fh) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: YAML must be a mapping at the root")
    return doc
