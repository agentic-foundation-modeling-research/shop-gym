"""Hermetic tests for ``ProbeRunner.run_agent_entry`` (T4.2).

The dispatcher sits between the per-cohort entry loop in
``shop_probe.cli`` and the generic agent task runner in
``shop_probe.agent.runner``. This test pins its contract:

* ``run_agent_entry`` rejects non-``agent_driven`` entries up front.
* The outer wait budget equals
  ``(task.timeout_s or DEFAULT_AGENT_TIMEOUT_S) + AGENT_BUFFER_S`` and is
  threaded into the inner :meth:`ProbeRunner.run` call as ``timeout_s``.
* The runner-owned closure delegates to
  :func:`shop_probe.agent.runner.run_agent_task` with the entry's inline
  :class:`AgentTaskInline` block and the live ``page`` / ``ctx``.
* The dispatcher forwards ``base_url`` / ``sample_*`` / ``agent_config``
  onto :meth:`ProbeRunner.run` verbatim and surfaces its
  :class:`ProbeOutcome` to the caller.

Stubs replace :meth:`ProbeRunner.run` and ``run_agent_task`` so the test
needs neither Playwright nor a live harness.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from shop_probe.agent import runner as agent_runner_module
from shop_probe.agent.config import AgentRuntimeConfig
from shop_probe.probes._runner import (
    AGENT_BUFFER_S,
    DEFAULT_AGENT_TIMEOUT_S,
    ProbeContext,
    ProbeFn,
    ProbeOutcome,
    ProbeRunner,
)
from shop_probe.rubric.schema import AgentTaskInline, RubricEntry


def _agent_entry(
    *,
    entry_id: str = "collection.filters.applies_to_results",
    timeout_s: int | None = None,
    step_budget: int | None = None,
) -> RubricEntry:
    """Build an agent-driven rubric entry with sensible defaults."""
    task_data: dict[str, Any] = {
        "goal": "Apply any one filter that narrows the visible product list.",
        "judge_prompt": "Did the visible product set narrow?",
        "precondition_url_attr": "sample_collection_url",
    }
    if timeout_s is not None:
        task_data["timeout_s"] = timeout_s
    if step_budget is not None:
        task_data["step_budget"] = step_budget
    return RubricEntry.model_validate(
        {
            "id": entry_id,
            "category": "collection",
            "level": "agent_driven",
            "weight": 2,
            "description": "Agent-driven — filter narrows visible products.",
            "authenticated": False,
            "transactional": False,
            "agent_task": task_data,
        }
    )


def _make_runner(tmp_path: Path) -> ProbeRunner:
    """Construct a runner without entering its async-context (no browser)."""
    return ProbeRunner(evidence_root=tmp_path / "evidence")


def test_run_agent_entry_rejects_non_agent_driven_entries(tmp_path: Path) -> None:
    """Deterministic entries must not flow through the agent dispatcher."""
    runner = _make_runner(tmp_path)
    deterministic = RubricEntry.model_validate(
        {
            "id": "site_shell.header.sticky",
            "category": "site_shell",
            "level": "core",
            "weight": 1,
            "probe": "probes.site_shell.header_is_sticky",
            "description": "Sticky header probe.",
            "authenticated": False,
            "transactional": False,
        }
    )

    async def _go() -> None:
        with pytest.raises(ValueError, match="agent_driven"):
            await runner.run_agent_entry(
                deterministic,
                base_url="http://localhost",
            )

    asyncio.run(_go())


def test_run_agent_entry_forwards_call_to_run_with_buffered_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outer wait = task.timeout_s + AGENT_BUFFER_S; ``run`` gets all kwargs."""
    runner = _make_runner(tmp_path)
    entry = _agent_entry(timeout_s=90)
    expected_outcome = ProbeOutcome(passed=True, notes="stub-verdict")

    captured: dict[str, Any] = {}

    async def _stub_run(
        probe: ProbeFn,
        *,
        base_url: str,
        probe_id: str,
        sample_product_url: str | None = None,
        sample_collection_url: str | None = None,
        timeout_s: float | None = None,
        agent_config: AgentRuntimeConfig | None = None,
    ) -> ProbeOutcome:
        captured.update(
            {
                "probe": probe,
                "base_url": base_url,
                "probe_id": probe_id,
                "sample_product_url": sample_product_url,
                "sample_collection_url": sample_collection_url,
                "timeout_s": timeout_s,
                "agent_config": agent_config,
            }
        )
        return expected_outcome

    monkeypatch.setattr(runner, "run", _stub_run)

    cfg = AgentRuntimeConfig(step_budget=5, timeout_s=90)

    async def _go() -> ProbeOutcome:
        return await runner.run_agent_entry(
            entry,
            base_url="http://localhost:4000",
            sample_product_url="http://localhost:4000/products/p1",
            sample_collection_url="http://localhost:4000/collections/c1",
            agent_config=cfg,
        )

    outcome = asyncio.run(_go())

    assert outcome is expected_outcome
    assert captured["base_url"] == "http://localhost:4000"
    assert captured["probe_id"] == entry.id
    assert captured["sample_product_url"] == "http://localhost:4000/products/p1"
    assert captured["sample_collection_url"] == "http://localhost:4000/collections/c1"
    assert captured["agent_config"] is cfg
    assert captured["timeout_s"] == pytest.approx(90 + AGENT_BUFFER_S)


