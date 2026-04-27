"""Unit tests for :mod:`shop_gen.data_synth.store`.

Covers the T3.4 requirements from
``docs/impl/shop_gen_implementation.md``:

* ``synth_store`` makes exactly one LLM call producing a JSON object
  shaped like :class:`~shop_gen.data_synth.schema.Store` (minus the
  identity-locked fields, which the orchestrator overrides).
* The cached payload at ``.shop_gen/stage_cache/store.json`` is
  pydantic-validated.
* The step requires ``ctx.runtime`` and surfaces a clear error when it
  is ``None`` (the public :func:`shop_gen.pipeline.run` does not yet
  plumb a runtime through).
* Identity-locked fields (``name``, ``currency_code``, ``country_code``)
  always reflect the identity, even if the LLM tries to override them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from harness.runtimes import LLMCompleter
from shop_gen.config import ShopGenConfig
from shop_gen.data_synth import StageSynthError, Store, SynthStoreStep
from shop_gen.data_synth.store import synth_store_from_identity
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


def _identity(
    *,
    name: str = "AisleArena",
    descriptor: str = "boutique outdoor storefront",
    currency: str = "USD",
    country: str = "US",
) -> dict[str, object]:
    return {
        "name": name,
        "descriptor": descriptor,
        "tone": ["rugged", "warm"],
        "currency": currency,
        "country": country,
    }


def _stub_response(
    *,
    domain: str = "aisle-arena.example",
    description: str = "A small outdoor storefront.",
    primary: str = "#1f6f43",
    secondary: str = "#f3e9d2",
    cards: tuple[str, ...] = ("VISA", "MASTER"),
    logo_url: str | None = None,
) -> str:
    return json.dumps(
        {
            "domain": domain,
            "description": description,
            "payment_settings": {"accepted_card_brands": list(cards)},
            "brand": {
                "logo_url": logo_url,
                "colors": {"primary": primary, "secondary": secondary},
            },
        },
    )


def _materialise_identity(out_dir: Path, **identity_overrides: object) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = _identity(**identity_overrides)  # type: ignore[arg-type]
    (out_dir / "identity.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _make_seed(tmp_path: Path) -> Path:
    seed = tmp_path / "seed_a"
    seed.mkdir()
    return seed


# --------------------------------------------------------------------------- #
# synth_store_from_identity
# --------------------------------------------------------------------------- #


def test_synth_store_calls_llm_once_and_validates() -> None:
    completer = _StubCompleter(responses=[_stub_response()])
    store = synth_store_from_identity(
        identity=_identity(),
        completer=cast(LLMCompleter, completer),
    )
    assert len(completer.prompts) == 1
    assert isinstance(store, Store)
    assert store.domain == "aisle-arena.example"
    assert store.description == "A small outdoor storefront."
    assert store.payment_settings.accepted_card_brands == ["VISA", "MASTER"]
    assert store.brand.colors.primary == "#1f6f43"


def test_synth_store_uses_identity_for_locked_fields() -> None:
    """The identity name / currency / country always win over LLM payload."""
    completer = _StubCompleter(responses=[_stub_response()])
    store = synth_store_from_identity(
        identity=_identity(name="DuneRidge", currency="EUR", country="DE"),
        completer=cast(LLMCompleter, completer),
    )
    assert store.name == "DuneRidge"
    assert store.currency_code == "EUR"
    assert store.country_code == "DE"


def test_synth_store_strips_llm_locked_fields() -> None:
    """If the LLM smuggles its own name, the orchestrator's name still wins."""
    response = json.dumps(
        {
            "domain": "x.example",
            "description": "y",
            "payment_settings": {"accepted_card_brands": ["VISA"]},
            "brand": {
                "logo_url": None,
                "colors": {"primary": "#000000", "secondary": "#ffffff"},
            },
            # Sneaky overrides:
            "name": "Real-World Co.",
            "currency_code": "GBP",
            "country_code": "GB",
            "shop_id": 999,
        },
    )
    completer = _StubCompleter(responses=[response])
    store = synth_store_from_identity(
        identity=_identity(name="AisleArena", currency="USD", country="US"),
        completer=cast(LLMCompleter, completer),
    )
    assert store.name == "AisleArena"
    assert store.currency_code == "USD"
    assert store.country_code == "US"
    assert store.shop_id == 0


