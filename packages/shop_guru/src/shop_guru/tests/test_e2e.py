"""Unit tests for the E2E generator."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from shop_guru.config import Shop
from shop_guru.generators import e2e
from shop_guru.io import load_shop_data


@pytest.fixture
def tiny_data(tiny_shop_arena_root, tiny_shop: Shop) -> dict:
    return load_shop_data(tiny_shop)


@patch("shop_guru.generators.e2e.litellm")
def test_e2e_generate_success(mock_litellm, tiny_shop: Shop, tiny_data: dict) -> None:
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "tiny-e2e-v1-1",
                                "type": "shopping",
                                "intent": "A test task.",
                            }
                        ]
                    }
                )
            )
        )
    ]
    mock_litellm.completion.return_value = mock_response

    tasks = e2e.generate(tiny_shop, tiny_data, count=1)
    assert len(tasks) == 1
    assert tasks[0]["id"] == "tiny-e2e-v1-1"


@patch("shop_guru.generators.e2e.litellm")
def test_e2e_generate_error_handling(mock_litellm, tiny_shop: Shop, tiny_data: dict) -> None:
    mock_litellm.completion.side_effect = Exception("API Error")
    tasks = e2e.generate(tiny_shop, tiny_data)
    assert tasks == []
