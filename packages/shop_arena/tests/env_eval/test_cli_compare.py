"""CLI tests for ``shop-env-eval compare``."""

from __future__ import annotations

from pathlib import Path

import pytest

from shop_arena.env_eval import cli as cli_mod
from shop_arena.env_eval.cli import EXIT_OK, EXIT_USAGE, main
from shop_arena.env_eval.structure.compare import CompareConfig, CompareResult


def test_compare_cli_threads_urls_and_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The URL-only CLI constructs one shared cohort configuration."""
    captured: list[CompareConfig] = []
    report_path = tmp_path / "variance.json"

    def _fake_compare(config: CompareConfig) -> CompareResult:
        captured.append(config)
        return CompareResult(comparison_dir=tmp_path, report_path=report_path)

    monkeypatch.setattr(cli_mod, "compare_urls", _fake_compare)
    monkeypatch.setattr(
        cli_mod,
        "load_project_env",
        lambda: pytest.fail("compare must not load LLM credentials"),
    )

    rc = main(
        [
            "compare",
            "https://a.example",
            "https://b.example",
            "--out",
            str(tmp_path),
            "--viewport",
            "1280x720",
            "--max-hops",
            "2",
            "--rediscover",
        ],
    )

    assert rc == EXIT_OK
    assert capsys.readouterr().out.strip() == str(report_path)
    (config,) = captured
    assert config.urls == ("https://a.example", "https://b.example")
    assert config.out_dir == tmp_path
    assert config.viewport == (1280, 720)
    assert config.max_hops == 2
    assert config.rediscover is True


def test_compare_cli_rejects_one_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One URL returns a configuration error without running evaluation."""

    def _fail(_config: CompareConfig) -> CompareResult:  # pragma: no cover
        pytest.fail("compare_urls must not run with one sample")

    monkeypatch.setattr(cli_mod, "compare_urls", _fail)
    monkeypatch.setattr(
        cli_mod,
        "load_project_env",
        lambda: pytest.fail("compare must not load LLM credentials"),
    )

    rc = main(["compare", "https://only.example"])

    assert rc == EXIT_USAGE
    assert "invalid comparison configuration" in capsys.readouterr().err


def test_help_lists_compare_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    """Top-level help advertises structural comparison."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    assert "compare" in capsys.readouterr().out


def test_compare_help_is_explicitly_llm_free(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Compare exposes no model or rubric options."""
    with pytest.raises(SystemExit) as excinfo:
        main(["compare", "--help"])
    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "without LLM calls" in output
    assert "--no-rubric" not in output
    assert "--rubric-model" not in output
