"""End-to-end tests for the ``--agent-*`` CLI flags (impl plan T6.4).

The flags introduced in T6.1 plumb the v1.3 agent-driven runtime configuration
from ``shop-probe run`` / ``shop-probe eval`` into every spawned probe. These
tests pin three contracts:

* a ``v1.1`` rubric run with default flags issues **zero** Anthropic calls —
  ``run_agent_task`` and ``AsyncAnthropic`` are never reached because the
  rubric carries no ``agent_driven`` entries;
* a ``v1.3`` rubric run forwards every ``--agent-*`` flag into the
  :class:`AgentRuntimeConfig` attached to ``ProbeContext.agent_config`` that
  ``run_agent_task`` observes;
* ``shop-probe eval`` forwards the same flags into the ``argparse.Namespace``
  it builds for each spawned ``run`` invocation.

All Anthropic / harness side effects are stubbed; the SandboxShop fixture
serves the storefront so the deterministic v1.1 entries can complete via
real Playwright.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from shop_probe import cli
from shop_probe.agent import judge as judge_module
from shop_probe.agent import runner as agent_runner_module
from shop_probe.agent.config import AgentRuntimeConfig
from shop_probe.cli import EXIT_OK, main
from shop_probe.probes._runner import ProbeContext, ProbeOutcome
from shop_probe.report import BrowserMeta, CategoryScore, ProbeReport
from shop_probe.targets import Target

# `tests/` is on sys.path via pytest's rootdir; `_sandbox.py` lives there.
_TESTS_ROOT = Path(__file__).resolve().parent
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from _sandbox import SandboxShop  # noqa: E402 — sys.path adjustment above


def _run_args(
    base_url: str,
    out_root: Path,
    *,
    rubric: str,
    extra: list[str] | None = None,
) -> list[str]:
    return [
        "run",
        base_url,
        "--name",
        "fixture",
        "--label",
        "sandbox",
        "--rubric",
        rubric,
        "--axes",
        "A",
        "--out",
        str(out_root),
        *(extra or []),
    ]


def test_cli_run_v1_1_default_flags_make_no_anthropic_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--rubric v1.1`` + default ``--agent-*`` flags issue zero Anthropic calls.

    The v1.1 rubric carries no ``agent_driven`` entries, so the dispatcher
    must never reach :func:`run_agent_task` (which is the only path that
    constructs an :class:`AsyncAnthropic` client via the completion judge).
    Both are monkey-patched to fail loudly on touch.
    """

    async def _exploding_run_agent_task(*_args: Any, **_kwargs: Any) -> ProbeOutcome:
        pytest.fail("run_agent_task must not be invoked for v1.1 (no agent_driven entries)")

    class _ExplodingAnthropic:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pytest.fail("AsyncAnthropic must not be constructed for v1.1")

    monkeypatch.setattr(agent_runner_module, "run_agent_task", _exploding_run_agent_task)
    # Patch on the agent.judge module where ``AsyncAnthropic`` is imported + used.
    monkeypatch.setattr(judge_module, "AsyncAnthropic", _ExplodingAnthropic)

    with SandboxShop() as base_url:
        rc = main(_run_args(base_url, tmp_path, rubric="v1.1"))

    assert rc == EXIT_OK


