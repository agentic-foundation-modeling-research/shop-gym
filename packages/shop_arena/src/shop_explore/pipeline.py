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

The synthesis step requires an LLM client. Callers that do not pass
one (the CLI today, replay tests) get a deterministic no-op client
that returns an empty completion; :func:`shop_explore.synthesize.synthesize`
then falls back to concatenating ``parts/*.md`` and flags
``manifest.manual_fallback=true``. Production callers wire a real
:class:`~shop_explore.synthesize.LLMClient` through the ``llm`` keyword.

The module is import-safe — no I/O at import time. Prompt resources are
read from disk only when :func:`explore` is invoked.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from harness import PlanExecLoopConfig, Prompts, get_runtime, run_plan_exec_loop
from shop_explore import __version__
from shop_explore.config import ExploreConfig, ExploreResult
from shop_explore.prefetch import run as run_prefetch
from shop_explore.synthesize import LLMClient, synthesize

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
"""Directory holding the bundled ``agents.md`` / ``planner.md`` / ``execute.md`` resources."""

_DEFAULT_OUTPUT_ROOT = Path("outputs") / "shop_manuals"
"""Default parent of ``<domain>/<run_id>/`` when ``ExploreConfig.out_dir`` is omitted."""

_RUN_ID_HASH_LEN = 8
"""Length of the SHA-256 prefix appended to the timestamp in a ``run_id`` (spec §5.4)."""


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
            (spec §5.10 step 3). When ``None``, a no-op client is used
            and synthesis falls back to deterministic concatenation of
            ``parts/*.md`` (``manifest.manual_fallback=true``).

    Returns:
        An :class:`ExploreResult` with the harness ``final_status`` and
        the published artifact paths anchored under
        ``run_dir/artifact/``.

    Raises:
        ShopUnreachableError: If the prefetch step aborts (bot-block,
            robots.txt deny, network error on ``/`` or ``robots.txt``).
        SynthesisError: If the harness loop returned without populating
            ``run_dir/artifact/parts/`` or ``run_dir/artifact/prefetch/``,
            or if the merged capabilities fragments fail schema
            validation.
    """
    run_dir = config.out_dir if config.out_dir is not None else _default_run_dir(config)

    agents_md = (_PROMPTS_DIR / "agents.md").read_text(encoding="utf-8")
    planner_prompt = (_PROMPTS_DIR / "planner.md").read_text(encoding="utf-8")
    execute_prompt = (_PROMPTS_DIR / "execute.md").read_text(encoding="utf-8")
    manual_prompt = (_PROMPTS_DIR / "synthesize_manual.md").read_text(encoding="utf-8")

    seed_root = Path(tempfile.mkdtemp(prefix="shop-explore-seed-"))
    try:
        seed_dir = seed_root / "artifact_seed"
        seed_dir.mkdir()
        run_prefetch(config.url, dest_dir=seed_dir / "prefetch")

        loop_config = PlanExecLoopConfig(
            run_dir=run_dir,
            prompts=Prompts(planner=planner_prompt, execute=execute_prompt),
            agents_md=agents_md,
            artifact_seed_dir=seed_dir,
            max_iters=config.max_iters,
            timeout=config.timeout,
        )
        runtime = get_runtime(config.runtime)
        loop_result = run_plan_exec_loop(loop_config, runtime)
    finally:
        shutil.rmtree(seed_root, ignore_errors=True)

    synthesize(
        run_dir,
        llm=llm if llm is not None else _NoOpLLMClient(),
        manual_prompt=manual_prompt,
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


class _NoOpLLMClient:
    """LLM client that always returns the empty string.

    Used by :func:`explore` when the caller does not supply an LLM
    client. Triggers the spec §5.10 fallback path inside
    :func:`shop_explore.synthesize.synthesize`: the manual is rendered
    as the deterministic concatenation of ``parts/*.md`` and
    ``manifest.manual_fallback`` is set to ``True``. This keeps the
    pipeline runnable without any LLM credentials (e.g. in CI replay
    tests) until a real client is wired in a later milestone.
    """

    def complete(self, prompt: str) -> str:
        """Return ``""`` to force the synthesis fallback path."""
        return ""


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
    short = hashlib.sha256(payload).hexdigest()[:_RUN_ID_HASH_LEN]
    return f"{timestamp}-{short}"
