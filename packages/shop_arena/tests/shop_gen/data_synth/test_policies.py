"""Unit tests for :mod:`shop_gen.data_synth.policies`.

Covers the T3.4 requirements from
``docs/impl/shop_gen_implementation.md``:

* ``synth_policies`` makes exactly one LLM call producing a JSON array
  of :class:`~shop_gen.data_synth.schema.Policy`-shaped objects.
* The cached payload at ``.shop_gen/stage_cache/policies.json`` is
  pydantic-validated.
* The conventional policy handles (privacy / shipping / terms /
  refund) are required by the step.
* The step requires ``ctx.runtime`` and surfaces a clear error when it
  is ``None``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from harness.runtimes import LLMCompleter
from shop_gen.config import ShopGenConfig
from shop_gen.data_synth import Policy, StageSynthError, SynthPoliciesStep
from shop_gen.data_synth.policies import synth_policies_from_identity
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


_IDENTITY: dict[str, object] = {
    "name": "AisleArena",
    "descriptor": "boutique outdoor storefront",
    "tone": ["rugged", "warm"],
    "currency": "USD",
    "country": "US",
}

_REQUIRED_HANDLES: tuple[str, ...] = (
    "privacy-policy",
    "shipping-policy",
    "terms-of-service",
    "refund-policy",
)


def _stub_response(handles: tuple[str, ...] = _REQUIRED_HANDLES) -> str:
    return json.dumps(
        [
            {
                "handle": handle,
                "title": handle.replace("-", " ").title(),
                "body_html": f"<p>{handle}</p>",
            }
            for handle in handles
        ],
    )


def _materialise_identity(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "identity.json").write_text(
        json.dumps(_IDENTITY, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _make_seed(tmp_path: Path) -> Path:
    seed = tmp_path / "seed_a"
    seed.mkdir()
    return seed


# --------------------------------------------------------------------------- #
# synth_policies_from_identity
# --------------------------------------------------------------------------- #


def test_synth_policies_calls_llm_once_and_validates() -> None:
    completer = _StubCompleter(responses=[_stub_response()])
    policies = synth_policies_from_identity(
        identity=_IDENTITY,
        completer=cast(LLMCompleter, completer),
    )
    assert len(completer.prompts) == 1
    assert {p.handle for p in policies} == set(_REQUIRED_HANDLES)
    assert all(isinstance(p, Policy) for p in policies)


def test_synth_policies_strips_code_fence() -> None:
    fenced = "```json\n" + _stub_response() + "\n```"
    completer = _StubCompleter(responses=[fenced])
    policies = synth_policies_from_identity(
        identity=_IDENTITY,
        completer=cast(LLMCompleter, completer),
    )
    assert {p.handle for p in policies} == set(_REQUIRED_HANDLES)


def test_synth_policies_rejects_empty_response() -> None:
    completer = _StubCompleter(responses=[""])
    with pytest.raises(StageSynthError, match="empty response"):
        synth_policies_from_identity(
            identity=_IDENTITY,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_policies_rejects_empty_array() -> None:
    completer = _StubCompleter(responses=["[]"])
    with pytest.raises(StageSynthError, match="empty policies array"):
        synth_policies_from_identity(
            identity=_IDENTITY,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_policies_rejects_object_response() -> None:
    completer = _StubCompleter(responses=["{}"])
    with pytest.raises(StageSynthError, match="JSON array"):
        synth_policies_from_identity(
            identity=_IDENTITY,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_policies_rejects_missing_required_handle() -> None:
    """The conventional set of four handles is enforced at parse time."""
    completer = _StubCompleter(
        responses=[_stub_response(("privacy-policy", "shipping-policy", "terms-of-service"))],
    )
    with pytest.raises(StageSynthError, match="missing required policy handles"):
        synth_policies_from_identity(
            identity=_IDENTITY,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_policies_rejects_duplicate_handles() -> None:
    completer = _StubCompleter(
        responses=[
            _stub_response(
                (
                    "privacy-policy",
                    "shipping-policy",
                    "terms-of-service",
                    "refund-policy",
                    "privacy-policy",
                ),
            ),
        ],
    )
    with pytest.raises(StageSynthError, match="duplicate policy handle"):
        synth_policies_from_identity(
            identity=_IDENTITY,
            completer=cast(LLMCompleter, completer),
        )


def test_synth_policies_rejects_missing_field() -> None:
    bad = json.dumps([{"handle": handle} for handle in _REQUIRED_HANDLES])
    completer = _StubCompleter(responses=[bad])
    with pytest.raises(StageSynthError, match="Policy schema validation"):
        synth_policies_from_identity(
            identity=_IDENTITY,
            completer=cast(LLMCompleter, completer),
        )


# --------------------------------------------------------------------------- #
# SynthPoliciesStep
# --------------------------------------------------------------------------- #


def test_step_metadata() -> None:
    step = SynthPoliciesStep()
    assert step.id == "synth_policies"
    assert step.phase == "data_synth"
    assert step.outputs == [Path(".shop_gen") / "stage_cache" / "policies.json"]
    assert step.depends_on == ["synth_identity"]
    assert step.version == 1


def test_step_run_writes_stage_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_identity(out_dir)
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))

    step = SynthPoliciesStep()
    step.run(ctx)

    cached = json.loads(
        (out_dir / ".shop_gen" / "stage_cache" / "policies.json").read_text(encoding="utf-8"),
    )
    assert isinstance(cached, list)
    assert {Policy.model_validate(entry).handle for entry in cached} == set(_REQUIRED_HANDLES)


def test_step_run_is_deterministic(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_identity(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    response = _stub_response()

    def _run() -> bytes:
        completer = _StubCompleter(responses=[response])
        ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
        step = SynthPoliciesStep()
        step.run(ctx)
        return (out_dir / ".shop_gen" / "stage_cache" / "policies.json").read_bytes()

    assert _run() == _run()


def test_step_run_requires_runtime(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_identity(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    step = SynthPoliciesStep()
    with pytest.raises(ValueError, match="LLMCompleter"):
        step.run(ctx)


def test_step_run_missing_identity(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
    step = SynthPoliciesStep()
    with pytest.raises(FileNotFoundError, match=r"identity\.json"):
        step.run(ctx)


def test_step_registered_with_pipeline_appears_in_data_synth_phase() -> None:
    """T3.4 wires ``synth_policies`` into the Phase 2 phase listing."""
    grouped = list_steps()
    assert "synth_policies" in grouped["data_synth"]
