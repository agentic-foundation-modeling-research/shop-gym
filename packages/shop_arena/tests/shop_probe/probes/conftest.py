"""Shared fixtures for axis-A probe tests (T1.7).

Each test gets a **fresh** SandboxShop instance — the in-process server
holds cart state, so isolating per-test removes cross-test ordering bugs
on the cart line-item probes.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

# `tests/` is on sys.path via pytest's rootdir; `_sandbox.py` lives there.
_TESTS_ROOT = Path(__file__).resolve().parent.parent
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from _sandbox import SandboxShop  # noqa: E402 — sys.path adjustment above


@pytest.fixture
def sandbox_url() -> Iterator[str]:
    """Spin up a fresh in-process SandboxShop for one test."""
    with SandboxShop() as base_url:
        yield base_url
