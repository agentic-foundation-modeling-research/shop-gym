"""Tests for `harness.telemetry.secrets`."""

from __future__ import annotations

from harness.telemetry import scrub_secrets

_SCRUB_SAMPLE_INT = 42


def test_scrub_secrets_redacts_top_level_secret_keys() -> None:
    out = scrub_secrets({"api_key": "sk-abc", "model": "gpt-5"})
    assert out == {"api_key": "***REDACTED***", "model": "gpt-5"}


def test_scrub_secrets_handles_common_secret_names() -> None:
    payload = {
        "api_key": "x",
        "API_KEY": "x",
        "ApiKey": "x",
        "api-key": "x",
        "openai_api_key": "x",
        "secret": "x",
        "client_secret": "x",
        "password": "x",
        "auth_token": "x",
        "access_key": "x",
    }
    redacted = scrub_secrets(payload)
    assert all(v == "***REDACTED***" for v in redacted.values())


def test_scrub_secrets_does_not_redact_innocent_keys() -> None:
    out = scrub_secrets({"runtime": "replay", "max_iters": 3, "timeout": 60.0})
    assert out == {"runtime": "replay", "max_iters": 3, "timeout": 60.0}


def test_scrub_secrets_recurses_into_nested_mappings() -> None:
    out = scrub_secrets(
        {
            "runtime": {"name": "claude_code", "api_key": "sk-abc"},
            "config": {"max_iters": 3, "secrets": {"token": "t"}},
        }
    )
    assert out == {
        "runtime": {"name": "claude_code", "api_key": "***REDACTED***"},
        "config": {"max_iters": 3, "secrets": "***REDACTED***"},
    }


def test_scrub_secrets_recurses_into_lists() -> None:
    out = scrub_secrets({"runtimes": [{"api_key": "k1"}, {"api_key": "k2"}]})
    assert out == {"runtimes": [{"api_key": "***REDACTED***"}, {"api_key": "***REDACTED***"}]}


def test_scrub_secrets_returns_scalars_unchanged() -> None:
    assert scrub_secrets("hello") == "hello"
    assert scrub_secrets(_SCRUB_SAMPLE_INT) == _SCRUB_SAMPLE_INT
    assert scrub_secrets(None) is None
