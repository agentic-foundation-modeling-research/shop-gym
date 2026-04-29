"""Tests for `shop_probe.judge.anonymize` (T4.4 acceptance — spec §5.5 step 3).

The acceptance check from the implementation plan reads:

    Unit test asserts no source-domain / brand / first-N-product-title
    leakage post-anonymization.

These tests build a realistic ``Trajectory`` rooted in the pilot pair
(``source/1`` against the calibrated ``sandbox/1``), run it
through :func:`anonymize_trajectory`, and assert that:

* the rewritten trajectory carries ``anonymized=True``;
* the source domain, brand strings, theme identifiers, and the first N
  distinctive product titles do not appear anywhere in the rewritten
  text (target label/url/notes, action selectors/values/descriptions,
  observation urls/titles, step reasoning, top-level notes);
* catalog identifiers in URL paths are replaced with stable hashes that
  match across calls (so symmetric rewrites between (sandbox, source)
  members preserve cross-step structure for the judge);
* the closed schema still round-trips through JSON after rewriting.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from shop_probe.judge.anonymize import (
    REDACTED_BRAND,
    REDACTED_HOST,
    REDACTED_THEME,
    AnonymizationPlan,
    anonymize_trajectory,
    hash_token,
)
from shop_probe.judge.trajectory import (
    Trajectory,
    TrajectoryAction,
    TrajectoryObservation,
    TrajectoryStep,
)
from shop_probe.report import BrowserMeta, EvidenceRef
from shop_probe.targets import Target

# --------------------------------------------------------------------------- #
# Fixture builders — modelled on `pair_1` so the tests double as a
# regression for the actual brand strings the judge would otherwise see.
# --------------------------------------------------------------------------- #

_SOURCE_DOMAIN = "source-1.example.invalid"
_BRAND_TERMS: tuple[str, ...] = ("Hardware", "Shopify Hardware")
_THEME_IDS: tuple[str, ...] = ("Dawn", "atelier")
_PRODUCT_TITLES: tuple[str, ...] = (
    "Premium Snowboard Pro",
    "Hardware Hooded Sweatshirt",
    "Aurora Drinkware Set",
    "ShopFloor Toolkit",
    "Mountain Range Backpack",
)
"""The first N distinctive product names that must not leak (T4.4 check)."""

_STARTED_AT: datetime = datetime(2026, 2, 14, 12, 0, 0, tzinfo=UTC)
_ENDED_AT: datetime = _STARTED_AT + timedelta(seconds=120)


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.1 (Chromium/129)",
        viewport=(1280, 800),
        headless=True,
    )


def _evidence(idx: int, kind: str = "screenshot") -> EvidenceRef:
    suffix = "viewport.png" if kind == "screenshot" else "a11y.json"
    return EvidenceRef(
        kind=kind,  # type: ignore[arg-type]
        path=f"trajectories/t01/step_{idx:03d}/{suffix}",
    )


def _source_target() -> Target:
    return Target(
        name="shop_alpha",
        base_url=f"https://{_SOURCE_DOMAIN}/",
        label="real",
        notes="Production Hardware storefront calibrated against Dawn theme.",
    )


def _step(
    idx: int,
    *,
    action: TrajectoryAction,
    observation: TrajectoryObservation,
    reasoning: str,
) -> TrajectoryStep:
    return TrajectoryStep(
        index=idx,
        action=action,
        observation=observation,
        reasoning=reasoning,
        duration_ms=350 + idx * 40,
    )


def _hardware_trajectory() -> Trajectory:
    """Trajectory full of brand-y signals — the hard case for the rewriter."""
    steps: tuple[TrajectoryStep, ...] = (
        _step(
            0,
            action=TrajectoryAction(
                kind="navigate",
                value=f"https://{_SOURCE_DOMAIN}/collections/snowboards",
                description=(
                    "Navigate to the Hardware snowboard collection on source-1.example.invalid."
                ),
            ),
            observation=TrajectoryObservation(
                url=f"https://{_SOURCE_DOMAIN}/collections/snowboards",
                title="Snowboards — Shopify Hardware",
                screenshot=_evidence(0),
                a11y_snapshot=_evidence(0, kind="a11y_snapshot"),
            ),
            reasoning="The collection page on source-1.example.invalid lists snowboards.",
        ),
        _step(
            1,
            action=TrajectoryAction(
                kind="click",
                selector='a[href="/products/premium-snowboard-pro"]',
                value=None,
                description="Open the Premium Snowboard Pro product detail page.",
            ),
            observation=TrajectoryObservation(
                url=f"https://{_SOURCE_DOMAIN}/products/premium-snowboard-pro",
                title="Premium Snowboard Pro — Shopify Hardware (Dawn theme)",
                screenshot=_evidence(1),
                a11y_snapshot=_evidence(1, kind="a11y_snapshot"),
            ),
            reasoning=("Clicked the Premium Snowboard Pro link on the Hardware storefront."),
        ),
        _step(
            2,
            action=TrajectoryAction(
                kind="type",
                selector="input[name='q']",
                value="Hardware Hooded Sweatshirt",
                description="Search for the Hardware Hooded Sweatshirt.",
            ),
            observation=TrajectoryObservation(
                url=f"https://{_SOURCE_DOMAIN}/search?q=Hardware+Hooded+Sweatshirt",
                title="Search results — Hardware",
                screenshot=_evidence(2),
                a11y_snapshot=_evidence(2, kind="a11y_snapshot"),
            ),
            reasoning="Typed the Hardware Hooded Sweatshirt name into the search box.",
        ),
    )
    return Trajectory(
        target=_source_target(),
        task_id="t01_filter_open_pdp_search",
        runner_version="0.0.0",
        runtime=_browser_meta(),
        started_at=_STARTED_AT,
        ended_at=_ENDED_AT,
        steps=steps,
        har=EvidenceRef(kind="har", path="trajectories/t01/run.har"),
        final_status="completed",
        anonymized=False,
        notes="Run 1 against source-1.example.invalid on Dawn.",
    )


def _plan() -> AnonymizationPlan:
    return AnonymizationPlan(
        source_domains=(_SOURCE_DOMAIN,),
        brand_terms=_BRAND_TERMS,
        theme_identifiers=_THEME_IDS,
        product_titles=_PRODUCT_TITLES,
    )


def _all_text_fields(trajectory: Trajectory) -> list[str]:
    """Return every free-form text field the judge would see.

    Includes target label/base_url/notes, top-level notes, and per-step
    action.selector/value/description, observation.url/title, reasoning.
    Used by the leakage assertions below.
    """
    out: list[str] = [
        trajectory.target.name,
        trajectory.target.base_url,
        trajectory.notes or "",
        trajectory.target.notes or "",
    ]
    for step in trajectory.steps:
        out.extend(
            [
                step.action.selector or "",
                step.action.value or "",
                step.action.description,
                step.observation.url or "",
                step.observation.title or "",
                step.reasoning,
            ]
        )
    return out


# --------------------------------------------------------------------------- #
# hash_token primitive — the building block for catalog placeholders.
# --------------------------------------------------------------------------- #


def test_hash_token_is_deterministic_for_same_inputs() -> None:
    assert hash_token("premium-snowboard-pro") == hash_token("premium-snowboard-pro")


def test_hash_token_changes_with_salt() -> None:
    a = hash_token("premium-snowboard-pro", salt="salt-a")
    b = hash_token("premium-snowboard-pro", salt="salt-b")
    assert a != b


def test_hash_token_respects_length_argument() -> None:
    short = 8
    long = 32
    assert len(hash_token("foo", length=short)) == short
    assert len(hash_token("foo", length=long)) == long


@pytest.mark.parametrize("bad_length", [0, 3, 65, 128])
def test_hash_token_rejects_out_of_range_length(bad_length: int) -> None:
    with pytest.raises(ValueError, match=r"length must be in"):
        hash_token("foo", length=bad_length)


# --------------------------------------------------------------------------- #
# Plan schema — closed contract.
# --------------------------------------------------------------------------- #


def test_anonymization_plan_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AnonymizationPlan.model_validate(
            {
                "source_domains": ("a.example",),
                "unknown": True,
            }
        )


def test_anonymization_plan_defaults_are_empty() -> None:
    plan = AnonymizationPlan()
    assert plan.source_domains == ()
    assert plan.brand_terms == ()
    assert plan.theme_identifiers == ()
    assert plan.product_titles == ()


# --------------------------------------------------------------------------- #
# Trajectory anonymization — the T4.4 acceptance test.
# --------------------------------------------------------------------------- #


def test_anonymize_trajectory_sets_anonymized_flag() -> None:
    traj = _hardware_trajectory()
    out = anonymize_trajectory(traj, _plan())
    assert traj.anonymized is False, "fixture should start non-anonymized"
    assert out.anonymized is True


def test_anonymize_trajectory_strips_source_domain() -> None:
    """T4.4 check: no source-domain leakage post-anonymization."""
    out = anonymize_trajectory(_hardware_trajectory(), _plan())
    for field in _all_text_fields(out):
        assert _SOURCE_DOMAIN not in field.lower(), field
    # The redacted host is the only host signal that survives.
    assert REDACTED_HOST in out.target.base_url


def test_anonymize_trajectory_strips_brand_terms() -> None:
    """T4.4 check: no brand-string leakage post-anonymization."""
    out = anonymize_trajectory(_hardware_trajectory(), _plan())
    for field in _all_text_fields(out):
        # Whole-word case-insensitive: assert no "Hardware" or "Shopify Hardware"
        # token survives. Substring matches inside hashes (12 hex chars) are not
        # possible because hex is lowercase a-f0-9.
        lower = field.lower()
        for brand in _BRAND_TERMS:
            assert brand.lower() not in lower, (brand, field)
    # And the redaction token is what replaced them.
    flat = " ".join(_all_text_fields(out))
    assert REDACTED_BRAND in flat


def test_anonymize_trajectory_strips_theme_identifiers() -> None:
    out = anonymize_trajectory(_hardware_trajectory(), _plan())
    flat = " ".join(_all_text_fields(out)).lower()
    for theme in _THEME_IDS:
        assert f" {theme.lower()} " not in f" {flat} ", theme
    assert REDACTED_THEME.lower() in flat


def test_anonymize_trajectory_strips_first_n_product_titles() -> None:
    """T4.4 check: no first-N-product-title leakage post-anonymization."""
    out = anonymize_trajectory(_hardware_trajectory(), _plan())
    flat = " ".join(_all_text_fields(out)).lower()
    for title in _PRODUCT_TITLES:
        assert title.lower() not in flat, title
    # And distinctive titles that DID appear in the input are now hashed.
    expected_token = f"product_{hash_token('premium snowboard pro', length=12)}"
    assert expected_token in flat


def test_anonymize_trajectory_hashes_catalog_handles_in_url_paths() -> None:
    """Catalog identifiers are replaced with stable hashes (spec §5.5 step 3)."""
    out = anonymize_trajectory(_hardware_trajectory(), _plan())
    pdp_step = out.steps[1]
    expected = hash_token("premium-snowboard-pro", length=12)
    assert pdp_step.observation.url is not None
    assert expected in pdp_step.observation.url
    assert "premium-snowboard-pro" not in pdp_step.observation.url
    # The selector also held the handle inside an href attribute.
    assert pdp_step.action.selector is not None
    assert "premium-snowboard-pro" not in pdp_step.action.selector


def test_anonymize_trajectory_handles_are_stable_across_runs() -> None:
    """Two runs of the same plan + handle produce the same placeholder."""
    plan = _plan()
    out_a = anonymize_trajectory(_hardware_trajectory(), plan)
    out_b = anonymize_trajectory(_hardware_trajectory(), plan)
    assert out_a.steps[1].observation.url == out_b.steps[1].observation.url


def test_anonymize_trajectory_rewrites_target_name_and_base_url() -> None:
    out = anonymize_trajectory(_hardware_trajectory(), _plan())
    assert out.target.name.startswith("target_")
    assert REDACTED_HOST in out.target.base_url
    assert _SOURCE_DOMAIN not in out.target.base_url


def test_anonymize_trajectory_round_trips_through_json() -> None:
    out = anonymize_trajectory(_hardware_trajectory(), _plan())
    payload = json.loads(out.model_dump_json())
    assert payload["anonymized"] is True
    assert Trajectory.model_validate_json(out.model_dump_json()) == out


def test_anonymize_trajectory_with_empty_plan_is_a_safe_no_op_on_text() -> None:
    """An empty plan still rewrites URLs / target but leaves brand-free text alone."""
    plan = AnonymizationPlan()  # nothing to redact
    traj = _hardware_trajectory()
    out = anonymize_trajectory(traj, plan)
    # Without source_domains, the host is *still* redacted because the rewriter
    # treats every host as untrusted (spec §5.5 step 3 — the only host signal
    # that survives is "some host"). But brand text is unchanged because the
    # plan opted out.
    assert _SOURCE_DOMAIN not in (out.target.base_url or "")
    # Brand text in descriptions is preserved — the empty plan opted out.
    assert "Hardware" in out.steps[0].action.description


def test_anonymize_trajectory_preserves_step_indices_and_durations() -> None:
    traj = _hardware_trajectory()
    out = anonymize_trajectory(traj, _plan())
    assert tuple(s.index for s in out.steps) == tuple(s.index for s in traj.steps)
    assert tuple(s.duration_ms for s in out.steps) == tuple(s.duration_ms for s in traj.steps)
    assert out.started_at == traj.started_at
    assert out.ended_at == traj.ended_at
    assert out.final_status == traj.final_status


def test_anonymize_trajectory_preserves_evidence_refs() -> None:
    """Evidence paths are not rewritten by this module (spec §5.5 step 3 v1 scope)."""
    traj = _hardware_trajectory()
    out = anonymize_trajectory(traj, _plan())
    for original, rewritten in zip(traj.steps, out.steps, strict=True):
        assert original.observation.screenshot == rewritten.observation.screenshot
        assert original.observation.a11y_snapshot == rewritten.observation.a11y_snapshot
    assert out.har == traj.har


def test_anonymize_trajectory_strips_brand_in_observation_title() -> None:
    out = anonymize_trajectory(_hardware_trajectory(), _plan())
    for step in out.steps:
        if step.observation.title is None:
            continue
        assert "Hardware" not in step.observation.title
        assert "Dawn" not in step.observation.title


def test_anonymize_trajectory_handles_longer_brand_before_shorter() -> None:
    """Longest-first ordering: ``Shopify Hardware`` is matched before ``Hardware``."""
    plan = _plan()
    out = anonymize_trajectory(_hardware_trajectory(), plan)
    for step in out.steps:
        if step.observation.title is None:
            continue
        # If we matched "Hardware" first we'd leave "Shopify REDACTED" in titles.
        assert "Shopify" not in step.observation.title


def test_anonymize_trajectory_preserves_target_label() -> None:
    out = anonymize_trajectory(_hardware_trajectory(), _plan())
    assert out.target.label == "real"


def test_anonymize_trajectory_relative_url_stays_relative() -> None:
    """Action values that are relative paths must not gain a host (regression)."""
    traj = _hardware_trajectory()
    relative_step = TrajectoryStep(
        index=99,
        action=TrajectoryAction(
            kind="navigate",
            value="/collections/snowboards",
            description="Navigate to /collections/snowboards.",
        ),
        observation=TrajectoryObservation(
            url="/collections/snowboards",
            title="Snowboards",
            screenshot=_evidence(99),
            a11y_snapshot=_evidence(99, kind="a11y_snapshot"),
        ),
        reasoning="",
        duration_ms=10,
    )
    traj = traj.model_copy(update={"steps": (relative_step,)})
    out = anonymize_trajectory(traj, _plan())
    new_url = out.steps[0].observation.url
    assert new_url is not None
    assert REDACTED_HOST not in new_url
    assert new_url.startswith("/collections/")
    # The handle is hashed even on relative URLs.
    assert "snowboards" not in new_url
