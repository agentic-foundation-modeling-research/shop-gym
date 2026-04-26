"""Pipeline orchestrator for ``shop_explore`` runs.

Implements §5.2 + §5.10 of the ShopExplore spec
(``docs/specs/shop_arena/shop_explore.md``): the public :func:`explore`
function takes a validated :class:`~shop_explore.config.ExploreConfig`,
runs the deterministic prefetch step into a temporary seed directory,
loads the bundled prompt resources (``agents.md``, ``planner.md``,
``execute.md``, ``synthesize_manual.md``), drives the harness
``run_plan_exec_loop`` against the requested runtime, and finally calls
:func:`shop_explore.synthesize.synthesize` to publish the four
``manual.md`` / ``capabilities.json`` / ``stats.json`` /
``manifest.json`` artifacts under ``run_dir/artifact/`` (spec §5.10).

The synthesis step requires an LLM client. When the configured runtime
satisfies :class:`harness.runtimes.LLMCompleter` (``pi``, ``claude_code``),
the pipeline wraps it in a thin :class:`_RuntimeLLMClient` adapter so the
manual-merge call goes through the same model the runtime drives its
iterations with — resolving spec §8.2 open question 1 in favour of
"reuse harness runtime LLM" (impl plan T6.2). Runtimes that cannot
serve completions (e.g. :class:`harness.runtimes.replay.ReplayRuntime`)
raise :class:`SynthesisError` from :func:`build_runtime_llm`; callers
must inject an explicit ``llm`` keyword to :func:`explore` in that
case. There is no silent fallback — earlier revisions returned an empty
completion, which masked LLM-client misconfiguration.

The module is import-safe — no I/O at import time. Prompt resources are
read from disk only when :func:`explore` is invoked.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from harness import (
    AgentRuntime,
    PlanExecLoopConfig,
    Prompts,
    get_runtime,
    run_plan_exec_loop,
)
from harness.runtimes import LLMCompleter
from shop_explore._version import __version__
from shop_explore.config import ExploreConfig, ExploreResult
from shop_explore.prefetch import run as run_prefetch
from shop_explore.synthesize import LLMClient, SynthesisError, synthesize

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
"""Directory holding the bundled ``agents.md`` / ``planner.md`` / ``execute.md`` resources."""

_CAPABILITIES_SCHEMA_PATH = Path(__file__).resolve().parent / "capabilities" / "schema.py"
"""Source of truth for the ``{{CAPABILITIES_SCHEMA}}`` placeholder in ``agents.md`` (§5)."""

_PLAYWRIGHT_SKILL_RELPATH = "pi-playwright/skills/playwright-browser"
"""Relative path of the playwright skill under the JS package manager's global root."""

_DEFAULT_OUTPUT_ROOT = Path("outputs") / "shop_manuals"
"""Default parent of ``<domain>/<run_id>/`` when ``ExploreConfig.out_dir`` is omitted."""

RUN_ID_HASH_LEN = 8
"""Length of the SHA-256 prefix appended to the timestamp in a ``run_id`` (spec §5.4)."""

_log = logging.getLogger(__name__)