def test_synth_store_assigns_placeholder_shop_id() -> None:
    """``shop_id`` is set to 0 in stage cache; ``assemble_data`` reassigns later."""
    completer = _StubCompleter(responses=[_stub_response()])
    store = synth_store_from_identity(
        identity=_identity(),
        completer=cast(LLMCompleter, completer),
    )
    assert store.shop_id == 0


def test_synth_store_strips_code_fence() -> None:
    fenced = "```json\n" + _stub_response() + "\n```"
    completer = _StubCompleter(responses=[fenced])
    store = synth_store_from_identity(
        identity=_identity(),
        completer=cast(LLMCompleter, completer),
    )
    assert store.domain == "aisle-arena.example"


def test_synth_store_rejects_empty_response() -> None:
    completer = _StubCompleter(responses=[""])
    with pytest.raises(StageSynthError, match="empty response"):
        synth_store_from_identity(
            identity=_identity(),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_store_rejects_non_json_response() -> None:
    completer = _StubCompleter(responses=["not-json"])
    with pytest.raises(StageSynthError, match="not valid JSON"):
        synth_store_from_identity(
            identity=_identity(),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_store_rejects_array_response() -> None:
    completer = _StubCompleter(responses=["[]"])
    with pytest.raises(StageSynthError, match="JSON object"):
        synth_store_from_identity(
            identity=_identity(),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_store_rejects_missing_required_field() -> None:
    """Pydantic validation catches missing payment_settings / brand."""
    completer = _StubCompleter(
        responses=[json.dumps({"domain": "x.example", "description": "y"})],
    )
    with pytest.raises(StageSynthError, match="Store schema validation"):
        synth_store_from_identity(
            identity=_identity(),
            completer=cast(LLMCompleter, completer),
        )


def test_synth_store_rejects_identity_missing_name() -> None:
    completer = _StubCompleter(responses=[])
    bad_identity = {"descriptor": "x", "tone": ["a"], "currency": "USD", "country": "US"}
    with pytest.raises(StageSynthError, match="missing non-empty string 'name'"):
        synth_store_from_identity(
            identity=bad_identity,
            completer=cast(LLMCompleter, completer),
        )


# --------------------------------------------------------------------------- #
# SynthStoreStep
# --------------------------------------------------------------------------- #


def test_step_metadata() -> None:
    step = SynthStoreStep()
    assert step.id == "synth_store"
    assert step.phase == "data_synth"
    assert step.outputs == [Path(".shop_gen") / "stage_cache" / "store.json"]
    assert step.depends_on == ["synth_identity"]
    assert step.version == 1


def test_step_run_writes_stage_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_identity(out_dir)
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))

    step = SynthStoreStep()
    step.run(ctx)

    cached = json.loads(
        (out_dir / ".shop_gen" / "stage_cache" / "store.json").read_text(encoding="utf-8"),
    )
    store = Store.model_validate(cached)
    assert store.name == "AisleArena"
    assert store.domain == "aisle-arena.example"
    assert len(completer.prompts) == 1


def test_step_run_is_deterministic_across_invocations(tmp_path: Path) -> None:
    """Two runs against identical inputs + LLM response produce the same store.json."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_identity(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    response = _stub_response()

    def _run() -> bytes:
        completer = _StubCompleter(responses=[response])
        ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
        step = SynthStoreStep()
        step.run(ctx)
        return (out_dir / ".shop_gen" / "stage_cache" / "store.json").read_bytes()

    first = _run()
    second = _run()
    assert first == second


def test_step_run_requires_runtime(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_identity(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    step = SynthStoreStep()
    with pytest.raises(ValueError, match="LLMCompleter"):
        step.run(ctx)


def test_step_run_missing_identity(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    completer = _StubCompleter(responses=[_stub_response()])
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
    step = SynthStoreStep()
    with pytest.raises(FileNotFoundError, match=r"identity\.json"):
        step.run(ctx)


def test_step_registered_with_pipeline_appears_in_data_synth_phase() -> None:
    """T3.4 wires ``synth_store`` into the Phase 2 phase listing."""
    grouped = list_steps()
    assert "synth_store" in grouped["data_synth"]
