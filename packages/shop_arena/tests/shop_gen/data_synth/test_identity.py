"""Unit tests for :mod:`shop_gen.data_synth.identity`.

Covers the T3.3 requirements from
``docs/impl/shop_gen_implementation.md``:

* ``synth_identity`` makes exactly one LLM call producing
  ``{descriptor, tone, currency, country}``; the orchestrator picks
  ``name`` deterministically from the fake-brand allowlist via
  ``sha256(seeds + descriptor) mod len(allowlist)``.
* Deterministic name selection across re-runs with the same inputs.
* Schema validation rejects malformed responses (non-JSON, missing
  fields, wrong currency / country shape, ill-typed tone list).
* ``identity.json`` is written under ``<out_dir>/`` with the closed
  :class:`Identity` model contents.
* The step requires ``ctx.runtime`` and surfaces a clear error when it
  is ``None`` (the public :func:`shop_gen.pipeline.run` does not yet
  plumb a runtime through).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from harness.runtimes import LLMCompleter
from shop_gen.brands.allowlist import Allowlist, load_allowlist
from shop_gen.config import ShopGenConfig
from shop_gen.data_synth.identity import (
    Identity,
    IdentitySynthError,
    SynthIdentityStep,
    pick_name_from_allowlist,
    synth_identity_from_manual,
)
from shop_gen.pipeline import list_steps
from shop_gen.steps.base import StepContext

# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #


@dataclass
class _StubCompleter:
    """Recording :class:`LLMCompleter` returning a queue of canned responses."""

    responses: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)

    def complete(self, prompt: str, *, timeout: float) -> str:
        del timeout
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("LLM was called more times than expected")
        return self.responses.pop(0)


def _stub_response(
    *,
    descriptor: str = "boutique outdoor storefront",
    tone: tuple[str, ...] = ("rugged", "warm"),
    currency: str = "USD",
    country: str = "US",
) -> str:
    return json.dumps(
        {
            "descriptor": descriptor,
            "tone": list(tone),
            "currency": currency,
            "country": country,
        },
    )


def _materialise_manual(out_dir: Path) -> None:
    """Write a minimal ``manual/`` so the step can read it at run time."""
    manual_dir = out_dir / "manual"
    manual_dir.mkdir(parents=True, exist_ok=True)
    (manual_dir / "capabilities.json").write_text(
        json.dumps(
            {
                "version": "0.1",
                "shop": {
                    "descriptor": "boutique outdoor storefront",
                    "category": "outdoor",
                    "currency": "USD",
                    "tone": ["rugged", "warm"],
                },
            },
        ),
        encoding="utf-8",
    )
    (manual_dir / "manual.md").write_text(
        "# Shop Manual — boutique outdoor storefront\n\n## Overview\n\n"
        "Focused outdoor storefront for hikers and campers.\n",
        encoding="utf-8",
    )


def _make_seed(tmp_path: Path, name: str = "seed_a") -> Path:
    seed = tmp_path / name
    seed.mkdir()
    return seed


# --------------------------------------------------------------------------- #
# Identity model
# --------------------------------------------------------------------------- #


def test_identity_round_trip_preserves_fields() -> None:
    payload = {
        "name": "AisleArena",
        "descriptor": "boutique outdoor storefront",
        "tone": ["rugged", "warm"],
        "currency": "USD",
        "country": "US",
    }
    identity = Identity.model_validate(payload)
    assert identity.model_dump(mode="json") == payload


def test_identity_rejects_extra_field() -> None:
    with pytest.raises(Exception, match="Extra"):
        Identity.model_validate(
            {
                "name": "AisleArena",
                "descriptor": "boutique outdoor storefront",
                "tone": ["rugged"],
                "currency": "USD",
                "country": "US",
                "rogue": "should fail",
            },
        )


def test_identity_rejects_lowercase_currency() -> None:
    with pytest.raises(Exception, match="currency"):
        Identity.model_validate(
            {
                "name": "AisleArena",
                "descriptor": "boutique outdoor storefront",
                "tone": ["rugged"],
                "currency": "usd",
                "country": "US",
            },
        )


def test_identity_rejects_more_than_three_tone_tags() -> None:
    with pytest.raises(Exception, match="tone"):
        Identity.model_validate(
            {
                "name": "AisleArena",
                "descriptor": "boutique outdoor storefront",
                "tone": ["a", "b", "c", "d"],
                "currency": "USD",
                "country": "US",
            },
        )


# --------------------------------------------------------------------------- #
# pick_name_from_allowlist
# --------------------------------------------------------------------------- #


def test_pick_name_is_deterministic_across_calls(tmp_path: Path) -> None:
    seeds = [tmp_path / "seed_a", tmp_path / "seed_b"]
    allowlist = load_allowlist()
    a = pick_name_from_allowlist(seeds=seeds, descriptor="cozy home goods", allowlist=allowlist)
    b = pick_name_from_allowlist(seeds=seeds, descriptor="cozy home goods", allowlist=allowlist)
    assert a == b
    assert a in allowlist.brands


def test_pick_name_changes_with_descriptor(tmp_path: Path) -> None:
    seeds = [tmp_path / "seed_a"]
    allowlist = load_allowlist()
    descriptors = [f"descriptor variation {i}" for i in range(20)]
    picks = {
        pick_name_from_allowlist(seeds=seeds, descriptor=d, allowlist=allowlist)
        for d in descriptors
    }
    # Every pick is in the allowlist and at least two distinct descriptors
    # should disagree at the v0.1 allowlist size (10 brands).
    assert picks <= set(allowlist.brands)
    assert len(picks) >= 2  # noqa: PLR2004


def test_pick_name_changes_with_seeds(tmp_path: Path) -> None:
    descriptor = "premium home goods storefront"
    allowlist = load_allowlist()
    distinct_picks: set[str] = set()
    for i in range(20):
        seeds = [tmp_path / f"seed_{i}"]
        distinct_picks.add(
            pick_name_from_allowlist(seeds=seeds, descriptor=descriptor, allowlist=allowlist),
        )
    assert distinct_picks <= set(allowlist.brands)
    assert len(distinct_picks) >= 2  # noqa: PLR2004


def test_pick_name_rejects_empty_allowlist(tmp_path: Path) -> None:
    empty = Allowlist(version="0.0.0", brands=frozenset(), safe_nouns=frozenset())
    with pytest.raises(ValueError, match="no brands"):
        pick_name_from_allowlist(seeds=[tmp_path / "x"], descriptor="d", allowlist=empty)


# --------------------------------------------------------------------------- #
# synth_identity_from_manual
# --------------------------------------------------------------------------- #


def test_synth_identity_from_manual_calls_llm_once_and_picks_name(tmp_path: Path) -> None:
    completer = _StubCompleter(responses=[_stub_response()])
    capabilities = {"version": "0.1", "shop": {"descriptor": "cozy"}}
    seeds = [tmp_path / "seed_a"]
    identity = synth_identity_from_manual(
        capabilities=capabilities,
        manual="# Shop Manual — cozy\n",
        seeds=seeds,
        completer=cast(LLMCompleter, completer),
    )
    assert len(completer.prompts) == 1
    assert identity.descriptor == "boutique outdoor storefront"
    assert identity.tone == ["rugged", "warm"]
    assert identity.currency == "USD"
    assert identity.country == "US"
    assert identity.name in load_allowlist().brands


def test_synth_identity_strips_code_fence(tmp_path: Path) -> None:
    fenced = "```json\n" + _stub_response() + "\n```"
    completer = _StubCompleter(responses=[fenced])
    identity = synth_identity_from_manual(
        capabilities={"version": "0.1"},
        manual="# Manual\n",
        seeds=[tmp_path / "seed_a"],
        completer=cast(LLMCompleter, completer),
    )
    assert identity.descriptor == "boutique outdoor storefront"


def test_synth_identity_rejects_empty_response(tmp_path: Path) -> None:
    completer = _StubCompleter(responses=[""])
    with pytest.raises(IdentitySynthError, match="empty response"):
        synth_identity_from_manual(
            capabilities={"version": "0.1"},
            manual="# Manual\n",
            seeds=[tmp_path / "seed_a"],
            completer=cast(LLMCompleter, completer),
        )


def test_synth_identity_rejects_non_json_response(tmp_path: Path) -> None:
    completer = _StubCompleter(responses=["not-json at all"])
    with pytest.raises(IdentitySynthError, match="not valid JSON"):
        synth_identity_from_manual(
            capabilities={"version": "0.1"},
            manual="# Manual\n",
            seeds=[tmp_path / "seed_a"],
            completer=cast(LLMCompleter, completer),
        )


def test_synth_identity_rejects_missing_descriptor(tmp_path: Path) -> None:
    completer = _StubCompleter(
        responses=[json.dumps({"tone": ["a"], "currency": "USD", "country": "US"})],
    )
    with pytest.raises(IdentitySynthError, match="descriptor"):
        synth_identity_from_manual(
            capabilities={"version": "0.1"},
            manual="# Manual\n",
            seeds=[tmp_path / "seed_a"],
            completer=cast(LLMCompleter, completer),
        )


def test_synth_identity_rejects_bad_currency_shape(tmp_path: Path) -> None:
    completer = _StubCompleter(responses=[_stub_response(currency="dollars")])
    with pytest.raises(IdentitySynthError, match="ISO 4217"):
        synth_identity_from_manual(
            capabilities={"version": "0.1"},
            manual="# Manual\n",
            seeds=[tmp_path / "seed_a"],
            completer=cast(LLMCompleter, completer),
        )


def test_synth_identity_rejects_bad_country_shape(tmp_path: Path) -> None:
    completer = _StubCompleter(responses=[_stub_response(country="USA")])
    with pytest.raises(IdentitySynthError, match="ISO 3166-1"):
        synth_identity_from_manual(
            capabilities={"version": "0.1"},
            manual="# Manual\n",
            seeds=[tmp_path / "seed_a"],
            completer=cast(LLMCompleter, completer),
        )


def test_synth_identity_rejects_empty_tone_list(tmp_path: Path) -> None:
    completer = _StubCompleter(
        responses=[
            json.dumps(
                {
                    "descriptor": "x",
                    "tone": [],
                    "currency": "USD",
                    "country": "US",
                },
            ),
        ],
    )
    with pytest.raises(IdentitySynthError, match="tone"):
        synth_identity_from_manual(
            capabilities={"version": "0.1"},
            manual="# Manual\n",
            seeds=[tmp_path / "seed_a"],
            completer=cast(LLMCompleter, completer),
        )


def test_synth_identity_returns_same_name_for_same_inputs(tmp_path: Path) -> None:
    """Re-running with identical inputs (and identical LLM response) yields the same name."""
    seeds = [tmp_path / "seed_a", tmp_path / "seed_b"]
    capabilities = {"version": "0.1"}
    manual = "# Manual\n"
    response = _stub_response(descriptor="stable descriptor")

    first = synth_identity_from_manual(
        capabilities=capabilities,
        manual=manual,
        seeds=seeds,
        completer=cast(LLMCompleter, _StubCompleter(responses=[response])),
    )
    second = synth_identity_from_manual(
        capabilities=capabilities,
        manual=manual,
        seeds=seeds,
        completer=cast(LLMCompleter, _StubCompleter(responses=[response])),
    )
    assert first == second


# --------------------------------------------------------------------------- #
# SynthIdentityStep
# --------------------------------------------------------------------------- #


def test_step_metadata_for_multi_seed() -> None:
    step = SynthIdentityStep(manual_step_ids=("merge_capabilities", "merge_manual_prose"))
    assert step.id == "synth_identity"
    assert step.phase == "data_synth"
    assert step.outputs == [Path("identity.json")]
    assert step.depends_on == ["merge_capabilities", "merge_manual_prose"]
    assert step.version == 1


def test_step_metadata_for_single_seed() -> None:
    step = SynthIdentityStep(manual_step_ids=("copy_seed_manual",))
    assert step.depends_on == ["copy_seed_manual"]


def test_step_metadata_listing_branch() -> None:
    """Empty ``manual_step_ids`` is the listing-branch placeholder shape."""
    step = SynthIdentityStep()
    assert step.id == "synth_identity"
    assert step.depends_on == []
    assert step.inputs == []


def test_step_run_writes_identity_json(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_manual(out_dir)
    completer = _StubCompleter(responses=[_stub_response(descriptor="cozy outdoor")])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))

    step = SynthIdentityStep(manual_step_ids=("copy_seed_manual",))
    step.run(ctx)

    written = json.loads((out_dir / "identity.json").read_text(encoding="utf-8"))
    identity = Identity.model_validate(written)
    assert identity.descriptor == "cozy outdoor"
    assert identity.name in load_allowlist().brands


def test_step_run_is_deterministic_across_invocations(tmp_path: Path) -> None:
    """Two runs against identical inputs + LLM response produce the same identity.json."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_manual(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    response = _stub_response(descriptor="stable descriptor", tone=("clean", "calm"))

    def _run() -> bytes:
        completer = _StubCompleter(responses=[response])
        ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
        step = SynthIdentityStep(manual_step_ids=("copy_seed_manual",))
        step.run(ctx)
        return (out_dir / "identity.json").read_bytes()

    first = _run()
    second = _run()
    assert first == second


def test_step_run_requires_runtime(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_manual(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    step = SynthIdentityStep(manual_step_ids=("copy_seed_manual",))
    with pytest.raises(ValueError, match="LLMCompleter"):
        step.run(ctx)


def test_step_run_missing_manual_capabilities(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
    step = SynthIdentityStep(manual_step_ids=("copy_seed_manual",))
    with pytest.raises(FileNotFoundError, match="capabilities"):
        step.run(ctx)


def test_step_registered_with_pipeline_appears_in_data_synth_phase() -> None:
    """T3.3 wires ``synth_identity`` into the Phase 2 phase listing."""
    grouped = list_steps()
    assert "synth_identity" in grouped["data_synth"]
