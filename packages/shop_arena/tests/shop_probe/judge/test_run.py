"""Tests for `shop_probe.judge.run` (web_probe_patch.md).

Covers:

* :func:`render_trajectory_for_judge` refuses un-anonymized trajectories
  and renders an anonymized trajectory to the pinned text format.
* :func:`classify_trajectory` invokes the classifier callable and
  projects its return into a closed :class:`JudgeCall`.
* :func:`classify_shop` runs the classifier ``samples`` times and
  preserves order.
* :func:`judge_calls_from_results` projects classifier results to
  :class:`JudgeCall` rows and rejects invalid labels.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from shop_probe.judge.run import (
    ClassifierResult,
    classify_shop,
    classify_trajectory,
    judge_calls_from_results,
    render_trajectory_for_judge,
)
from shop_probe.judge.trajectory import (
    Trajectory,
    TrajectoryAction,
    TrajectoryObservation,
    TrajectoryStep,
)
from shop_probe.report import BrowserMeta, EvidenceRef
from shop_probe.targets import Target

_PROMPT_HASH = "b" * 64
_TIMESTAMP = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11",
        playwright_version="1.48",
        chromium_version="129",
        user_agent="ShopProbe/0.1",
        viewport=(1280, 800),
        headless=True,
    )


def _trajectory(*, anonymized: bool = True) -> Trajectory:
    target = Target(name="shop_alpha", base_url="http://localhost:4000", label="sandbox")
    step0 = TrajectoryStep(
        index=0,
        action=TrajectoryAction(
            kind="navigate",
            value="http://localhost:4000/",
            description="Navigate to the homepage.",
        ),
        observation=TrajectoryObservation(
            url="http://localhost:4000/",
            title=None,
            screenshot=EvidenceRef(kind="screenshot", path="iters/00/screenshot.png"),
            a11y_snapshot=EvidenceRef(kind="a11y_snapshot", path="iters/00/a11y.json"),
        ),
        reasoning="open homepage",
        duration_ms=200,
    )
    step1 = TrajectoryStep(
        index=1,
        action=TrajectoryAction(
            kind="click",
            selector='a[href="/products/x"]',
            description="Click the first product card.",
        ),
        observation=TrajectoryObservation(
            url="http://localhost:4000/products/x",
            title=None,
            screenshot=EvidenceRef(kind="screenshot", path="iters/01/screenshot.png"),
            a11y_snapshot=EvidenceRef(kind="a11y_snapshot", path="iters/01/a11y.json"),
        ),
        reasoning="",
        duration_ms=300,
    )
    return Trajectory(
        target=target,
        task_id="t01_browse",
        runner_version="0.0.0",
        runtime=_browser_meta(),
        started_at=_TIMESTAMP,
        ended_at=_TIMESTAMP + timedelta(seconds=10),
        steps=(step0, step1),
        har=None,
        final_status="completed",
        anonymized=anonymized,
        notes=None,
    )


def _result(predicted: str = "sandbox") -> ClassifierResult:
    return ClassifierResult(
        predicted_label=predicted,
        prompt_hash=_PROMPT_HASH,
        response="picked it",
        latency_ms=42.0,
        cost_usd=0.001,
        model_id="gpt-stub",
    )


# --------------------------------------------------------------------------- #
# render_trajectory_for_judge.
# --------------------------------------------------------------------------- #


def test_render_includes_target_header_and_step_lines() -> None:
    text = render_trajectory_for_judge(_trajectory())
    assert "target: shop_alpha" in text
    assert "step_00: Navigate to the homepage." in text
    assert "step_01: Click the first product card." in text
    assert "screenshot_00: iters/00/screenshot.png" in text
    assert "snapshot_00: iters/00/a11y.json" in text
    assert "screenshot_01: iters/01/screenshot.png" in text


def test_render_appends_observation_url_to_step_head() -> None:
    text = render_trajectory_for_judge(_trajectory())
    assert "step_00: Navigate to the homepage. -> http://localhost:4000/" in text


def test_render_omits_reasoning_when_empty() -> None:
    text = render_trajectory_for_judge(_trajectory())
    # Step 0 has reasoning = "open homepage"; step 1 has empty reasoning.
    assert "reasoning: open homepage" in text
    # No reasoning line for step 1.
    step1_block = text.split("step_01:")[1]
    assert "reasoning:" not in step1_block


def test_render_rejects_unanonymized_trajectory() -> None:
    with pytest.raises(ValueError, match="anonymized trajectory"):
        render_trajectory_for_judge(_trajectory(anonymized=False))


# --------------------------------------------------------------------------- #
# classify_trajectory + classify_shop.
# --------------------------------------------------------------------------- #


def test_classify_trajectory_returns_judge_call() -> None:
    captured: list[str] = []

    def classifier(rendered: str) -> ClassifierResult:
        captured.append(rendered)
        return _result("sandbox")

    call = classify_trajectory(_trajectory(), classifier)
    assert call.predicted_label == "sandbox"
    assert call.prompt_hash == _PROMPT_HASH
    assert call.model_id == "gpt-stub"
    assert "target: shop_alpha" in captured[0]


def test_classify_trajectory_rejects_invalid_label() -> None:
    def classifier(rendered: str) -> ClassifierResult:
        del rendered
        return ClassifierResult(
            predicted_label="bogus",
            prompt_hash=_PROMPT_HASH,
            response="r",
            latency_ms=0.0,
            cost_usd=0.0,
            model_id="m",
        )

    with pytest.raises(ValueError, match="invalid"):
        classify_trajectory(_trajectory(), classifier)


def test_classify_shop_runs_classifier_n_times() -> None:
    counter = {"n": 0}

    def classifier(rendered: str) -> ClassifierResult:
        del rendered
        counter["n"] += 1
        return _result("sandbox" if counter["n"] % 2 else "real")

    calls = classify_shop(_trajectory(), classifier, samples=4)
    assert len(calls) == 4  # noqa: PLR2004
    assert [c.predicted_label for c in calls] == ["sandbox", "real", "sandbox", "real"]


def test_classify_shop_rejects_zero_samples() -> None:
    def classifier(rendered: str) -> ClassifierResult:
        del rendered
        return _result()

    with pytest.raises(ValueError, match="samples"):
        classify_shop(_trajectory(), classifier, samples=0)


# --------------------------------------------------------------------------- #
# judge_calls_from_results.
# --------------------------------------------------------------------------- #


def test_judge_calls_from_results_projects_each_row() -> None:
    out = judge_calls_from_results((_result("sandbox"), _result("real"), _result("abstain")))
    assert tuple(c.predicted_label for c in out) == ("sandbox", "real", "abstain")


def test_judge_calls_from_results_rejects_invalid_label() -> None:
    bad = ClassifierResult(
        predicted_label="bogus",
        prompt_hash=_PROMPT_HASH,
        response="r",
        latency_ms=0.0,
        cost_usd=0.0,
        model_id="m",
    )
    with pytest.raises(ValueError, match="invalid"):
        judge_calls_from_results((bad,))
