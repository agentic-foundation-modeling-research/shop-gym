"""Shared helpers for axis-A probe tests (T1.7).

Imported by ``tests/probes/test_*.py`` and the corresponding
``tests/probes/conftest.py``. Lives at ``tests/_probe_helpers.py`` so it
sits next to ``_sandbox.py`` and is reachable via the rootdir-based
sys.path pytest sets up for ``packages/shop_arena/tests/shop_probe/``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from shop_probe.probes._runner import ProbeContext, ProbeOutcome, ProbeRunner

# Standard sample paths exposed by the localhost fixture.
SAMPLE_PRODUCT_PATH = "/products/sample"
SAMPLE_COLLECTION_PATH = "/collections/all"


def run_probe(
    probe: Callable[[object, ProbeContext], Awaitable[ProbeOutcome]],
    *,
    base_url: str,
    probe_id: str,
    evidence_root: Path,
    sample_product_url: str | None = None,
    sample_collection_url: str | None = None,
) -> ProbeOutcome:
    """Drive one probe through :class:`ProbeRunner` and return the outcome.

    Wraps the async-context-manager dance so individual tests stay synchronous.
    """

    async def _go() -> ProbeOutcome:
        async with ProbeRunner(evidence_root=evidence_root) as runner:
            return await runner.run(
                probe,  # type: ignore[arg-type]
                base_url=base_url,
                probe_id=probe_id,
                sample_product_url=sample_product_url,
                sample_collection_url=sample_collection_url,
            )

    return asyncio.run(_go())
