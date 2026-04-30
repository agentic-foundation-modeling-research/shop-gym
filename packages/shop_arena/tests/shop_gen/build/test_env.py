"""Unit tests for :mod:`shop_gen.build.env`.

Covers the T5.1 requirements from
``docs/impl/shop_gen_implementation.md``:

* ``clone_template`` copies the vendored Hydrogen template tree
  byte-for-byte (modulo ``.env`` which is later overwritten).
* ``write_env_file`` produces a ``.env`` file containing the resolved
  sidecar URL plus the mock storefront credentials the Hydrogen
  runtime expects on ``process.env``.
* Both steps satisfy the :class:`Step` Protocol with the canonical
  id / phase / inputs / outputs / depends_on / version surface.
"""

from __future__ import annotations

import filecmp
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shop_gen.build.env import CloneTemplateStep, WriteEnvFileStep
from shop_gen.config import ShopGenConfig
from shop_gen.steps.base import Step, StepContext, StepInput

_TEMPLATE_DIR: Path = (
    Path(__file__).resolve().parents[3] / "src" / "shop_gen" / "templates" / "hydrogen"
)
"""Vendored Hydrogen template the steps copy from."""

_EXPECTED_ENV_KEYS: tuple[str, ...] = (
    "PUBLIC_STORE_DOMAIN",
    "SESSION_SECRET",
    "PUBLIC_STOREFRONT_API_TOKEN",
    "PUBLIC_STOREFRONT_ID",
    "PUBLIC_FOOTER_MENU_HANDLES",
)


@dataclass
class _RecordingCompleter:
    """Stub :class:`LLMCompleter` that fails the test if invoked."""

    prompts: list[str] = field(default_factory=list)

    def complete(self, prompt: str, *, timeout: float) -> str:
        del timeout
        self.prompts.append(prompt)
        raise AssertionError("env-setup steps must not invoke the LLM")


def _make_seed(tmp_path: Path) -> Path:
    """Create a minimal seed directory so :class:`ShopGenConfig` accepts it."""
    seed = tmp_path / "seed"
    (seed / "artifact").mkdir(parents=True)
    return seed


