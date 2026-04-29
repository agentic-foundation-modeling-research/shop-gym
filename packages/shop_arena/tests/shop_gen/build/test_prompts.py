"""Lint-only tests for the Phase 4 build-harness-loop prompt templates.

T5.3 from ``docs/impl/shop_gen_implementation.md`` requires four prompt
files under ``packages/shop_arena/src/shop_gen/build/prompts/`` —
``agents.md`` / ``planner.md`` / ``execute.md`` /
``consolidate_execute.md`` — and asserts that both executor bodies carry
the ``{{verifier_feedback}}`` placeholder the harness substitutes at
runtime (verifiers spec §5.5).

These tests are pure I/O over the in-repo prompt files; they never
spawn an LLM client and never load runtime config.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

import pytest

from shop_gen.build.prompts import (
    VERIFIER_FEEDBACK_PLACEHOLDER,
    load_agents_md,
    load_consolidate_execute_prompt,
    load_cross_task_consistency_prompt,
    load_execute_prompt,
    load_planner_prompt,
    load_quality_judge_prompt,
)

# The four loaders T5.3 ships, keyed by the prompt-file slot they
# populate. Keep this in lockstep with
# ``shop_gen.build.prompts.__all__``.
_LOADERS: Final[dict[str, Callable[[], str]]] = {
    "agents.md": load_agents_md,
    "planner.md": load_planner_prompt,
    "execute.md": load_execute_prompt,
    "consolidate_execute.md": load_consolidate_execute_prompt,
    "quality_judge.md": load_quality_judge_prompt,
    "cross_task_consistency.md": load_cross_task_consistency_prompt,
}

# The two executor bodies must carry the verifier-feedback placeholder.
_EXECUTOR_LOADERS: Final[dict[str, Callable[[], str]]] = {
    "execute.md": load_execute_prompt,
    "consolidate_execute.md": load_consolidate_execute_prompt,
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
    ``gen_info_pages``, ``visual_polish``, ``consolidate``. A planner
    prompt that drops one of these would cause the orchestrator's
    consolidate-append fallback (spec §5.5.4) to fire and would surprise
    the verifier dispatch contract (spec §5.5.3) which keys on the
    canonical task ids.
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
        "visual_polish",
        "consolidate",
    )
    missing = [task_id for task_id in canonical_ids if task_id not in body]
    assert not missing, (
        f"planner.md is missing canonical task id(s): {missing}. "
        "Spec §5.5.2 requires every run to emit these in `## Tasks`."
    )


def test_planner_prompt_marks_consolidate_as_required() -> None:
    """The planner prompt must mark ``consolidate`` as REQUIRED + lowest priority.

    Spec §5.5.4 makes ``consolidate`` mandatory; if the planner emits
    the rest of the plan but drops ``consolidate``, the orchestrator
    appends it deterministically. Marking it REQUIRED in the planner
    prompt avoids that fallback in the common case and gives the
    planner the language it needs to brief the task.
    """
    body = load_planner_prompt()
    assert "REQUIRED" in body, "planner.md must mark `consolidate` as REQUIRED (spec §5.5.4)."
    assert "consolidate" in body, "planner.md must reference the `consolidate` task id."


def test_consolidate_prompt_describes_cross_task_cleanup() -> None:
    """The consolidate prompt must orient the agent to cross-task cleanup, not new features.

    Spec §5.5.4 quotes the consolidation contract:
    "Read the entire `hydrogen/app/` tree. Look for: shared-component
    drift, conflicting design tokens, orphaned imports, broken links
    between pages, navigation paths that no longer match collection
    handles, and any verifier feedback from prior iterations that was
    deferred. Fix them in place. Do not introduce new features."

    The exact wording can drift; this test asserts the *intent*
    survives, not the verbatim quote.
    """
    body = load_consolidate_execute_prompt()
    must_mention = (
        "consolidat",  # consolidate / consolidation
        "drift",
        "deferred",
    )
    missing = [token for token in must_mention if token.lower() not in body.lower()]
    assert not missing, (
        f"consolidate_execute.md must orient the agent to cross-task "
        f"cleanup (spec §5.5.4). Missing key concept(s): {missing}."
    )
    # The body's wording wraps freely across lines. Normalise to a
    # single-spaced string before substring matching so a line break
    # between "introduce" and "new" does not flake the assertion.
    flat = " ".join(body.split())
    assert "do not introduce new" in flat.lower() or "no new features" in flat.lower(), (
        "consolidate_execute.md must forbid introducing new features (spec §5.5.4)."
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