def explore(config: ExploreConfig, *, llm: LLMClient | None = None) -> ExploreResult:
    """Run the full ShopExplore pipeline for one storefront URL.

    Sequence (spec §5.2):

    1. Resolve ``run_dir`` from ``config.out_dir`` or the default
       ``outputs/shop_manuals/<domain>/<run_id>/`` layout.
    2. Run :func:`shop_explore.prefetch.run` into a temporary seed dir
       (the harness later copies that tree into ``run_dir/artifact/``).
    3. Load the bundled prompt resources.
    4. Build a :class:`harness.PlanExecLoopConfig` and invoke
       :func:`harness.run_plan_exec_loop` with the configured runtime.
    5. Return an :class:`ExploreResult` whose paths point at the
       eventual published artifacts under ``run_dir/artifact/``. These
       paths are forward declarations: synthesis (M3) is what actually
       creates the files at those locations.
    6. Run :func:`shop_explore.synthesize.synthesize` to publish
       ``manual.md`` / ``capabilities.json`` / ``stats.json`` /
       ``manifest.json`` under ``run_dir/artifact/`` (spec §5.10).

    Args:
        config: Validated run configuration.
        llm: Optional LLM client used for the single manual-merge call
            (spec §5.10 step 3). When ``None``, the configured runtime
            is wrapped via :func:`build_runtime_llm`; runtimes that do
            not implement :class:`harness.runtimes.LLMCompleter`
            (e.g. :class:`harness.runtimes.replay.ReplayRuntime`) make
            that wrapping raise :class:`SynthesisError`. Replay tests
            and other completer-less callers must inject an explicit
            stub here.

    Returns:
        An :class:`ExploreResult` with the harness ``final_status`` and
        the published artifact paths anchored under
        ``run_dir/artifact/``.

    Raises:
        ShopUnreachableError: If the prefetch step aborts (bot-block,
            robots.txt deny, network error on ``/`` or ``robots.txt``).
        SynthesisError: If the harness loop returned without populating
            ``run_dir/artifact/parts/`` or ``run_dir/artifact/prefetch/``;
            if the merged capabilities fragments fail schema validation;
            if the runtime does not implement
            :class:`harness.runtimes.LLMCompleter` and no ``llm`` was
            supplied; or if the manual-merge LLM call fails / returns
            an unusable response.
    """
    run_dir = config.out_dir if config.out_dir is not None else _default_run_dir(config)
    _log.info("run_dir=%s", run_dir)
    _log.info("tail %s/iters/*/native.log for progress", run_dir)

    agents_md = _render_agents_md(
        (_PROMPTS_DIR / "agents.md").read_text(encoding="utf-8"),
    )
    planner_prompt = (_PROMPTS_DIR / "planner.md").read_text(encoding="utf-8")
    execute_prompt = (_PROMPTS_DIR / "execute.md").read_text(encoding="utf-8")
    manual_prompt = (_PROMPTS_DIR / "synthesize_manual.md").read_text(encoding="utf-8")

    seed_root = Path(tempfile.mkdtemp(prefix="shop-explore-seed-"))
    try:
        seed_dir = seed_root / "artifact_seed"
        seed_dir.mkdir()
        _log.info("prefetching from %s", config.url)
        prefetch_result = run_prefetch(config.url, dest_dir=seed_dir / "prefetch")
        _log.info("prefetched %d entries", len(prefetch_result.entries))

        loop_config = PlanExecLoopConfig(
            run_dir=run_dir,
            prompts=Prompts(planner=planner_prompt, execute=execute_prompt),
            agents_md=agents_md,
            artifact_seed_dir=seed_dir,
            max_iters=config.max_iters,
            timeout=config.timeout,
        )
        runtime = get_runtime(config.runtime)
        _log.info(
            "starting plan/exec loop (runtime=%s, max_iters=%d, timeout=%.0fs)",
            config.runtime,
            config.max_iters,
            config.timeout,
        )
        loop_result = run_plan_exec_loop(loop_config, runtime, force=config.force_resume)
        _log.info(
            "plan/exec loop done: final_status=%s, plan_iters=%d, exec_iters=%d",
            loop_result.final_status.value,
            loop_result.plan_iter_count,
            loop_result.exec_iter_count,
        )
    finally:
        shutil.rmtree(seed_root, ignore_errors=True)

    _log.info("synthesizing manual")
    synthesis = synthesize(
        run_dir,
        llm=llm if llm is not None else build_runtime_llm(runtime, timeout=config.timeout),
        manual_prompt=manual_prompt,
    )
    _log.info(
        "synthesis done: capability_conflicts=%d",
        len(synthesis.capability_conflicts),
    )

    artifact_dir = run_dir / "artifact"
    return ExploreResult(
        run_dir=run_dir,
        manual_path=artifact_dir / "manual.md",
        capabilities_path=artifact_dir / "capabilities.json",
        stats_path=artifact_dir / "stats.json",
        manifest_path=artifact_dir / "manifest.json",
        prefetch_dir=artifact_dir / "prefetch",
        final_status=loop_result.final_status,
    )


def build_runtime_llm(runtime: AgentRuntime, *, timeout: float) -> LLMClient:
    """Return an :class:`LLMClient` backed by ``runtime``.

    Inspects ``runtime`` for the :class:`harness.runtimes.LLMCompleter`
    Protocol. When supported, returns a :class:`_RuntimeLLMClient` that
    delegates the synthesis manual-merge call (spec §5.10) through the
    same runtime that drives the harness loop — so the synthesis call
    hits the same underlying model (§8.2 open question 1 resolved in
    favour of "reuse harness runtime LLM").

    Runtimes that cannot serve completions (e.g.
    :class:`harness.runtimes.replay.ReplayRuntime`) raise
    :class:`SynthesisError` here. Earlier revisions silently fell back
    to a no-op client that returned ``""`` and triggered a deterministic
    concatenation; that path masked LLM-client misconfiguration and was
    removed deliberately. Callers driving such runtimes (e.g. the replay
    test suite) must inject an explicit ``llm`` argument to
    :func:`explore`.

    Args:
        runtime: The harness runtime instance returned by
            :func:`harness.get_runtime`.
        timeout: Wall-clock budget forwarded to ``runtime.complete``.
            Reuses ``ExploreConfig.timeout`` so the synthesis call is
            bounded by the same per-iteration budget.

    Returns:
        An :class:`LLMClient` ready to pass to
        :func:`shop_explore.synthesize.synthesize`.

    Raises:
        SynthesisError: When ``runtime`` does not satisfy
            :class:`harness.runtimes.LLMCompleter`.
    """
    if isinstance(runtime, LLMCompleter):
        return _RuntimeLLMClient(runtime, timeout=timeout)
    raise SynthesisError(
        f"runtime {type(runtime).__name__} does not implement LLMCompleter; "
        "pass an explicit llm= to explore() (or switch to a runtime that does)"
    )


