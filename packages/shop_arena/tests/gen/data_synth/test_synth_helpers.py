"""Unit tests for :mod:`shop_arena.gen.data_synth._synth_helpers`.

The helpers underpin the T3.4 single-LLM-call steps; the parse paths
they own (fence stripping, JSON-object / JSON-array discrimination,
empty-response handling) are exercised directly here so the per-step
suites can stay focused on schema validation.
"""

from __future__ import annotations

import pytest

from shop_arena.gen.data_synth._synth_helpers import (
    StageSynthError,
    parse_json_array,
    parse_json_object,
)


def test_parse_json_object_decodes_plain_object() -> None:
    assert parse_json_object('{"a": 1}', step_id="t") == {"a": 1}


def test_parse_json_object_strips_code_fence() -> None:
    fenced = '```json\n{"a": 1}\n```'
    assert parse_json_object(fenced, step_id="t") == {"a": 1}


def test_parse_json_object_rejects_empty_response() -> None:
    with pytest.raises(StageSynthError, match="empty response"):
        parse_json_object("   ", step_id="t")


def test_parse_json_object_rejects_array() -> None:
    with pytest.raises(StageSynthError, match="JSON object"):
        parse_json_object("[]", step_id="t")


def test_parse_json_object_rejects_invalid_json() -> None:
    with pytest.raises(StageSynthError, match="not valid JSON"):
        parse_json_object("{not json", step_id="t")


def test_parse_json_object_step_id_in_error() -> None:
    with pytest.raises(StageSynthError, match="my_step:"):
        parse_json_object("not json", step_id="my_step")


def test_parse_json_array_decodes_plain_array() -> None:
    assert parse_json_array("[1, 2]", step_id="t") == [1, 2]


def test_parse_json_array_strips_code_fence() -> None:
    fenced = "```json\n[1, 2]\n```"
    assert parse_json_array(fenced, step_id="t") == [1, 2]


def test_parse_json_array_rejects_object() -> None:
    with pytest.raises(StageSynthError, match="JSON array"):
        parse_json_array("{}", step_id="t")


def test_parse_json_array_rejects_empty_response() -> None:
    with pytest.raises(StageSynthError, match="empty response"):
        parse_json_array("", step_id="t")
