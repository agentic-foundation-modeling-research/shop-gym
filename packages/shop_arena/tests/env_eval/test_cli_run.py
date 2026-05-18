"""Unit tests for ``shop-env-eval run`` (impl plan M1).

Covers spec §5.9 + SC1: ``shop-env-eval run <url>`` builds an
:class:`~shop_arena.env_eval.config.EvalConfig` from the argparse
namespace, invokes :func:`shop_arena.env_eval.pipeline.evaluate`, and
prints the resulting ``metrics.json`` path on stdout. The pipeline call
is monkey-patched so these tests stay hermetic — the actual orchestrator
lands in subsequent M1 tasks.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shop_arena.env_eval import cli as cli_mod
from shop_arena.env_eval.cli import EXIT_OK, EXIT_USAGE, main
from shop_arena.env_eval.config import (
    DEFAULT_MAX_HOPS,
    DEFAULT_PAGES_CLASSIFIER_MODEL,
    DEFAULT_RUBRIC_MODEL,
    DEFAULT_VIEWPORT,
    EvalConfig,
    EvalResult,
)
from shop_arena.env_eval.errors import ShopUnreachableError
from shop_arena.util import _dotenv

URL = "https://example-shop.com"


def _install_fake_evaluate(
    monkeypatch: pytest.MonkeyPatch,
    *,
    metrics_path: Path,
) -> list[EvalConfig]:
    """Replace ``cli.evaluate`` with a recorder returning a fixed result."""
    captured: list[EvalConfig] = []

    def _fake(config: EvalConfig) -> EvalResult:
        captured.append(config)
        return EvalResult(
            run_dir=metrics_path.parent,
            metrics_path=metrics_path,
        )

    monkeypatch.setattr(cli_mod, "evaluate", _fake)
    return captured


def test_run_prints_metrics_path_on_stdout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """SC1: ``shop-env-eval run <url>`` prints ``metrics.json`` path on stdout."""
    metrics_path = tmp_path / "run-id" / "metrics.json"
    captured_configs = _install_fake_evaluate(monkeypatch, metrics_path=metrics_path)

    rc = main(["run", URL])

    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert out.strip() == str(metrics_path)
    # Stdout is a single line so downstream tooling can pipe it directly.
    assert out.count("\n") == 1
    assert len(captured_configs) == 1
    assert captured_configs[0].url == URL


def test_run_uses_defaults_when_flags_omitted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Omitted flags fall back to the documented EvalConfig defaults."""
    metrics_path = tmp_path / "metrics.json"
    captured = _install_fake_evaluate(monkeypatch, metrics_path=metrics_path)

    main(["run", URL])

    (config,) = captured
    assert config.url == URL
    assert config.out_dir is None
    assert config.viewport == DEFAULT_VIEWPORT
    assert config.max_hops == DEFAULT_MAX_HOPS
    assert config.rubric_model == DEFAULT_RUBRIC_MODEL
    assert config.pages_classifier_model == DEFAULT_PAGES_CLASSIFIER_MODEL
    assert config.no_rubric is False
    assert config.rediscover is False
    assert config.shop_name is None


def test_run_threads_every_flag_into_eval_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Each CLI flag maps to the matching EvalConfig field."""
    metrics_path = tmp_path / "metrics.json"
    captured = _install_fake_evaluate(monkeypatch, metrics_path=metrics_path)
    out_dir = tmp_path / "custom-run"

    rc = main(
        [
            "run",
            URL,
            "--out",
            str(out_dir),
            "--viewport",
            "1280x720",
            "--max-hops",
            "5",
            "--rubric-model",
            "gpt-4o",
            "--pages-classifier-model",
            "gpt-5-nano",
            "--no-rubric",
            "--rediscover",
            "--shop-name",
            "my-shop",
        ],
    )

    assert rc == EXIT_OK
    (config,) = captured
    assert config.url == URL
    assert config.out_dir == out_dir
    assert config.viewport == (1280, 720)
    assert config.max_hops == 5
    assert config.rubric_model == "gpt-4o"
    assert config.pages_classifier_model == "gpt-5-nano"
    assert config.no_rubric is True
    assert config.rediscover is True
    assert config.shop_name == "my-shop"


def test_run_viewport_accepts_uppercase_x(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``--viewport`` accepts ``1440X900`` (case-insensitive separator)."""
    captured = _install_fake_evaluate(
        monkeypatch,
        metrics_path=tmp_path / "metrics.json",
    )

    main(["run", URL, "--viewport", "1440X900"])

    (config,) = captured
    assert config.viewport == (1440, 900)


