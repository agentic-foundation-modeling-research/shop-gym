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
            "https://c.example",
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
    assert config.urls == (
        "https://a.example",
        "https://b.example",
        "https://c.example",
    )
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


def test_compare_cli_threads_independent_visual_models_and_loads_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Repeated visual flags preserve model order and opt into project env."""
    captured: list[CompareConfig] = []
    loaded: list[bool] = []
    report_path = tmp_path / "variance.json"

    def _fake_compare(config: CompareConfig) -> CompareResult:
        captured.append(config)
        return CompareResult(comparison_dir=tmp_path, report_path=report_path)

    monkeypatch.setattr(cli_mod, "compare_urls", _fake_compare)
    monkeypatch.setattr(cli_mod, "load_project_env", lambda: loaded.append(True))

    rc = main(
        [
            "compare",
            "https://a.example",
            "https://b.example",
            "--visual-judge-model",
            "gpt-5",
            "--visual-judge-model",
            "claude-sonnet-4-6",
        ],
    )

    assert rc == EXIT_OK
    assert capsys.readouterr().out.strip() == str(report_path)
    assert loaded == [True]
    assert captured[0].visual_judge_models == ("gpt-5", "claude-sonnet-4-6")


def test_help_lists_compare_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    """Top-level help advertises structural comparison."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    assert "compare" in capsys.readouterr().out


def test_compare_help_describes_optional_visual_judge(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Compare keeps its deterministic core while exposing one visual option."""
    with pytest.raises(SystemExit) as excinfo:
        main(["compare", "--help"])
    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "LLM-free" in output
    assert "--visual-judge-model" in output
    assert "--no-rubric" not in output
    assert "--rubric-model" not in output