class _RuntimeLLMClient:
    """:class:`LLMClient` that delegates each call to a harness runtime.

    The runtime must satisfy :class:`harness.runtimes.LLMCompleter`; the
    iteration ``timeout`` is captured at construction time so the
    :class:`LLMClient` Protocol's single-argument ``complete`` shape is
    preserved at the synthesis call site. Any exception raised by the
    runtime propagates unchanged so :func:`synthesize` can surface it as
    a :class:`SynthesisError` and abort the run — there is no silent
    fallback.
    """

    def __init__(self, runtime: LLMCompleter, *, timeout: float) -> None:
        """Capture the runtime instance and the per-call timeout."""
        self._runtime = runtime
        self._timeout = timeout

    def complete(self, prompt: str) -> str:
        """Delegate to ``runtime.complete(prompt, timeout=...)``."""
        return self._runtime.complete(prompt, timeout=self._timeout)


def _render_agents_md(template: str) -> str:
    """Substitute ``{{PLAYWRIGHT_SKILL_DIR}}`` and ``{{CAPABILITIES_SCHEMA}}``.

    Both placeholders are rendered into the bundled ``agents.md`` template
    once per run so executor iterations don't need to discover them on
    their own (each discovery costs 4-5 bash calls per iteration on the
    Claude Code runtime). The skill path is resolved against the active
    JS package-manager global root; the capabilities schema is read from
    ``shop_explore.capabilities.schema`` so it can never drift from the
    pydantic model.

    Args:
        template: Raw contents of ``prompts/agents.md``.

    Returns:
        The template with both placeholders substituted. When the
        playwright skill cannot be located on this machine, the
        placeholder is replaced with a literal ``"<unresolved>"`` and a
        warning is logged — the agent will still try to run but will
        fail loudly the first time it touches ``$SKILL_DIR``, which is
        what we want for environments where browsing is not expected
        (e.g. ``replay`` runtime tests).
    """
    skill_dir = _resolve_playwright_skill_dir()
    if skill_dir is None:
        _log.warning(
            "could not resolve pi-playwright skill dir; "
            "rendering agents.md with placeholder '<unresolved>'",
        )
        skill_value = "<unresolved>"
    else:
        skill_value = str(skill_dir)
    schema_source = _CAPABILITIES_SCHEMA_PATH.read_text(encoding="utf-8")
    return template.replace("{{PLAYWRIGHT_SKILL_DIR}}", skill_value).replace(
        "{{CAPABILITIES_SCHEMA}}",
        schema_source.rstrip("\n"),
    )


def _resolve_playwright_skill_dir() -> Path | None:
    """Locate the ``pi-playwright`` browser skill on this machine.

    Tries ``pnpm root -g`` first (the project standard), then falls back
    to ``npm root -g``. Returns the absolute path to the skill directory
    when ``SKILL.md`` is present, or ``None`` when neither command
    succeeds or the skill is not installed globally.
    """
    for cmd in (("pnpm", "root", "-g"), ("npm", "root", "-g")):
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            continue
        root = proc.stdout.strip()
        if not root:
            continue
        candidate = Path(root) / _PLAYWRIGHT_SKILL_RELPATH
        if (candidate / "SKILL.md").is_file():
            return candidate
    return None


def _default_run_dir(config: ExploreConfig) -> Path:
    """Compute ``outputs/shop_manuals/<domain>/<run_id>/`` for ``config``."""
    domain = urlsplit(config.url).hostname or "unknown"
    return _DEFAULT_OUTPUT_ROOT / domain / _derive_run_id(config)


def _derive_run_id(config: ExploreConfig) -> str:
    """Return ``<UTC-timestamp>-<short-hash>`` per spec §5.4.

    The hash is the leading hex digits of ``SHA-256(url|runtime|version)``
    so that parallel runs of the same shop with different runtimes (or
    package versions) get distinct workspace paths even when started in
    the same second.
    """
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = f"{config.url}|{config.runtime}|{__version__}".encode()
    short = hashlib.sha256(payload).hexdigest()[:RUN_ID_HASH_LEN]
    return f"{timestamp}-{short}"
