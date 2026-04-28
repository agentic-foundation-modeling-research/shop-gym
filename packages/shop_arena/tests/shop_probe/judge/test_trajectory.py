"""Tests for `shop_probe.judge.trajectory` (T4.1 acceptance — spec §5.5).

Covers:

* JSON / dict round-trip for every closed schema in the module
  (``TrajectoryAction``, ``TrajectoryObservation``, ``TrajectoryStep``,
  ``Trajectory``) — this is the contract the blinded pairwise judge
  reads from.
* ``extra="forbid"`` unknown-field rejection on every model, so
  judge-input drift surfaces at validation time rather than as a silent
  scoring regression.
* The required-field invariants from spec §5.5 step 2: every
  ``TrajectoryObservation`` carries a screenshot AND an a11y snapshot;
  every ``TrajectoryStep`` carries an ``action`` + ``observation``.
* Numeric / temporal constraints: ``index``/``duration_ms`` non-negative,
  ``ended_at >= started_at``.
* Anonymization-state preservation across round-trips (the spec §5.5
  step 3 ``anonymized`` flag must survive serialization).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from shop_probe.judge.trajectory import (
    Trajectory,
    TrajectoryAction,
    TrajectoryObservation,
    TrajectoryStep,
)
from shop_probe.report import BrowserMeta, EvidenceRef
from shop_probe.targets import Target

# --------------------------------------------------------------------------- #
# Fixture builders — kept close to the spec §5.5 / §8.3 examples so the tests
# double as documentation of the wire format the judge prompt consumes.
# --------------------------------------------------------------------------- #

_SANDBOX_TARGET: Target = Target(
    label="sandbox/1_run123",
    base_url="http://localhost:4000",
    kind="sandbox",
    pair_id="pair_1",
)

_STARTED_AT: datetime = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
_ENDED_AT: datetime = _STARTED_AT + timedelta(seconds=42)


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.1 (Chromium/129)",
        viewport=(1280, 800),
        headless=True,
    )


def _screenshot_ref(idx: int) -> EvidenceRef:
    return EvidenceRef(
        kind="screenshot",
        path=f"trajectories/t01/step_{idx:03d}/viewport.png",
    )


def _a11y_ref(idx: int) -> EvidenceRef:
    return EvidenceRef(
        kind="a11y_snapshot",
        path=f"trajectories/t01/step_{idx:03d}/a11y.json",
    )


def _action() -> TrajectoryAction:
    return TrajectoryAction(
        kind="click",
        selector='button[name="add"]',
        value=None,
        description="Click the add-to-cart button on the product detail page.",
    )


def _observation(idx: int = 0) -> TrajectoryObservation:
    return TrajectoryObservation(
        url="http://localhost:4000/cart",
        title="Your cart — FixtureShop",
        screenshot=_screenshot_ref(idx),
        a11y_snapshot=_a11y_ref(idx),
    )


def _step(idx: int = 0) -> TrajectoryStep:
    return TrajectoryStep(
        index=idx,
        action=_action(),
        observation=_observation(idx),
        reasoning="The PDP shows an enabled add-to-cart button; click it.",
        duration_ms=812,
    )


def _trajectory(**overrides: object) -> Trajectory:
    base: dict[str, object] = {
        "target": _SANDBOX_TARGET,
        "task_id": "t01_filter_open_pdp_add_to_cart",
        "runner_version": "0.0.0",
        "runtime": _browser_meta(),
        "started_at": _STARTED_AT,
        "ended_at": _ENDED_AT,
        "steps": (_step(0), _step(1)),
        "har": EvidenceRef(kind="har", path="trajectories/t01/run.har"),
        "final_status": "completed",
        "anonymized": False,
        "notes": None,
    }
    base.update(overrides)
    return Trajectory.model_validate(base)


# --------------------------------------------------------------------------- #
# JSON round-trip — every schema must survive dump → load unchanged.
# --------------------------------------------------------------------------- #


def test_trajectory_action_json_round_trip() -> None:
    action = _action()
    assert TrajectoryAction.model_validate_json(action.model_dump_json()) == action


def test_trajectory_action_navigate_has_no_selector() -> None:
    action = TrajectoryAction(
        kind="navigate",
        value="http://localhost:4000/collections/all",
        description="Navigate to the All collection.",
    )
    assert action.selector is None
    assert TrajectoryAction.model_validate_json(action.model_dump_json()) == action


def test_trajectory_observation_json_round_trip() -> None:
    obs = _observation()
    assert TrajectoryObservation.model_validate_json(obs.model_dump_json()) == obs


def test_trajectory_observation_url_and_title_optional() -> None:
    obs = TrajectoryObservation(
        screenshot=_screenshot_ref(0),
        a11y_snapshot=_a11y_ref(0),
    )
    assert obs.url is None
    assert obs.title is None
    assert TrajectoryObservation.model_validate_json(obs.model_dump_json()) == obs


def test_trajectory_step_json_round_trip() -> None:
    step = _step(7)
    assert TrajectoryStep.model_validate_json(step.model_dump_json()) == step


def test_trajectory_step_reasoning_defaults_to_empty() -> None:
    step = TrajectoryStep(
        index=0,
        action=_action(),
        observation=_observation(),
        duration_ms=200,
    )
    assert step.reasoning == ""
    assert TrajectoryStep.model_validate_json(step.model_dump_json()) == step


def test_trajectory_json_round_trip_full() -> None:
    traj = _trajectory()
    assert Trajectory.model_validate_json(traj.model_dump_json()) == traj


def test_trajectory_dict_round_trip_normalises_via_json() -> None:
    # Pydantic dumps tuples as Python tuples in `model_dump`; the canonical
    # wire format is JSON, where tuples become lists. Both round-trips must
    # reconstruct an equal model so reviewers can re-load from disk.
    traj = _trajectory()
    assert Trajectory.model_validate(traj.model_dump()) == traj


def test_trajectory_empty_steps_is_valid() -> None:
    """Trajectories that timed out before the first action still validate."""
    traj = _trajectory(steps=(), final_status="timeout")
    assert traj.steps == ()
    assert Trajectory.model_validate_json(traj.model_dump_json()) == traj


def test_trajectory_har_optional() -> None:
    traj = _trajectory(har=None)
    assert traj.har is None
    assert Trajectory.model_validate_json(traj.model_dump_json()) == traj


def test_trajectory_anonymized_flag_round_trips() -> None:
    """Spec §5.5 step 3: the anonymized flag is what the judge gates on."""
    traj = _trajectory(anonymized=True)
    payload = json.loads(traj.model_dump_json())
    assert payload["anonymized"] is True
    assert Trajectory.model_validate_json(traj.model_dump_json()).anonymized is True


# --------------------------------------------------------------------------- #
# Unknown-field rejection — closed schemas reject typos on every model.
# --------------------------------------------------------------------------- #


def test_trajectory_action_rejects_unknown_field() -> None:
    payload = _action().model_dump()
    payload["intent"] = "purchase"  # not in the schema
    with pytest.raises(ValidationError, match="intent"):
        TrajectoryAction.model_validate(payload)


def test_trajectory_observation_rejects_unknown_field() -> None:
    payload = _observation().model_dump()
    payload["dom_html"] = "<html>...</html>"  # would belong on its own ref
    with pytest.raises(ValidationError, match="dom_html"):
        TrajectoryObservation.model_validate(payload)


def test_trajectory_step_rejects_unknown_field() -> None:
    payload = _step().model_dump()
    payload["score"] = 0.9  # judge scoring belongs on JudgeCall, not here
    with pytest.raises(ValidationError, match="score"):
        TrajectoryStep.model_validate(payload)


def test_trajectory_rejects_unknown_field() -> None:
    payload = json.loads(_trajectory().model_dump_json())
    payload["judge_pick"] = "A"  # belongs on JudgeCall
    with pytest.raises(ValidationError, match="judge_pick"):
        Trajectory.model_validate(payload)


# --------------------------------------------------------------------------- #
# Required-field invariants from spec §5.5 step 2.
# --------------------------------------------------------------------------- #


def test_observation_requires_screenshot() -> None:
    with pytest.raises(ValidationError, match="screenshot"):
        TrajectoryObservation.model_validate(
            {"a11y_snapshot": _a11y_ref(0).model_dump()},
        )


def test_observation_requires_a11y_snapshot() -> None:
    with pytest.raises(ValidationError, match="a11y_snapshot"):
        TrajectoryObservation.model_validate(
            {"screenshot": _screenshot_ref(0).model_dump()},
        )


def test_action_requires_non_empty_kind_and_description() -> None:
    with pytest.raises(ValidationError):
        TrajectoryAction(kind="", description="x")
    with pytest.raises(ValidationError):
        TrajectoryAction(kind="click", description="")


# --------------------------------------------------------------------------- #
# Numeric / temporal constraints.
# --------------------------------------------------------------------------- #


def test_step_rejects_negative_index() -> None:
    with pytest.raises(ValidationError):
        TrajectoryStep(
            index=-1,
            action=_action(),
            observation=_observation(),
            duration_ms=10,
        )


def test_step_rejects_negative_duration() -> None:
    with pytest.raises(ValidationError):
        TrajectoryStep(
            index=0,
            action=_action(),
            observation=_observation(),
            duration_ms=-1,
        )


def test_trajectory_rejects_ended_before_started() -> None:
    with pytest.raises(ValidationError, match="ended_at"):
        _trajectory(ended_at=_STARTED_AT - timedelta(seconds=1))


def test_trajectory_allows_zero_duration_run() -> None:
    """``ended_at == started_at`` is valid — degenerate but not malformed."""
    traj = _trajectory(ended_at=_STARTED_AT, steps=(), final_status="abandoned")
    assert traj.ended_at == traj.started_at


def test_trajectory_rejects_invalid_final_status() -> None:
    with pytest.raises(ValidationError, match="final_status"):
        _trajectory(final_status="success")
