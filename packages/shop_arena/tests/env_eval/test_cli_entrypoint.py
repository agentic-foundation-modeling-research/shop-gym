"""Console-script wiring: ``shop-env-eval`` resolves to ``cli:main``.

The argparse surface itself is exercised in
``test_cli_run.py``; this file only checks that ``[project.scripts]`` is
registered correctly so an installed package exposes the binary at the
documented import path (impl plan M0 — line 18).
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata

import pytest

from shop_arena.env_eval import cli as env_eval_cli


def test_console_script_registered() -> None:
    """``[project.scripts]`` exposes ``shop-env-eval`` pointing at ``cli:main``."""
    entry_points = importlib_metadata.entry_points(group="console_scripts")
    matches = [ep for ep in entry_points if ep.name == "shop-env-eval"]
    assert len(matches) == 1, "shop-env-eval console script not registered"
    assert matches[0].value == "shop_arena.env_eval.cli:main"


def test_console_script_loads_to_main() -> None:
    """The registered entry point loads to the same callable as ``cli.main``."""
    (entry,) = (
        ep
        for ep in importlib_metadata.entry_points(group="console_scripts")
        if ep.name == "shop-env-eval"
    )
    assert entry.load() is env_eval_cli.main


def test_main_with_no_args_exits_via_argparse() -> None:
    """``shop-env-eval`` (no subcommand) is rejected by argparse, not silently no-op."""
    with pytest.raises(SystemExit) as excinfo:
        env_eval_cli.main([])
    # argparse uses exit code 2 for usage errors.
    assert excinfo.value.code == 2
