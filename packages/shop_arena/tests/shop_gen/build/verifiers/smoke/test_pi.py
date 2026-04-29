"""Live-CLI smoke test for the visual sub-iter against the ``pi`` runtime (T6.2).

Skipped unless ``SHOP_GEN_VISUAL_SMOKE_PI=1`` is set in the environment.
When enabled, the test stages a fresh sub-workspace (no ``AGENTS.md`` /
``plan.md``), invokes :func:`shop_gen.build.verifiers._runtime_call.run_visual_iteration`
against a real :class:`harness.runtimes.PiRuntime`, and asserts the
spec §5.2.1 / impl plan T6.2 invariants:

* the playwright skill resolves on the host;
* the nested iteration completes (``iter/native.log`` is populated);
* at least one screenshot lands under ``work/screenshots/``;
* ``work/verdict.json`` parses against the §9.3 schema.

The fixture URL defaults to the Dawn theme demo
(`https://theme-dawn-demo.myshopify.com`); override with
``SHOP_GEN_VISUAL_SMOKE_URL`` when iterating against another live shop.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from harness.runtimes.pi import PiRuntime
from shop_gen.build.prompts import load_visual_judge_prompt
from shop_gen.build.verifiers._runtime_call import run_visual_iteration
from shop_gen.build.verifiers._skills import is_playwright_skill_available
from shop_gen.build.verifiers.visual_judge import (
    _VERDICT_SCHEMA_BLOCK,  # pyright: ignore[reportPrivateUsage]
)

_SMOKE_ENV_VAR = "SHOP_GEN_VISUAL_SMOKE_PI"
_URL_ENV_VAR = "SHOP_GEN_VISUAL_SMOKE_URL"
_DEFAULT_FIXTURE_URL = "https://theme-dawn-demo.myshopify.com"

_LIVE_TIMEOUT_SECONDS = 600.0
_PASS_THRESHOLD = 7.0

_SCREENSHOT_SUFFIXES: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp"})


@pytest.mark.smoke
@pytest.mark.skipif(
    os.environ.get(_SMOKE_ENV_VAR) != "1",
    reason=f"{_SMOKE_ENV_VAR}!=1; live visual sub-iter smoke test skipped",
)
def test_visual_sub_iter_pi_smoke_live(tmp_path: Path) -> None:
    """Drive a real ``pi`` visual sub-iter against the configured fixture storefront."""
    assert is_playwright_skill_available(), (
        "playwright skill is not installed globally; "
        "run `pnpm add -g pi-playwright` before enabling this smoke test"
    )

    base_url = os.environ.get(_URL_ENV_VAR, _DEFAULT_FIXTURE_URL)
    parent_dir = tmp_path / "visual_judge"
    parent_dir.mkdir()

    routes = ("/",)
    capabilities_slice = {"homepage": {"hero": True}}
    prompt = load_visual_judge_prompt().format(
        base_url=base_url,
        task_id="gen_homepage",
        capabilities_slice=json.dumps(capabilities_slice, indent=2, sort_keys=True),
        route_list="\n".join(f"- `{route}`" for route in routes),
        verdict_schema=_VERDICT_SCHEMA_BLOCK,
        prior_feedback_or_empty="",
    )
    routes_payload = {
        "base_url": base_url,
        "task_id": "gen_homepage",
        "buckets": ["homepage"],
        "routes": list(routes),
        "viewports": ["desktop", "mobile"],
    }

    runtime = PiRuntime()
    work_dir, parsed = run_visual_iteration(
        runtime,
        parent_dir=parent_dir,
        prompt=prompt,
        routes=routes_payload,
        timeout_s=_LIVE_TIMEOUT_SECONDS,
        pass_threshold=_PASS_THRESHOLD,
    )

    # Sub-workspace and harness-owned iter dir exist as staged.
    assert work_dir.is_dir(), f"work_dir was not created: {work_dir}"
    iter_dir = work_dir / "iter"
    assert iter_dir.is_dir(), f"iter_dir was not created: {iter_dir}"

    # `iter/native.log` is populated by `PiRuntime`.
    native_log = iter_dir / "native.log"
    assert native_log.is_file(), f"native.log missing under {iter_dir}"
    assert native_log.stat().st_size > 0, f"native.log is empty: {native_log}"

    # The agent saved at least one screenshot via the playwright skill.
    screenshots_dir = work_dir / "screenshots"
    assert screenshots_dir.is_dir(), (
        f"screenshots dir missing under {work_dir}; the agent did not invoke the playwright skill"
    )
    screenshots = [
        p
        for p in screenshots_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in _SCREENSHOT_SUFFIXES
    ]
    assert screenshots, f"no screenshots found under {screenshots_dir}"

    # `verdict.json` parsed against the §9.3 schema.
    assert parsed is not None, (
        f"verdict.json could not be parsed from {work_dir / 'verdict.json'}; "
        "the agent must emit the §9.3 schema"
    )