def test_cli_run_v1_3_forwards_agent_flags_into_probe_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--rubric v1.3`` threads every ``--agent-*`` flag through to ``run_agent_task``.

    Stubs :func:`run_agent_task` so the agent-driven entries short-circuit
    without spawning a harness loop, and asserts ``ctx.agent_config`` carries
    the exact :class:`AgentRuntimeConfig` the CLI built from the flags.
    """
    captured_configs: list[AgentRuntimeConfig | None] = []

    async def _stub_run_agent_task(_page: Any, ctx: ProbeContext, *, task: Any) -> ProbeOutcome:
        del task  # signature-only; the inline rubric block is opaque to this test.
        captured_configs.append(ctx.agent_config)
        return ProbeOutcome(passed=True, notes="stub")

    monkeypatch.setattr(agent_runner_module, "run_agent_task", _stub_run_agent_task)

    extra_flags = [
        "--agent-runtime",
        "pi",
        "--agent-model",
        "claude-sonnet-4-6",
        "--agent-step-budget",
        "5",
        "--agent-timeout-s",
        "90",
        "--agent-judge-model",
        "claude-haiku-test",
    ]

    with SandboxShop() as base_url:
        rc = main(
            _run_args(base_url, tmp_path, rubric="v1.3", extra=extra_flags),
        )

    assert rc == EXIT_OK
    # v1.3 has 8 agent-driven entries; all are unauthenticated + non-transactional
    # so the default include-auth=False filter keeps every one of them.
    assert len(captured_configs) == 8  # noqa: PLR2004 — pinned by v1.3 rubric.

    expected = AgentRuntimeConfig(
        runtime="pi",
        model="claude-sonnet-4-6",
        step_budget=5,
        timeout_s=90,
        judge_model="claude-haiku-test",
    )
    for cfg in captured_configs:
        assert cfg == expected


def test_cli_eval_forwards_agent_flags_into_spawned_run_invocations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``shop-probe eval`` propagates every ``--agent-*`` flag into each ``run`` call.

    Stubs :func:`shop_probe.cli._cmd_run` (the in-process callee that ``eval``
    delegates to) and inspects the :class:`argparse.Namespace` it receives.
    """
    benchmark_yaml = tmp_path / "benchmark.yaml"
    benchmark_yaml.write_text(
        "\n".join(
            [
                'version: "0.1"',
                "sandboxes:",
                "  - { name: shop_alpha, base_url: http://localhost:4000, label: sandbox }",
                "reals:",
                "  - { name: real_a, base_url: https://real-a.example.invalid, label: real }",
                "",
            ]
        ),
        encoding="utf-8",
    )
    out_root = tmp_path / "out"

    captured_args: list[argparse.Namespace] = []

    def _stub_cmd_run(args: argparse.Namespace) -> int:
        captured_args.append(args)
        # Write a minimal stand-in report so ``_cmd_report`` (called at the
        # end of ``_cmd_eval``) can pick it up.
        runtime = BrowserMeta(
            python_version="3.12.0",
            playwright_version="1.0.0",
            chromium_version="100",
            user_agent="ShopProbe/test",
            viewport=(1280, 800),
            headless=True,
        )
        report = ProbeReport(
            target=Target(name=args.name, base_url=args.base_url, label=args.label),
            rubric_version="v1.3",
            rubric_hash="b" * 64,
            runner_version="0.0.0",
            runtime=runtime,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            categories=(
                CategoryScore(
                    category="collection",
                    weight_passed=1.0,
                    weight_total=1.0,
                    coverage=1.0,
                ),
            ),
            coverage_core=1.0,
            coverage_modern=1.0,
            coverage_advanced=1.0,
            coverage_weighted=1.0,
            rerun_index=args.rerun_index,
        )
        out_path = (
            Path(args.out) / "reports" / f"{args.label}__{args.name}__rerun{args.rerun_index}.json"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return EXIT_OK

    monkeypatch.setattr(cli, "_cmd_run", _stub_cmd_run)

    rc = main(
        [
            "eval",
            "--benchmark",
            str(benchmark_yaml),
            "--out",
            str(out_root),
            "--reruns",
            "1",
            "--rubric",
            "v1.3",
            "--agent-runtime",
            "pi",
            "--agent-model",
            "claude-sonnet-4-6",
            "--agent-step-budget",
            "7",
            "--agent-timeout-s",
            "120",
            "--agent-judge-model",
            "claude-haiku-test",
        ]
    )

    assert rc == EXIT_OK
    # Bench has 1 sandbox + 1 real; reruns=1 → 2 ``run`` invocations.
    assert len(captured_args) == 2  # noqa: PLR2004
    for ns in captured_args:
        assert ns.agent_runtime == "pi"
        assert ns.agent_model == "claude-sonnet-4-6"
        assert ns.agent_step_budget == 7  # noqa: PLR2004
        assert ns.agent_timeout_s == 120  # noqa: PLR2004
        assert ns.agent_judge_model == "claude-haiku-test"
        assert ns.rubric == "v1.3"
