"""Unit tests for :mod:`shop_arena.env_eval.observation.rubric` (impl-plan M2).

The rubric module owns the M2 ``observation/<bucket>.rubric.json`` writer
(spec §5.3).  Coverage here pins the closed contract:

* the JSON schema sent to the model matches the closed
  :data:`RUBRIC_CATEGORIES` enum exactly,
* a clean :class:`VisionResponse` round-trips into a populated artifact,
* malformed responses (no parsed mapping, or schema violations) collapse
  to zero counts plus non-empty ``parse_errors`` instead of raising,
* the on-disk artifact is byte-stable JSON containing every required
  field (``prompt_version`` / ``model`` / ``temperature`` / ``counts`` /
  ``raw_response`` / ``parse_errors``).

Provider routing, missing-credential handling, and the model-capability
deny list are exercised in :mod:`test_llm`; this file injects a fake
:class:`LLMVisionClient` so the rubric tests stay hermetic.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shop_arena.env_eval.observation import rubric as rubric_mod
from shop_arena.env_eval.observation.rubric import (
    RUBRIC_PROMPT_VERSION,
    RUBRIC_RESPONSE_SCHEMA,
    RubricArtifact,
    build_rubric_prompt_payload,
    load_rubric_prompt,
    run_rubric,
    write_rubric_artifact,
)
from shop_arena.env_eval.schema.metrics import RUBRIC_CATEGORIES, Rubric
from shop_arena.util._llm import VisionResponse

# ---------------------------------------------------------------------------
# Test fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakeVisionClient:
    """Records ``call`` arguments and returns a canned :class:`VisionResponse`.

    Implements the :class:`shop_arena.util._llm.LLMVisionClient` Protocol
    by attribute (``model``) plus method (``call``).
    """

    model: str = "claude-sonnet-4-6"
    response: VisionResponse = field(
        default_factory=lambda: VisionResponse(parsed=None, raw_response=""),
    )
    calls: list[dict[str, Any]] = field(default_factory=list)

    def call(
        self,
        *,
        prompt: str,
        images: Sequence[bytes],
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        self.calls.append(
            {
                "prompt": prompt,
                "images": tuple(images),
                "schema": schema,
                "temperature": temperature,
            },
        )
        return self.response


_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-payload"
_AXTREE_TEXT = (
    "RootWebArea 'Mock Apparel'\n"
    "\t[57] banner\n"
    "\t\t[60] link 'Mock Clothing'\n"
    "\t\t[62] navigation 'Primary'"
)


def _all_zero_counts() -> dict[str, int]:
    return dict.fromkeys(RUBRIC_CATEGORIES, 0)


# ---------------------------------------------------------------------------
# Module layout
# ---------------------------------------------------------------------------


def test_rubric_module_is_importable() -> None:
    """M0 layout marker: ``observation.rubric`` exists and imports."""
    assert rubric_mod.__name__ == "shop_arena.env_eval.observation.rubric"


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


def test_response_schema_mirrors_closed_category_enum() -> None:
    """Schema properties + ``required`` list match :data:`RUBRIC_CATEGORIES` exactly."""
    properties = RUBRIC_RESPONSE_SCHEMA["properties"]
    assert set(properties.keys()) == set(RUBRIC_CATEGORIES)
    assert RUBRIC_RESPONSE_SCHEMA["required"] == list(RUBRIC_CATEGORIES)


def test_response_schema_is_closed() -> None:
    """``additionalProperties=false`` so unknown categories are rejected."""
    assert RUBRIC_RESPONSE_SCHEMA["additionalProperties"] is False
    assert RUBRIC_RESPONSE_SCHEMA["type"] == "object"


def test_response_schema_property_types_are_non_negative_integers() -> None:
    """Every category accepts only non-negative integers."""
    for category, schema in RUBRIC_RESPONSE_SCHEMA["properties"].items():
        assert schema == {"type": "integer", "minimum": 0}, category


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------


def test_load_rubric_prompt_returns_body_only() -> None:
    """Loader strips the documentation header before the ``---`` divider."""
    body = load_rubric_prompt()
    assert body.endswith("\n")
    # Documentation lines mention "prompt_version" — body should not.
    assert "prompt_version" not in body
    # The body starts at the first prompt instruction.
    assert "You are auditing" in body


def test_load_rubric_prompt_is_deterministic() -> None:
    """Two calls return byte-identical strings (no template interpolation)."""
    assert load_rubric_prompt() == load_rubric_prompt()


def test_build_rubric_prompt_payload_appends_axtree_under_header() -> None:
    """Helper concatenates the prompt body, the axtree header, and the axtree text."""
    payload = build_rubric_prompt_payload(_AXTREE_TEXT)
    assert payload.startswith(load_rubric_prompt().rstrip())
    assert "\n\n--- AXTREE ---\n" in payload
    assert payload.endswith(_AXTREE_TEXT.rstrip() + "\n")


def test_build_rubric_prompt_payload_accepts_empty_axtree() -> None:
    """An empty axtree still emits the section header so the wire shape is stable."""
    payload = build_rubric_prompt_payload("")
    assert payload.endswith("\n\n--- AXTREE ---\n\n")


# ---------------------------------------------------------------------------
# run_rubric — happy path
# ---------------------------------------------------------------------------


def test_run_rubric_forwards_prompt_image_and_schema_to_client() -> None:
    """The vision client receives the prompt body, PNG bytes, and closed schema."""
    parsed = _all_zero_counts() | {"nav": 1, "footer": 2}
    client = _FakeVisionClient(
        response=VisionResponse(parsed=parsed, raw_response=json.dumps(parsed, sort_keys=True)),
    )

    artifact = run_rubric(client, (_PNG_BYTES,), axtree_text=_AXTREE_TEXT, temperature=0.0)

    [call] = client.calls
    assert call["images"] == (_PNG_BYTES,)
    assert call["schema"] == RUBRIC_RESPONSE_SCHEMA
    assert call["temperature"] == 0.0
    assert call["prompt"] == build_rubric_prompt_payload(_AXTREE_TEXT)
    # Clean response → fully populated artifact, no parse errors.
    assert artifact.parse_errors == ()
    assert artifact.prompt_version == RUBRIC_PROMPT_VERSION
    assert artifact.model == client.model
    assert artifact.temperature == 0.0
    assert artifact.counts.nav == 1
    assert artifact.counts.footer == 2


def test_run_rubric_passes_through_temperature_override() -> None:
    """A non-default ``temperature`` propagates to both the client and the artifact."""
    parsed = _all_zero_counts()
    client = _FakeVisionClient(
        response=VisionResponse(parsed=parsed, raw_response="{}"),
    )

    artifact = run_rubric(client, (_PNG_BYTES,), axtree_text=_AXTREE_TEXT, temperature=0.7)

    [call] = client.calls
    assert call["temperature"] == 0.7
    assert artifact.temperature == 0.7


def test_run_rubric_accepts_custom_prompt_override() -> None:
    """Passing ``prompt=`` bypasses ``prompt.md`` for tests / experiments."""
    parsed = _all_zero_counts()
    client = _FakeVisionClient(
        response=VisionResponse(parsed=parsed, raw_response="{}"),
    )

    run_rubric(
        client,
        (_PNG_BYTES,),
        axtree_text=_AXTREE_TEXT,
        prompt="custom prompt for the test only",
    )

    [call] = client.calls
    # The override replaces ``prompt.md`` body; the axtree section is still
    # appended so the on-wire prompt shape stays stable.

    assert call["prompt"] == build_rubric_prompt_payload(
        _AXTREE_TEXT,
        base_prompt="custom prompt for the test only",
    )


def test_run_rubric_state_node_passes_pre_and_post_screenshots() -> None:
    """State-node mode (v0.3) forwards both screenshots and an empty axtree."""
    pre_png = b"\x89PNG\r\n\x1a\nfake-pre"
    post_png = b"\x89PNG\r\n\x1a\nfake-post"
    parsed = _all_zero_counts() | {"popup_modal": 1, "cta_button": 2}
    client = _FakeVisionClient(
        response=VisionResponse(parsed=parsed, raw_response=json.dumps(parsed, sort_keys=True)),
    )

    artifact = run_rubric(client, (pre_png, post_png), axtree_text="")

    [call] = client.calls
    # Both screenshots reach the client in pre-then-post order.
    assert call["images"] == (pre_png, post_png)
    # Empty axtree still emits the section header so the on-wire shape is stable.
    assert call["prompt"] == build_rubric_prompt_payload("")
    # The clean response round-trips into a populated artifact.
    assert artifact.parse_errors == ()
    assert artifact.counts.popup_modal == 1
    assert artifact.counts.cta_button == 2


# ---------------------------------------------------------------------------
# run_rubric — malformed-response fallback
# ---------------------------------------------------------------------------


def test_run_rubric_with_no_parsed_mapping_yields_zero_counts() -> None:
    """``parsed=None`` → zero :class:`Rubric` and parse_errors propagated verbatim."""
    client = _FakeVisionClient(
        response=VisionResponse(
            parsed=None,
            raw_response="not-json",
            parse_errors=("openai response is not valid JSON: …",),
        ),
    )

    artifact = run_rubric(client, (_PNG_BYTES,), axtree_text=_AXTREE_TEXT)

    assert artifact.counts == Rubric()
    assert artifact.parse_errors == ("openai response is not valid JSON: …",)
    assert artifact.raw_response == "not-json"


def test_run_rubric_with_unknown_category_collapses_to_parse_error() -> None:
    """A response with an off-enum key fails closed-schema validation."""
    parsed = _all_zero_counts() | {"unknown_category": 5}
    client = _FakeVisionClient(
        response=VisionResponse(parsed=parsed, raw_response=json.dumps(parsed, sort_keys=True)),
    )

    artifact = run_rubric(client, (_PNG_BYTES,), axtree_text=_AXTREE_TEXT)

    assert artifact.counts == Rubric()
    assert artifact.parse_errors  # populated
    assert any("unknown_category" in err for err in artifact.parse_errors)


def test_run_rubric_with_negative_count_collapses_to_parse_error() -> None:
    """A negative count violates ``ge=0`` in :class:`Rubric` and surfaces as a parse error."""
    parsed = _all_zero_counts() | {"nav": -1}
    client = _FakeVisionClient(
        response=VisionResponse(parsed=parsed, raw_response=json.dumps(parsed, sort_keys=True)),
    )

    artifact = run_rubric(client, (_PNG_BYTES,), axtree_text=_AXTREE_TEXT)

    assert artifact.counts == Rubric()
    assert artifact.parse_errors
    # The schema-validation error mentions the offending field.
    assert any("nav" in err for err in artifact.parse_errors)


def test_run_rubric_preserves_upstream_parse_errors_on_schema_failure() -> None:
    """Upstream ``VisionResponse.parse_errors`` are kept alongside schema errors."""
    parsed = _all_zero_counts() | {"unknown_category": 1}
    client = _FakeVisionClient(
        response=VisionResponse(
            parsed=parsed,
            raw_response="{}",
            parse_errors=("upstream warning",),
        ),
    )

    artifact = run_rubric(client, (_PNG_BYTES,), axtree_text=_AXTREE_TEXT)

    assert "upstream warning" in artifact.parse_errors
    assert any("unknown_category" in err for err in artifact.parse_errors)


# ---------------------------------------------------------------------------
# Artifact serialization
# ---------------------------------------------------------------------------


def test_write_rubric_artifact_emits_required_fields(tmp_path: Path) -> None:
    """Artifact JSON contains every M2-required field."""
    artifact = RubricArtifact(
        prompt_version=RUBRIC_PROMPT_VERSION,
        model="claude-sonnet-4-6",
        temperature=0.0,
        counts=Rubric(nav=1, footer=2),
        raw_response='{"nav": 1, "footer": 2}',
        parse_errors=(),
    )
    path = tmp_path / "homepage.rubric.json"

    write_rubric_artifact(artifact, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["prompt_version"] == RUBRIC_PROMPT_VERSION
    assert payload["model"] == "claude-sonnet-4-6"
    assert payload["temperature"] == 0.0
    assert payload["counts"]["nav"] == 1
    assert payload["counts"]["footer"] == 2
    assert payload["raw_response"] == '{"nav": 1, "footer": 2}'
    assert payload["parse_errors"] == []


def test_write_rubric_artifact_is_byte_stable(tmp_path: Path) -> None:
    """Two writes of the same artifact produce identical bytes."""
    artifact = RubricArtifact(
        prompt_version=RUBRIC_PROMPT_VERSION,
        model="gpt-4o",
        temperature=0.0,
        counts=Rubric(),
        raw_response="{}",
        parse_errors=("warn",),
    )
    a = tmp_path / "a.rubric.json"
    b = tmp_path / "b.rubric.json"

    write_rubric_artifact(artifact, a)
    write_rubric_artifact(artifact, b)

    assert a.read_bytes() == b.read_bytes()
    # Trailing newline preserved.
    assert a.read_bytes().endswith(b"\n")


def test_rubric_artifact_is_closed_extra_forbid() -> None:
    """The artifact pydantic model rejects unknown keys at parse time."""
    payload = {
        "prompt_version": RUBRIC_PROMPT_VERSION,
        "model": "claude-sonnet-4-6",
        "temperature": 0.0,
        "counts": Rubric().model_dump(mode="json"),
        "raw_response": "{}",
        "parse_errors": [],
        "unexpected": "field",
    }
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RubricArtifact.model_validate(payload)
