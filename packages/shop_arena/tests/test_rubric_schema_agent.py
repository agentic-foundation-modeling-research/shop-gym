"""Schema tests for the v1.3 ``level: agent_driven`` rubric entry.

Pinned to T1.3 of ``docs/impl/web_probe_v1_3_agent_driven_implementation.md``.
Verifies the inline ``agent_task`` block + ``probe`` XOR contract that
``RubricEntry`` enforces in ``shop_probe.rubric.schema``:

* an ``agent_driven`` entry with an inline block parses cleanly;
* an ``agent_driven`` entry without ``agent_task`` is rejected;
* a non-agent entry that smuggles in ``agent_task`` is rejected;
* a non-agent entry without a ``probe`` reference is rejected (regression
  for the now-optional ``RubricEntry.probe`` field).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shop_probe.rubric import AgentTaskInline, RubricEntry


def _agent_task_dict(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "goal": "Apply any one filter that narrows the visible product list.",
        "judge_prompt": "Did the visible product set narrow between BEFORE and AFTER?",
        "precondition_url_attr": "sample_collection_url",
    }
    base.update(overrides)
    return base


def _entry_dict(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "collection.filters.applies_to_results",
        "category": "collection",
        "level": "agent_driven",
        "weight": 2,
        "description": "Agent-driven filter narrows results.",
        "authenticated": False,
        "transactional": False,
        "agent_task": _agent_task_dict(),
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_agent_driven_entry_with_inline_block_parses() -> None:
    """An ``agent_driven`` entry with a fully populated inline block validates."""
    entry = RubricEntry.model_validate(_entry_dict())
    assert entry.level == "agent_driven"
    assert entry.probe is None
    assert isinstance(entry.agent_task, AgentTaskInline)
    assert entry.agent_task.goal.startswith("Apply any one filter")
    assert entry.agent_task.precondition_url_attr == "sample_collection_url"
    assert entry.agent_task.step_budget is None
    assert entry.agent_task.timeout_s is None


def test_agent_driven_entry_with_per_task_overrides_parses() -> None:
    """Optional ``step_budget`` / ``timeout_s`` overrides round-trip."""
    entry = RubricEntry.model_validate(
        _entry_dict(
            agent_task=_agent_task_dict(step_budget=20, timeout_s=240),
        )
    )
    assert entry.agent_task is not None
    assert entry.agent_task.step_budget == 20  # noqa: PLR2004
    assert entry.agent_task.timeout_s == 240  # noqa: PLR2004


# --------------------------------------------------------------------------- #
# Contract violations
# --------------------------------------------------------------------------- #


def test_agent_driven_entry_missing_agent_task_is_rejected() -> None:
    """``level: agent_driven`` without an inline ``agent_task`` block fails."""
    with pytest.raises(ValidationError) as exc:
        RubricEntry.model_validate(_entry_dict(agent_task=None))
    assert "agent_task" in str(exc.value)


def test_agent_driven_entry_with_probe_reference_is_rejected() -> None:
    """``agent_driven`` entries must not also carry a ``probe`` dotted ref."""
    with pytest.raises(ValidationError) as exc:
        RubricEntry.model_validate(
            _entry_dict(probe="probes.collection.filters_apply"),
        )
    assert "probe" in str(exc.value)


def test_core_entry_with_agent_task_is_rejected() -> None:
    """Non-agent levels must not smuggle in an inline ``agent_task`` block."""
    with pytest.raises(ValidationError) as exc:
        RubricEntry.model_validate(
            _entry_dict(
                id="collection.filters.sidebar",
                level="core",
                probe="probes.collection.has_sidebar_filters",
                agent_task=_agent_task_dict(),
            )
        )
    assert "agent_task" in str(exc.value)


def test_core_entry_without_probe_is_rejected() -> None:
    """Regression: ``probe`` is optional on the model, but required for non-agent levels."""
    with pytest.raises(ValidationError) as exc:
        RubricEntry.model_validate(
            _entry_dict(
                id="collection.filters.sidebar",
                level="core",
                probe=None,
                agent_task=None,
            )
        )
    assert "probe" in str(exc.value)
