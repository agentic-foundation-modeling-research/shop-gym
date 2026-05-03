"""Tests for the shop_guru.eval subpackage.

Covers:
- Loader filter semantics (shop / skill).
- Judge returns a parsed ``JudgementResult`` when the OpenAI client
  returns a valid JSON payload.
- ``ShopGuruBrowserTask`` setup + minimal ``validate()`` contract
  (terminal-role bookkeeping, budget exhaustion). The judge runs
  post-episode in ``score.load_episode`` and is covered by rule-gate tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from shop_guru.eval.judge import JudgementResult, judge_trace
from shop_guru.eval.loader import load_shopguru_tasks
from shop_guru.eval.score import _apply_rule_gate
from shop_guru.eval.task import ShopGuruBrowserTask

# ---------- loader ----------


def _write_shops_yml(path: Path, shops: list[dict[str, Any]]) -> None:
    path.write_text(yaml.safe_dump({"shops": shops}))


def _write_bench(dir_: Path, filename: str, tasks: list[dict[str, Any]]) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / filename).write_text(json.dumps(tasks))


@pytest.fixture
def agentlab_fixture(tmp_path: Path) -> dict[str, Any]:
    """Two shops, two skills each — one benchmark file per skill."""
    benchmarks_root = tmp_path / "root"
    shop_a_bench = benchmarks_root / "alpha" / "benchmarks"
    shop_b_bench = benchmarks_root / "beta" / "benchmarks"

    _write_bench(
        shop_a_bench,
        "ShopGuru_e2e_featured_v1.json",
        [{"id": "a-e2e-1", "intent": "buy hat", "url": "https://a.example", "type": "e2e"}],
    )
    _write_bench(
        shop_a_bench,
        "ShopGuru_prod_discovery_exact_featured_v1.json",
        [{"id": "a-pde-1", "intent": "find hat", "url": "https://a.example", "type": "pde"}],
    )
    _write_bench(
        shop_b_bench,
        "ShopGuru_e2e_featured_v1.json",
        [{"id": "b-e2e-1", "intent": "buy scarf", "url": "https://b.example", "type": "e2e"}],
    )

    config_path = tmp_path / "featured_v1.yml"
    _write_shops_yml(
        config_path,
        [
            {
                "slug": "alpha",
                "name": "Alpha",
                "shop_url": "https://a.example",
                "data_dir": "outputs/shops/a.example",
                "country": "US",
                "currency": "USD",
                "language": "en",
                "image_tag": "a-main",
            },
            {
                "slug": "beta",
                "name": "Beta",
                "shop_url": "https://b.example",
                "data_dir": "outputs/shops/b.example",
                "country": "US",
                "currency": "USD",
                "language": "en",
                "image_tag": "b-main",
            },
        ],
    )
    return {"config": config_path, "root": benchmarks_root}


def test_loader_filters_by_shop_skill(agentlab_fixture: dict[str, Any]) -> None:
    # No filters: both shops, both skills → 3 tasks.
    all_tasks = load_shopguru_tasks(
        config_path=agentlab_fixture["config"],
        benchmarks_root=agentlab_fixture["root"],
    )
    assert {t["id"] for t in all_tasks} == {"a-e2e-1", "a-pde-1", "b-e2e-1"}
    assert all(t["shop_slug"] in {"alpha", "beta"} for t in all_tasks)

    # Shop filter.
    alpha_only = load_shopguru_tasks(
        config_path=agentlab_fixture["config"],
        benchmarks_root=agentlab_fixture["root"],
        shops=["alpha"],
    )
    assert {t["id"] for t in alpha_only} == {"a-e2e-1", "a-pde-1"}

    # Skill filter.
    e2e_only = load_shopguru_tasks(
        config_path=agentlab_fixture["config"],
        benchmarks_root=agentlab_fixture["root"],
        skills=["e2e"],
    )
    assert {t["id"] for t in e2e_only} == {"a-e2e-1", "b-e2e-1"}
    assert all(t["skill"] == "e2e" for t in e2e_only)


def test_loader_raises_on_unknown_task_id(agentlab_fixture: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="not found"):
        load_shopguru_tasks(
            config_path=agentlab_fixture["config"],
            benchmarks_root=agentlab_fixture["root"],
            task_ids=["does-not-exist"],
        )


# ---------- judge ----------


def _fake_openai_response(payload: dict[str, Any]) -> MagicMock:
    choice = MagicMock()
    choice.message.content = json.dumps(payload)
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_judge_trace_success() -> None:
    payload = {
        "reasoning": "all good",
        "verdict": True,
        "failure_reason": "",
        "impossible_task": False,
        "reached_captcha": False,
    }

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_openai_response(payload)

    with patch("openai.OpenAI", return_value=fake_client):
        result = judge_trace(
            task="buy a hat",
            final_result="done, hat added to cart",
            agent_steps=["[user] buy a hat", "[assistant] done"],
            screenshots_b64=["aGVsbG8="],  # "hello"
            model="gpt-5",
            base_url="https://example.test/v1",
            api_key="sk-test",
        )

    assert isinstance(result, JudgementResult)
    assert result.verdict is True
    assert result.reasoning == "all good"

    # Verify the call was made with JSON mode + a multimodal user message.
    call = fake_client.chat.completions.create.call_args
    assert call.kwargs["model"] == "gpt-5"
    assert call.kwargs["response_format"] == {"type": "json_object"}
    user_content = call.kwargs["messages"][1]["content"]
    assert any(c.get("type") == "image_url" for c in user_content)


def test_judge_trace_returns_false_on_llm_error() -> None:
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("proxy exploded")

    with patch("openai.OpenAI", return_value=fake_client):
        result = judge_trace(
            task="buy a hat",
            final_result="",
            agent_steps=[],
            screenshots_b64=[],
            model="gpt-5",
            base_url="https://example.test/v1",
            api_key="sk-test",
        )
    assert result.verdict is False
    assert "proxy exploded" in (result.failure_reason or "")


# ---------- rule gate ----------


def test_rule_gate_infeasible_expected_and_agent_refused() -> None:
    result = _apply_rule_gate(
        success_criteria={"expected_outcome": "infeasible", "url_contains": "/x"},
        url_trajectory=[],
        terminal_role="infeasible",
        model_used="gpt-5",
    )
    assert result is not None
    assert result.verdict is True


def test_rule_gate_infeasible_expected_but_agent_did_not_refuse() -> None:
    result = _apply_rule_gate(
        success_criteria={
            "expected_outcome": "infeasible",
            "url_contains": "/x",
            "infeasible_reason": "filter facet missing",
        },
        url_trajectory=[(0, "https://shop/x")],
        terminal_role="assistant",
        model_used="gpt-5",
    )
    assert result is not None
    assert result.verdict is False
    assert result.failure_reason == "filter facet missing"


def test_rule_gate_url_contains_miss_fails_without_llm() -> None:
    result = _apply_rule_gate(
        success_criteria={"url_contains": "/cart"},
        url_trajectory=[(0, "https://shop/"), (1, "https://shop/products/p1")],
        terminal_role="assistant",
        model_used="gpt-5",
    )
    assert result is not None
    assert result.verdict is False
    assert "/cart" in (result.failure_reason or "")


def test_rule_gate_url_contains_hit_defers_to_llm() -> None:
    result = _apply_rule_gate(
        success_criteria={"url_contains": "/cart"},
        url_trajectory=[(0, "https://shop/"), (1, "https://shop/cart")],
        terminal_role="assistant",
        model_used="gpt-5",
    )
    assert result is None


def test_rule_gate_no_success_criteria_defers_to_llm() -> None:
    result = _apply_rule_gate(
        success_criteria=None,
        url_trajectory=[(0, "https://shop/")],
        terminal_role="assistant",
        model_used="gpt-5",
    )
    assert result is None


# ---------- ShopGuruBrowserTask ----------


class _FakePage:
    """Minimal playwright.Page stand-in for unit tests."""

    def __init__(self) -> None:
        self.goto_url: str | None = None

    def goto(self, url: str, timeout: int = 0) -> None:
        self.goto_url = url


def _make_task(max_steps: int | None = None) -> ShopGuruBrowserTask:
    return ShopGuruBrowserTask(
        seed=0,
        shop_task={
            "id": "tiny-1",
            "intent": "buy a red hat",
            "url": "https://tiny.example",
            "type": "e2e",
        },
        max_steps=max_steps,
    )


def test_shopguru_browser_task_setup_navigates_and_returns_goal() -> None:
    task = _make_task()
    page = _FakePage()

    goal, info = task.setup(page)

    assert goal == "buy a red hat"
    assert page.goto_url == "https://tiny.example"
    assert info == {"shopguru_task_id": "tiny-1", "shopguru_task_type": "e2e"}


def test_shopguru_browser_task_not_done_until_terminal_role() -> None:
    task = _make_task()
    page = _FakePage()
    task.setup(page)

    # User-only messages: not terminal — empty extra, no bookkeeping leaked.
    reward, done, msg, extra = task.validate(
        page, [{"role": "user", "message": "buy a red hat"}]
    )
    assert (reward, done, msg, extra) == (0.0, False, "", {})

    reward, done, _, extra = task.validate(
        page,
        [
            {"role": "user", "message": "buy a red hat"},
            {"role": "user", "message": "another user nudge"},
        ],
    )
    assert (reward, done, extra) == (0.0, False, {})


def test_shopguru_browser_task_assistant_message_terminates() -> None:
    task = _make_task(max_steps=10)
    page = _FakePage()
    task.setup(page)

    reward, done, msg, info = task.validate(
        page,
        [
            {"role": "user", "message": "buy a red hat"},
            {"role": "assistant", "message": "added to cart, done."},
        ],
    )

    # No inline judge → reward stays 0.0; the post-episode hook scores.
    assert (reward, done, msg) == (0.0, True, "")
    assert info == {
        "forced_by_budget": False,
        "terminal_role": "assistant",
        "n_validate_calls": 1,
        "max_steps": 10,
        "shopguru_task_id": "tiny-1",
        "shopguru_task_type": "e2e",
    }


def test_shopguru_browser_task_infeasible_message_terminates() -> None:
    task = _make_task()
    page = _FakePage()
    task.setup(page)

    reward, done, _, info = task.validate(
        page, [{"role": "infeasible", "message": "site requires login"}]
    )

    assert (reward, done) == (0.0, True)
    assert info["terminal_role"] == "infeasible"
    assert info["forced_by_budget"] is False


def test_shopguru_browser_task_budget_exhaustion_terminates() -> None:
    task = _make_task(max_steps=2)
    page = _FakePage()
    task.setup(page)

    # First non-terminal call: under budget — not done.
    reward, done, _, extra = task.validate(
        page, [{"role": "user", "message": "keep going"}]
    )
    assert (reward, done, extra) == (0.0, False, {})

    # Second non-terminal call: hits max_steps — forced terminal.
    reward, done, _, info = task.validate(
        page, [{"role": "user", "message": "keep going"}]
    )
    assert (reward, done) == (0.0, True)
    assert info["terminal_role"] == "budget"
    assert info["forced_by_budget"] is True
    assert info["n_validate_calls"] == 2
    assert info["max_steps"] == 2
