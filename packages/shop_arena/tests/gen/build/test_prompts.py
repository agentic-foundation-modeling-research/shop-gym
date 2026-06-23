"""Lint-only tests for the Phase 4 build-harness-loop prompt templates.

T5.3 from ``docs/impl/shop_gen_implementation.md`` requires the prompt
files under ``packages/shop_arena/src/shop_arena/gen/build/prompts/`` —
``agents.md`` / ``planner.md`` / ``execute.md`` — and asserts that the
executor body carries the ``{{verifier_feedback}}`` placeholder the
harness substitutes at runtime (verifiers spec §5.5).

These tests are pure I/O over the in-repo prompt files; they never
spawn an LLM client and never load runtime config.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest

from shop_arena.gen.build.prompts import (
    VERIFIER_FEEDBACK_PLACEHOLDER,
    copy_fixes_into,
    load_agents_md,
    load_cross_task_consistency_prompt,
    load_execute_prompt,
    load_planner_prompt,
    load_quality_judge_prompt,
    load_visual_judge_prompt,
)

# The loaders T5.3 ships, keyed by the prompt-file slot they populate.
# Keep this in lockstep with ``shop_arena.gen.build.prompts.__all__``.
_LOADERS: Final[dict[str, Callable[[], str]]] = {
    "agents.md": load_agents_md,
    "planner.md": load_planner_prompt,
    "execute.md": load_execute_prompt,
    "quality_judge.md": load_quality_judge_prompt,
    "cross_task_consistency.md": load_cross_task_consistency_prompt,
    "visual_judge.md": load_visual_judge_prompt,
}

# The executor body must carry the verifier-feedback placeholder.
_EXECUTOR_LOADERS: Final[dict[str, Callable[[], str]]] = {
    "execute.md": load_execute_prompt,
}


@pytest.mark.parametrize("name", sorted(_LOADERS))
def test_prompt_file_is_non_empty(name: str) -> None:
    """Every T5.3 prompt file must be present and non-empty."""
    body = _LOADERS[name]()
    assert body.strip(), f"{name}: prompt file is empty"


@pytest.mark.parametrize("name", sorted(_EXECUTOR_LOADERS))
def test_executor_prompt_contains_verifier_feedback_placeholder(name: str) -> None:
    """Both executor bodies must carry the harness verifier-feedback slot.

    The harness only renders ``{{verifier_feedback}}`` when the
    placeholder is literally present in the executor body
    (``harness.loop._compose_executor_prompt``). A missing placeholder
    silently drops feedback, masking retry failures.
    """
    body = _EXECUTOR_LOADERS[name]()
    assert VERIFIER_FEEDBACK_PLACEHOLDER in body, (
        f"{name}: executor body is missing the "
        f"'{VERIFIER_FEEDBACK_PLACEHOLDER}' placeholder. The harness "
        "needs the placeholder to inject prior-iteration verifier "
        "feedback (verifiers spec §5.5)."
    )


def test_planner_prompt_lists_canonical_task_ids() -> None:
    """The planner prompt must enumerate the v0.1 canonical task ids.

    Spec §5.5.2 fixes the planner output to a canonical block:
    ``gen_theme``, ``gen_navigation``, ``gen_homepage``,
    ``gen_collections``, ``gen_product``, ``gen_cart_search``,
    ``gen_info_pages``, ``visual_fix``. A planner prompt that drops
    one of these would surprise the verifier dispatch contract
    (spec §5.5.3) which keys on the canonical task ids.
    """
    body = load_planner_prompt()
    canonical_ids = (
        "gen_theme",
        "gen_navigation",
        "gen_homepage",
        "gen_collections",
        "gen_product",
        "gen_cart_search",
        "gen_info_pages",
        "visual_fix",
    )
    missing = [task_id for task_id in canonical_ids if task_id not in body]
    assert not missing, (
        f"planner.md is missing canonical task id(s): {missing}. "
        "Spec §5.5.2 requires every run to emit these in `## Tasks`."
    )


def test_planner_prompt_marks_visual_fix_as_required() -> None:
    """The planner prompt must mark ``visual_fix`` as REQUIRED + lowest priority.

    Spec §5.5.4 makes ``visual_fix`` mandatory: it absorbs the
    cross-task cleanup remit. The planner prompt must brief that
    explicitly so the planner does not drop it.
    """
    body = load_planner_prompt()
    assert "REQUIRED" in body, "planner.md must mark `visual_fix` as REQUIRED (spec §5.5.4)."
    assert "visual_fix" in body, "planner.md must reference the `visual_fix` task id."


def test_execute_prompt_describes_visual_fix_cross_task_cleanup() -> None:
    """The execute prompt must orient ``visual_fix`` to cross-task cleanup, not new features.

    Spec §5.5.4 — ``visual_fix`` reads the entire ``hydrogen/app/``
    tree, fixes leftover ``[!]`` issues + cross-page seams (shared-
    component drift, conflicting tokens, orphaned imports, broken
    inter-page links, deferred verifier feedback). The exact wording
    can drift; this test asserts the *intent* survives.
    """
    body = load_execute_prompt()
    must_mention = (
        "visual_fix",
        "drift",
        "deferred",
    )
    missing = [token for token in must_mention if token.lower() not in body.lower()]
    assert not missing, (
        f"execute.md must orient `visual_fix` to cross-task cleanup "
        f"(spec §5.5.4). Missing key concept(s): {missing}."
    )


def test_agents_md_warns_against_real_world_brand_tokens() -> None:
    """The build constitution must still warn the agent away from real-world brands.

    The fake-brand allowlist (spec §5.6) is enforced by the data-synth
    pipeline over ``data/*.json`` — not by the build agent — and the
    ``no_brand_leak`` verifier is disabled (commit ``e54c98f``: too many
    false positives on Hydrogen / React / TypeScript identifiers). The
    residual contract for the build agent is a single "Don'ts" bullet:
    "no real-world brand tokens, real domains, real emails, or
    trademarked names" anywhere in the hydrogen tree. This test pins
    that bullet so we don't lose the rule when the section is reshuffled.
    """
    body = load_agents_md().lower()
    flat = " ".join(body.split())
    assert "real-world brand" in flat or "real-world brands" in flat, (
        "agents.md must warn the build agent against real-world brand "
        "tokens in the 'Don'ts' section (commit e54c98f kept this rule "
        "after dropping the explicit allowlist)."
    )


def test_loaders_are_cached() -> None:
    """Repeated loader calls must return the same string identity (cache).

    The loaders are decorated with ``functools.cache``; the build-loop
    driver calls them once per harness invocation, but tests and
    ad-hoc callers should not re-read disk.
    """
    for loader in _LOADERS.values():
        first = loader()
        second = loader()
        assert first is second, (
            f"{loader.__name__}: loader is not cached — "
            "expected identical object identity across calls."
        )


def test_quality_judge_prompt_carries_required_format_slots() -> None:
    """The ``quality_judge`` template must accept the slots T5.5 fills in.

    The verifier renders ``task_id`` / ``capabilities`` / ``source_blocks``
    via ``str.format()``; a missing placeholder would crash with
    ``KeyError`` at the first dispatch. The test exercises the format
    call directly with placeholder values to lock the contract.
    """
    body = load_quality_judge_prompt()
    rendered = body.format(
        task_id="gen_homepage",
        capabilities="{}",
        source_blocks="### x",
    )
    assert "gen_homepage" in rendered
    assert "### x" in rendered


def test_cross_task_consistency_prompt_carries_required_format_slots() -> None:
    """The ``cross_task_consistency`` template must accept the T5.5 slots."""
    body = load_cross_task_consistency_prompt()
    rendered = body.format(
        collection_handles="[]",
        source_blocks="### x",
    )
    assert "### x" in rendered


def test_visual_judge_prompt_carries_required_format_slots() -> None:
    """The ``visual_judge`` template must accept the six T1.2 slots.

    Spec §9.2 fixes six placeholders the verifier renders before each
    iteration: ``base_url`` / ``task_id`` / ``capabilities_slice`` /
    ``route_list`` / ``verdict_schema`` / ``prior_feedback_or_empty``.
    A missing placeholder would crash with ``KeyError`` at the first
    dispatch; a stray literal ``{`` would crash ``str.format`` with a
    different error. The test exercises the format call directly with
    placeholder values to lock the contract.
    """
    body = load_visual_judge_prompt()
    rendered = body.format(
        base_url="http://localhost:3000",
        task_id="gen_homepage",
        capabilities_slice="{}",
        route_list="- /",
        verdict_schema="{}",
        prior_feedback_or_empty="",
    )
    assert "http://localhost:3000" in rendered
    assert "gen_homepage" in rendered
    assert "- /" in rendered


def test_visual_judge_prompt_calls_out_pre_filtered_capability_slice() -> None:
    """The visual-judge prompt must tell the agent the slice is pre-filtered.

    Spec §9.2 — the prompt must explicitly tell the agent the
    capabilities slice has been pre-filtered for this task's bucket(s)
    so it does not penalise the absence of features that belong to a
    different bucket. T1.2 "Check" pins this contract.
    """
    body = load_visual_judge_prompt()
    flat = " ".join(body.split()).lower()
    assert "pre-filtered" in flat, (
        "visual_judge.md must call out that the capabilities slice has "
        "been pre-filtered for the task's bucket(s) (visual-verifier "
        "spec §9.2)."
    )
    assert "bucket" in flat, (
        "visual_judge.md must reference the page-bucket axis so the "
        "agent understands why the slice is narrow (spec §9.2)."
    )


def test_visual_judge_prompt_forbids_networkidle_and_run_code() -> None:
    """The rendered-page judge must avoid known hanging browser patterns."""
    body = load_visual_judge_prompt().lower()
    assert "networkidle" in body, (
        "visual_judge.md must explicitly warn against networkidle waits; "
        "Hydrogen pages can keep background requests open until the verifier times out."
    )
    assert "run-code" in body, (
        "visual_judge.md must steer the agent away from raw run-code navigation "
        "and toward the playwright skill's bounded built-in commands."
    )


# ---------------------------------------------------------------------------
# `prompts/fixes/` — per-task pitfall + reuse rules read by the executor at
# task-start (execute.md §2 step 5).
# ---------------------------------------------------------------------------

# The fix files we expect on disk. ``common.md`` is read by every task; the
# per-task files are read only when the executor's task id matches.
_REQUIRED_FIX_FILES: Final[tuple[str, ...]] = (
    "common.md",
    "gen_navigation.md",
    "gen_homepage.md",
    "gen_collections.md",
    "gen_product.md",
    "gen_cart_search.md",
)


def test_execute_prompt_points_executor_at_fixes_dir() -> None:
    """`execute.md` must instruct the executor to read `prompts/fixes/`.

    Without this pointer the per-task fix files stay on disk and never
    enter the executor's context. The exact wording is allowed to drift
    — what matters is that the path is named.
    """
    body = load_execute_prompt()
    assert "prompts/fixes/common.md" in body, (
        "execute.md must instruct the executor to read "
        "`prompts/fixes/common.md` (the cross-cutting rule file)."
    )
    assert "prompts/fixes/<task_id>.md" in body, (
        "execute.md must instruct the executor to read "
        "`prompts/fixes/<task_id>.md` after picking its task."
    )


def test_copy_fixes_into_materialises_per_task_files(tmp_path: Path) -> None:
    """`copy_fixes_into` must materialise the canonical fix tree in the target dir.

    Doubles as the source-side assertion: a missing or empty file in
    the package's `prompts/fixes/` directory would surface here as a
    missing or empty file in the copy target.
    """
    target_prompts = tmp_path / "prompts"
    target_prompts.mkdir()
    copy_fixes_into(target_prompts)

    fixes_dir = target_prompts / "fixes"
    assert fixes_dir.is_dir(), "fixes/ subdir must be created under prompts/"
    for name in _REQUIRED_FIX_FILES:
        path = fixes_dir / name
        assert path.is_file(), f"prompts/fixes/{name} not copied"
        assert path.read_text(encoding="utf-8").strip(), f"prompts/fixes/{name} is empty"


def test_gen_cart_search_fix_prompt_warns_against_forced_cart_drawers(
    tmp_path: Path,
) -> None:
    """The cart-search fix prompt must preserve manual-specific cart surfaces."""
    target_prompts = tmp_path / "prompts"
    target_prompts.mkdir()
    copy_fixes_into(target_prompts)

    body = (target_prompts / "fixes" / "gen_cart_search.md").read_text(
        encoding="utf-8",
    )
    assert "Do not force every cart into a drawer" in body
    assert "no" in body.lower()
    assert "slide-in side drawer or modal" in body
    assert '`<Aside type="cart">`' in body
    assert "navigate to `/cart`" in body
    assert ".overlay > aside" in body
    assert "visually offscreen" in body


def test_copy_fixes_into_is_idempotent_for_resume(tmp_path: Path) -> None:
    """`copy_fixes_into` must no-op when the target already exists.

    The harness's resume path leaves a populated `<run_dir>/prompts/fixes/`
    in place; a second call (e.g. on retry after a transient failure) must
    not raise `FileExistsError` or clobber the existing tree.
    """
    target_prompts = tmp_path / "prompts"
    target_prompts.mkdir()
    copy_fixes_into(target_prompts)
    sentinel = (target_prompts / "fixes" / "common.md").read_bytes()
    copy_fixes_into(target_prompts)  # second call must not raise
    assert (target_prompts / "fixes" / "common.md").read_bytes() == sentinel
