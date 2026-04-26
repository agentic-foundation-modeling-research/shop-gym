"""Live-CLI smoke test for ``shop_explore`` against the ``pi`` runtime (T4.3).

Skipped unless ``SHOP_EXPLORE_SMOKE_PI=1`` is set in the environment.
When enabled, the test runs the full :func:`shop_explore.explore`
pipeline against a real storefront with the live ``pi`` runtime and
asserts the §5.4 / §5.10 invariants:

* harness ``final_status == completed``;
* ``capabilities.json`` validates against the closed
  :class:`shop_explore.Capabilities` schema;
* ``stats.json`` validates against the :class:`shop_explore.Stats`
  schema;
* every executor task in ``plan.md`` has at least one screenshot
  under ``artifact/evidence/<task_id>/`` (spec §5.7 obligation 5).

The fixture URL defaults to the minimal Shopify Dawn theme preview
shop (`https://theme-dawn-demo.myshopify.com`) per the M4 fixture
plan; override with ``SHOP_EXPLORE_SMOKE_URL`` when iterating against
a different live storefront.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path

import pytest

from harness.config import FinalStatus
from harness.plan import parse as parse_plan
from shop_explore import Capabilities, ExploreConfig, Stats, explore

_SMOKE_ENV_VAR = "SHOP_EXPLORE_SMOKE_PI"
_URL_ENV_VAR = "SHOP_EXPLORE_SMOKE_URL"
_DEFAULT_FIXTURE_URL = "https://theme-dawn-demo.myshopify.com"

_LIVE_TIMEOUT_SECONDS = 600.0
_LIVE_MAX_ITERS = 12

_SCREENSHOT_SUFFIXES: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp"})


@pytest.mark.smoke
@pytest.mark.skipif(
    os.environ.get(_SMOKE_ENV_VAR) != "1",
    reason=f"{_SMOKE_ENV_VAR}!=1; live shop_explore smoke test skipped",
)
def test_shop_explore_pi_smoke_live(tmp_path: Path) -> None:
    """Drive the full pipeline live against the configured fixture storefront."""
    url = os.environ.get(_URL_ENV_VAR, _DEFAULT_FIXTURE_URL)
    config = ExploreConfig(
        url=url,
        out_dir=tmp_path / "run",
        runtime="pi",
        max_iters=_LIVE_MAX_ITERS,
        timeout=_LIVE_TIMEOUT_SECONDS,
    )

    result = explore(config)

    assert result.final_status is FinalStatus.COMPLETED, (
        f"harness final_status was {result.final_status!r}, expected COMPLETED"
    )

    # Schemas validate (closed pydantic v2 models reject unknown fields).
    Capabilities.model_validate(json.loads(result.capabilities_path.read_text(encoding="utf-8")))
    Stats.model_validate(json.loads(result.stats_path.read_text(encoding="utf-8")))

    # Every executor task that ran ends up with ≥ 1 screenshot under evidence/.
    plan_md = (result.run_dir / "plan.md").read_text(encoding="utf-8")
    task_ids = [task.id for task in parse_plan(plan_md).tasks]
    assert task_ids, "plan.md has no tasks; planner emitted an empty plan"

    evidence_root = result.run_dir / "artifact" / "evidence"
    missing: list[str] = [
        task_id for task_id in task_ids if not _has_screenshot(evidence_root / task_id)
    ]
    assert not missing, f"tasks missing ≥ 1 screenshot under evidence/: {missing}"


def _has_screenshot(task_evidence_dir: Path) -> bool:
    """Return ``True`` iff ``task_evidence_dir`` contains at least one image file."""
    if not task_evidence_dir.is_dir():
        return False
    return any(_iter_image_files(task_evidence_dir))


def _iter_image_files(root: Path) -> Iterable[Path]:
    """Yield every file under ``root`` whose suffix is a known screenshot type."""
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in _SCREENSHOT_SUFFIXES:
            yield path