def test_run_agent_entry_uses_default_timeout_when_task_omits_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``task.timeout_s = None`` falls back to ``DEFAULT_AGENT_TIMEOUT_S``."""
    runner = _make_runner(tmp_path)
    entry = _agent_entry(timeout_s=None)

    captured: dict[str, Any] = {}

    async def _stub_run(probe: ProbeFn, **kwargs: Any) -> ProbeOutcome:
        captured["timeout_s"] = kwargs["timeout_s"]
        return ProbeOutcome(passed=True)

    monkeypatch.setattr(runner, "run", _stub_run)

    asyncio.run(
        runner.run_agent_entry(entry, base_url="http://localhost"),
    )

    assert captured["timeout_s"] == pytest.approx(
        DEFAULT_AGENT_TIMEOUT_S + AGENT_BUFFER_S,
    )


def test_run_agent_entry_closure_calls_run_agent_task_with_inline_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The captured closure delegates to ``run_agent_task`` verbatim."""
    runner = _make_runner(tmp_path)
    entry = _agent_entry()
    expected = ProbeOutcome(passed=False, notes="judge-said-no")

    captured_probe: list[ProbeFn] = []

    async def _stub_run(probe: ProbeFn, **_kwargs: Any) -> ProbeOutcome:
        captured_probe.append(probe)
        return ProbeOutcome(passed=True)

    monkeypatch.setattr(runner, "run", _stub_run)

    captured_task: list[AgentTaskInline] = []
    captured_args: list[tuple[Any, Any]] = []

    async def _stub_run_agent_task(
        page: Any,
        ctx: Any,
        *,
        task: AgentTaskInline,
    ) -> ProbeOutcome:
        captured_args.append((page, ctx))
        captured_task.append(task)
        return expected

    monkeypatch.setattr(
        agent_runner_module,
        "run_agent_task",
        _stub_run_agent_task,
    )

    asyncio.run(
        runner.run_agent_entry(entry, base_url="http://localhost"),
    )

    assert len(captured_probe) == 1
    closure = captured_probe[0]

    sentinel_page = object()
    sentinel_ctx = ProbeContext(
        page=sentinel_page,  # type: ignore[arg-type]
        base_url="http://localhost",
        probe_id=entry.id,
        evidence_root=tmp_path / "evidence",
    )
    outcome = asyncio.run(closure(sentinel_page, sentinel_ctx))  # type: ignore[arg-type]

    assert outcome is expected
    assert captured_task == [entry.agent_task]
    assert captured_args == [(sentinel_page, sentinel_ctx)]