def _make_ctx(tmp_path: Path) -> StepContext:
    """Build a :class:`StepContext` rooted at ``tmp_path / "out"``."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    return StepContext(config=cfg, out_dir=out_dir, runtime=_RecordingCompleter())


# --------------------------------------------------------------------------- #
# CloneTemplateStep — step contract
# --------------------------------------------------------------------------- #


def test_clone_template_step_satisfies_step_protocol() -> None:
    step = CloneTemplateStep()

    assert isinstance(step, Step)
    assert step.id == "clone_template"
    assert step.phase == "build"
    assert step.inputs == []
    assert step.outputs == [Path("hydrogen") / "package.json"]
    assert step.depends_on == []
    assert step.version == 3  # noqa: PLR2004


# --------------------------------------------------------------------------- #
# CloneTemplateStep — run
# --------------------------------------------------------------------------- #


def test_clone_template_copies_tree_into_hydrogen_subdir(tmp_path: Path) -> None:
    """The step recursively copies the vendored template under ``out_dir``."""
    ctx = _make_ctx(tmp_path)

    CloneTemplateStep().run(ctx)

    target = ctx.out_dir / "hydrogen"
    assert target.is_dir()
    assert (target / "package.json").is_file()
    assert (target / "server.mjs").is_file()
    # Nested directories are preserved.
    assert (target / "app").is_dir()


def test_clone_template_tree_is_byte_equivalent_to_template(tmp_path: Path) -> None:
    """Spec §5.5.1 check: clone is byte-faithful (modulo subsequent .env overwrite)."""
    ctx = _make_ctx(tmp_path)

    CloneTemplateStep().run(ctx)

    # ``node_modules`` is intentionally skipped by the clone step
    # (see :class:`CloneTemplateStep.run`). Compare against the
    # template with the same exclusion so the test stays green even
    # if a developer left a stray ``node_modules`` in the template
    # directory from an exploratory ``pnpm install``.
    diff = filecmp.dircmp(_TEMPLATE_DIR, ctx.out_dir / "hydrogen", ignore=["node_modules"])
    assert _no_diff(diff), f"clone diverged from template: {_summarize_diff(diff)}"


def test_clone_template_does_not_invoke_llm(tmp_path: Path) -> None:
    """The clone is fully deterministic; ``ctx.runtime`` must stay untouched."""
    ctx = _make_ctx(tmp_path)
    completer = ctx.runtime
    assert isinstance(completer, _RecordingCompleter)

    CloneTemplateStep().run(ctx)

    assert completer.prompts == []


def test_clone_template_is_idempotent(tmp_path: Path) -> None:
    """Re-running against the same workspace overwrites in place without error."""
    ctx = _make_ctx(tmp_path)

    step = CloneTemplateStep()
    step.run(ctx)
    first = (ctx.out_dir / "hydrogen" / "package.json").read_bytes()
    step.run(ctx)
    second = (ctx.out_dir / "hydrogen" / "package.json").read_bytes()

    assert first == second


def test_clone_template_excludes_node_modules_from_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stray ``node_modules/`` in the source template is not carried into the clone.

    Pnpm's strict layout uses symlinks to keep a single physical copy
    of every package. ``shutil.copytree`` defaults to ``symlinks=False``
    which dereferences those symlinks and produces multiple physical
    React copies, breaking SSR. The clone step skips ``node_modules/``
    so a follow-up ``pnpm install --frozen-lockfile`` always populates
    a clean tree.
    """
    fake_template = tmp_path / "fake_template"
    fake_template.mkdir()
    (fake_template / "package.json").write_text("{}", encoding="utf-8")
    nested = fake_template / "node_modules" / ".pnpm" / "react@18.3.1"
    nested.mkdir(parents=True)
    (nested / "sentinel.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr("shop_gen.build.env._TEMPLATE_DIR", fake_template)

    ctx = _make_ctx(tmp_path)
    CloneTemplateStep().run(ctx)

    target = ctx.out_dir / "hydrogen"
    assert (target / "package.json").is_file()
    assert not (target / "node_modules").exists()


def test_clone_template_purges_stale_node_modules_from_destination(
    tmp_path: Path,
) -> None:
    """A pre-existing corrupted ``node_modules/`` in the destination is wiped.

    ``shutil.copytree(dirs_exist_ok=True)`` does not descend into directories
    listed in ``ignore`` — it neither writes them nor cleans them up. So a
    workspace that was cloned by a *prior* version of this step (which
    dereferenced the template's pnpm symlinks into duplicate React copies)
    would keep that corrupt tree forever, even though the new step skips
    ``node_modules/`` on read. ``CloneTemplateStep.run`` actively removes
    any ``node_modules/`` from the destination before the copy so the next
    ``pnpm install --frozen-lockfile`` rebuilds from a clean slate.
    """
    ctx = _make_ctx(tmp_path)
    # First clone produces a clean tree.
    CloneTemplateStep().run(ctx)
    target = ctx.out_dir / "hydrogen"

    # Simulate a corrupted node_modules left over from a pre-fix run.
    nested = target / "node_modules" / ".pnpm" / "react@18.3.1"
    nested.mkdir(parents=True)
    (nested / "react.development.js").write_text("// duplicate", encoding="utf-8")
    assert (target / "node_modules").is_dir()

    # Second clone purges the stale node_modules.
    CloneTemplateStep().run(ctx)
    assert not (target / "node_modules").exists()
    # Source files still land normally.
    assert (target / "package.json").is_file()


# --------------------------------------------------------------------------- #
# WriteEnvFileStep — step contract
# --------------------------------------------------------------------------- #


def test_write_env_file_step_satisfies_step_protocol() -> None:
    step = WriteEnvFileStep()

    assert isinstance(step, Step)
    assert step.id == "write_env_file"
    assert step.phase == "build"
    assert step.inputs == [StepInput(step_id="clone_template")]
    assert step.outputs == [Path("hydrogen") / ".env"]
    assert step.depends_on == ["clone_template"]
    assert step.version == 1


# --------------------------------------------------------------------------- #
# WriteEnvFileStep — run
# --------------------------------------------------------------------------- #


def test_write_env_file_writes_expected_keys(tmp_path: Path) -> None:
    """T5.1 check: ``.env`` contains the keys the Hydrogen runtime needs."""
    ctx = _make_ctx(tmp_path)
    CloneTemplateStep().run(ctx)

    WriteEnvFileStep().run(ctx)

    env_path = ctx.out_dir / "hydrogen" / ".env"
    assert env_path.is_file()
    contents = env_path.read_text(encoding="utf-8")
    for key in _EXPECTED_ENV_KEYS:
        assert f"{key}=" in contents, f"missing {key} in .env"


def test_write_env_file_resolves_sidecar_url_to_localhost_port(tmp_path: Path) -> None:
    """``PUBLIC_STORE_DOMAIN`` points at ``http://localhost:<free-port>``."""
    ctx = _make_ctx(tmp_path)
    CloneTemplateStep().run(ctx)

    WriteEnvFileStep().run(ctx)

    env_lines = (ctx.out_dir / "hydrogen" / ".env").read_text(encoding="utf-8").splitlines()
    domain_line = next(line for line in env_lines if line.startswith("PUBLIC_STORE_DOMAIN="))
    value = domain_line.split("=", 1)[1]
    assert value.startswith("http://localhost:")
    port = int(value.removeprefix("http://localhost:"))
    # ``socket.bind(0)`` returns an ephemeral port (>= 1024 on every
    # mainstream OS); reject any value that suggests we accidentally
    # hard-coded the placeholder.
    _min_ephemeral_port = 1024
    assert port >= _min_ephemeral_port


def test_write_env_file_overwrites_template_placeholder(tmp_path: Path) -> None:
    """The clone ships a placeholder ``.env``; the step must overwrite it."""
    ctx = _make_ctx(tmp_path)
    CloneTemplateStep().run(ctx)
    placeholder = (ctx.out_dir / "hydrogen" / ".env").read_text(encoding="utf-8")
    assert "PUBLIC_STORE_DOMAIN" not in placeholder

    WriteEnvFileStep().run(ctx)

    rewritten = (ctx.out_dir / "hydrogen" / ".env").read_text(encoding="utf-8")
    assert "PUBLIC_STORE_DOMAIN=" in rewritten
    assert rewritten != placeholder


def test_write_env_file_does_not_invoke_llm(tmp_path: Path) -> None:
    """The step is deterministic up to port selection; never calls the LLM."""
    ctx = _make_ctx(tmp_path)
    CloneTemplateStep().run(ctx)
    completer = ctx.runtime
    assert isinstance(completer, _RecordingCompleter)

    WriteEnvFileStep().run(ctx)

    assert completer.prompts == []


def test_write_env_file_raises_when_hydrogen_dir_missing(tmp_path: Path) -> None:
    """Running ``write_env_file`` before ``clone_template`` is a hard failure."""
    ctx = _make_ctx(tmp_path)

    with pytest.raises(FileNotFoundError, match="hydrogen tree not found"):
        WriteEnvFileStep().run(ctx)


# --------------------------------------------------------------------------- #
# WriteEnvFileStep — footer_menu_handles (T3.5)
# --------------------------------------------------------------------------- #


def _read_footer_handles_line(env_path: Path) -> str:
    """Return the ``PUBLIC_FOOTER_MENU_HANDLES=...`` line value."""
    contents = env_path.read_text(encoding="utf-8").splitlines()
    line = next(line for line in contents if line.startswith("PUBLIC_FOOTER_MENU_HANDLES="))
    return line.split("=", 1)[1]


def test_write_env_file_emits_default_footer_handle_when_unset(tmp_path: Path) -> None:
    """Existing callers (no kwarg) get the legacy single-handle fallback."""
    ctx = _make_ctx(tmp_path)
    CloneTemplateStep().run(ctx)

    WriteEnvFileStep().run(ctx)

    env_path = ctx.out_dir / "hydrogen" / ".env"
    assert _read_footer_handles_line(env_path) == "footer"


def test_write_env_file_emits_default_footer_handle_when_none(tmp_path: Path) -> None:
    """Explicit ``None`` kwarg matches the no-kwarg behavior."""
    ctx = _make_ctx(tmp_path)
    CloneTemplateStep().run(ctx)

    WriteEnvFileStep(footer_menu_handles=None).run(ctx)

    env_path = ctx.out_dir / "hydrogen" / ".env"
    assert _read_footer_handles_line(env_path) == "footer"


def test_write_env_file_emits_default_footer_handle_when_empty_list(tmp_path: Path) -> None:
    """An empty list normalizes to the ``footer`` fallback (matches the loader)."""
    ctx = _make_ctx(tmp_path)
    CloneTemplateStep().run(ctx)

    WriteEnvFileStep(footer_menu_handles=[]).run(ctx)

    env_path = ctx.out_dir / "hydrogen" / ".env"
    assert _read_footer_handles_line(env_path) == "footer"


def test_write_env_file_emits_csv_when_handles_provided(tmp_path: Path) -> None:
    """Multiple handles serialize as a comma-separated list (no spaces)."""
    ctx = _make_ctx(tmp_path)
    CloneTemplateStep().run(ctx)

    WriteEnvFileStep(
        footer_menu_handles=["footer-shop", "footer-trust", "footer-legal"],
    ).run(ctx)

    env_path = ctx.out_dir / "hydrogen" / ".env"
    assert _read_footer_handles_line(env_path) == "footer-shop,footer-trust,footer-legal"


def test_write_env_file_normalizes_handles_to_match_loader(tmp_path: Path) -> None:
    """Whitespace is trimmed; empties and duplicates are dropped (loader parity)."""
    ctx = _make_ctx(tmp_path)
    CloneTemplateStep().run(ctx)

    WriteEnvFileStep(
        footer_menu_handles=["  footer  ", "", " trust ", "footer", "   "],
    ).run(ctx)

    env_path = ctx.out_dir / "hydrogen" / ".env"
    # Expected: trimmed, empties dropped, duplicates de-duped (first wins).
    assert _read_footer_handles_line(env_path) == "footer,trust"


def test_write_env_file_falls_back_when_input_is_all_whitespace(tmp_path: Path) -> None:
    """All-whitespace input degrades to the ``footer`` fallback."""
    ctx = _make_ctx(tmp_path)
    CloneTemplateStep().run(ctx)

    WriteEnvFileStep(footer_menu_handles=["   ", "\t", ""]).run(ctx)

    env_path = ctx.out_dir / "hydrogen" / ".env"
    assert _read_footer_handles_line(env_path) == "footer"


def test_write_env_file_step_contract_unchanged_with_footer_kwarg() -> None:
    """Passing ``footer_menu_handles`` does not perturb the Step Protocol surface."""
    step = WriteEnvFileStep(footer_menu_handles=["footer-a", "footer-b"])

    assert isinstance(step, Step)
    assert step.id == "write_env_file"
    assert step.phase == "build"
    assert step.inputs == [StepInput(step_id="clone_template")]
    assert step.outputs == [Path("hydrogen") / ".env"]
    assert step.depends_on == ["clone_template"]
    assert step.version == 1


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _no_diff(diff: filecmp.dircmp[str]) -> bool:
    """Recursively check that ``filecmp.dircmp`` reports no differences."""
    if diff.left_only or diff.right_only or diff.diff_files or diff.funny_files:
        return False
    return all(_no_diff(sub) for sub in diff.subdirs.values())


def _summarize_diff(diff: filecmp.dircmp[str]) -> str:
    """Render a compact diff summary for assertion messages."""
    return (
        f"left_only={diff.left_only!r} right_only={diff.right_only!r} "
        f"diff_files={diff.diff_files!r} funny={diff.funny_files!r}"
    )