@pytest.mark.parametrize("bad", ["1440", "1440x", "x900", "1440x900x10", "axb", "0x900", "-1x900"])
def test_run_rejects_malformed_viewport(
    monkeypatch: pytest.MonkeyPatch,
    bad: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Argparse surfaces malformed ``--viewport`` strings as a usage error."""

    # evaluate must NOT be called when argparse rejects --viewport.
    def _fail(_config: EvalConfig) -> EvalResult:  # pragma: no cover
        pytest.fail("evaluate must not run when --viewport is malformed")

    monkeypatch.setattr(cli_mod, "evaluate", _fail)

    with pytest.raises(SystemExit) as excinfo:
        main(["run", URL, "--viewport", bad])

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "viewport" in err.lower()


def test_run_missing_url_is_argparse_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The ``url`` positional is required; argparse exits 2 without it."""
    with pytest.raises(SystemExit) as excinfo:
        main(["run"])
    assert excinfo.value.code == 2
    assert "url" in capsys.readouterr().err.lower()


def test_run_truly_unknown_command_is_argparse_error() -> None:
    """argparse rejects subcommands outside the documented surface."""
    with pytest.raises(SystemExit) as excinfo:
        main(["frobnicate"])
    assert excinfo.value.code == 2


def test_run_eval_config_validation_error_returns_exit_usage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A pydantic ValidationError on EvalConfig is surfaced as EXIT_USAGE."""

    # Negative --max-hops violates EvalConfig's ``ge=0`` constraint.
    def _fail(_config: EvalConfig) -> EvalResult:  # pragma: no cover
        pytest.fail("evaluate must not run when EvalConfig validation fails")

    monkeypatch.setattr(cli_mod, "evaluate", _fail)

    rc = main(["run", URL, "--max-hops", "-1"])

    assert rc == EXIT_USAGE
    err = capsys.readouterr().err
    assert "shop-env-eval" in err
    assert "invalid configuration" in err


def test_run_shop_unreachable_error_returns_exit_usage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``ShopUnreachableError`` (and any EnvEvalError) maps to EXIT_USAGE + stderr."""

    def _raise(_config: EvalConfig) -> EvalResult:
        raise ShopUnreachableError("homepage timed out")

    monkeypatch.setattr(cli_mod, "evaluate", _raise)

    rc = main(["run", URL])

    assert rc == EXIT_USAGE
    err = capsys.readouterr().err
    assert "shop-env-eval: homepage timed out" in err


def test_run_accepts_kwargs_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Boolean flags default to ``False`` and are settable independently."""
    captured = _install_fake_evaluate(
        monkeypatch,
        metrics_path=tmp_path / "metrics.json",
    )

    main(["run", URL, "--no-rubric"])
    main(["run", URL, "--rediscover"])

    first, second = captured
    assert first.no_rubric is True and first.rediscover is False
    assert second.no_rubric is False and second.rediscover is True


def test_help_lists_run_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    """``shop-env-eval --help`` advertises the ``run`` subcommand."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "run" in out


def test_run_loads_project_dotenv_before_evaluate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``main()`` honours a project-root ``.env`` so operators do not need to ``export``."""
    sentinel = "SHOP_ENV_EVAL_DOTENV_SENTINEL"
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"{sentinel}=loaded-from-dotenv\n", encoding="utf-8")
    monkeypatch.delenv(sentinel, raising=False)
    _dotenv.reset_for_testing()
    snapshot = dict(os.environ)
    try:
        observed: dict[str, str | None] = {}
        metrics_path = tmp_path / "metrics.json"

        def _fake_evaluate(config: EvalConfig) -> EvalResult:
            observed["sentinel"] = os.environ.get(sentinel)
            observed["url"] = config.url
            return EvalResult(run_dir=metrics_path.parent, metrics_path=metrics_path)

        monkeypatch.setattr(cli_mod, "evaluate", _fake_evaluate)

        rc = main(["run", URL])

        assert rc == EXIT_OK
        # Loader fired before ``evaluate`` (and thus before the rubric client).
        assert observed["sentinel"] == "loaded-from-dotenv"
        assert observed["url"] == URL
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        _dotenv.reset_for_testing()


def test_run_help_lists_every_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """``shop-env-eval run --help`` lists each documented flag (spec §5.9)."""
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for flag in (
        "--out",
        "--viewport",
        "--max-hops",
        "--rubric-model",
        "--no-rubric",
        "--rediscover",
        "--shop-name",
    ):
        assert flag in out, f"missing flag in --help: {flag}"
