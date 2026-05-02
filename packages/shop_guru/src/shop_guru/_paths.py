"""Repo-anchored paths.

shop_guru is part of the ``shop-gym`` mono-repo and reads inputs from
``<repo>/outputs/shops/<slug>/data/`` (produced by ``shop_arena``) and
writes outputs to ``<repo>/outputs/shop_guru/<slug>/...``. The single
anchor for both is :data:`_REPO_ROOT`, computed from this file's
location so it works the same regardless of cwd.

Tests can monkeypatch ``shop_guru._paths._REPO_ROOT`` to redirect both
input discovery and output writes to a temporary directory.
"""
from __future__ import annotations

from pathlib import Path

# packages/shop_guru/src/shop_guru/_paths.py
#   parents[0] = shop_guru/
#   parents[1] = src/
#   parents[2] = packages/shop_guru/
#   parents[3] = packages/
#   parents[4] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]


def repo_root() -> Path:
    """Return the repo root.

    Reads ``_REPO_ROOT`` at call time so tests can monkeypatch the
    module attribute and have every caller pick up the override.
    """
    return _REPO_ROOT
