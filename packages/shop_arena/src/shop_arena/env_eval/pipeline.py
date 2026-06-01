"""``evaluate()`` orchestrator across discovery, transition, observation, action.

The orchestrator resolves a run directory, discovers the canonical sample
pages, captures the transition graph and per-node browser states, then computes
observation and action metrics from those captured graph nodes. URL nodes use
their captured screenshot/axtree files; state nodes use ``post.*`` artifacts.
"""

from __future__ import annotations

import functools
import io
import json
import logging
import shutil
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import numpy as np
from PIL import Image

from shop_arena.env_eval import _version
from shop_arena.env_eval import action as action_mod
from shop_arena.env_eval import pages as pages_mod
from shop_arena.env_eval import resume as resume_mod
from shop_arena.env_eval.config import EvalConfig, EvalResult
from shop_arena.env_eval.env import EnvEvalSession, make_env
from shop_arena.env_eval.observation.axtree_stats import compute_axtree_stats
from shop_arena.env_eval.observation.axtree_text import render_axtree_text
from shop_arena.env_eval.observation.rubric import (
    RUBRIC_PROMPT_VERSION,
    RubricArtifact,
    run_rubric,
    write_rubric_artifact,
)
from shop_arena.env_eval.schema import manifest as manifest_mod
from shop_arena.env_eval.schema import metrics as metrics_mod
from shop_arena.env_eval.transition import bfs as bfs_mod
from shop_arena.env_eval.transition import node_artifacts as node_artifacts_mod
from shop_arena.env_eval.transition import pages_classifier as pages_classifier_mod
from shop_arena.env_eval.transition.canonicalize import canonical_id_for_url
from shop_arena.env_eval.transition.graph import (
    GraphNode,
    TransitionGraph,
    write_graph_json,
)
from shop_arena.env_eval.transition.rules import RULES
from shop_arena.env_eval.transition.stateful import (
    DEFAULT_AXTREE_MIN_WAIT_HOMEPAGE_MS,
    run_stateful_pass,
    wait_for_axtree_settle,
    write_stateful_trace_lines,
)
from shop_arena.util._llm import LLMVisionClient, build_default_client

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_OUTPUT_ROOT",
    "RUN_ID_TIMESTAMP_FORMAT",
    "evaluate",
    "resolve_run_dir",
]

#: Parent directory for default-resolved run dirs (spec §5.6 / impl-plan M1).
#: Relative to the caller's CWD by default; tests inject ``base_dir`` to
#: keep filesystem assertions hermetic.
DEFAULT_OUTPUT_ROOT: Path = Path("outputs/shop_env_evals")

#: ``strftime`` format for the timestamped ``<run_id>`` segment. UTC, second
#: precision, filesystem-safe (no colons). Matches the impl-plan M1
#: "timestamped <run_id>" decision and is reused by manifest writers.
RUN_ID_TIMESTAMP_FORMAT: str = "%Y%m%dT%H%M%SZ"

_NODE_LAYER_INDEX_FILENAME: str = "index.json"
_NODE_LAYER_ARTIFACT_VERSION: str = "0.1"


@dataclass(frozen=True, slots=True)
class _TransitionNodeSource:
    """Filesystem source files backing one transition graph node."""

    canonical_id: str
    folder: str
    kind: metrics_mod.NodeKind
    representative_url: str
    state_name: str | None
    screenshot_path: Path | None
    axtree_json_path: Path | None
    axtree_text_path: Path | None
    #: Pre-action screenshot for state nodes (``None`` for URL nodes).  When
    #: set, the rubric step receives both the pre and post images and skips
    #: the axtree dump (rubric prompt v0.3); URL nodes keep the single-image
    #: + axtree shape from v0.2.
    pre_screenshot_path: Path | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _ObservationNodeMeasurement:
    """Observation entry plus raw axtree for website-level aggregation."""

    entry: metrics_mod.ObservationNodeOk | metrics_mod.NodeNotFound
    axtree: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class _ActionNodeMeasurement:
    """Action entry for one transition graph node."""

    entry: metrics_mod.ActionNodeOk | metrics_mod.NodeNotFound


def resolve_run_dir(
    config: EvalConfig,
    *,
    now: datetime | None = None,
    base_dir: Path | None = None,
) -> Path:
    """Return the run directory for an ``evaluate()`` call.

    Resolution rules (spec §5.6, impl-plan M1):

    * ``config.out_dir`` set → returned verbatim. An existing directory
      is the spec's resume signal; the caller does not need to opt in.
    * Otherwise → ``<base_dir>/<shop_name>/<run_id>/`` where
      ``<shop_name>`` is ``config.shop_name`` if provided, else the
      URL hostname (lowercased), and ``<run_id>`` is a UTC timestamp
      formatted via :data:`RUN_ID_TIMESTAMP_FORMAT`.

    Args:
        config: User-facing eval configuration. Only ``url``, ``out_dir``,
            and ``shop_name`` are read.
        now: UTC timestamp source for ``<run_id>``. Defaults to
            :func:`datetime.now` with :data:`datetime.UTC`. Tests inject a
            fixed value for byte-stable assertions.
        base_dir: Override for :data:`DEFAULT_OUTPUT_ROOT`. Tests pass a
            ``tmp_path`` so resolution stays inside the sandbox.

    Returns:
        The resolved run directory. The path is **not** created here;
        the pipeline (M1) creates it lazily on first artifact write.

    Raises:
        ValueError: ``config.out_dir`` is unset and a shop name cannot be
            derived (no override and the URL has no hostname).
    """
    if config.out_dir is not None:
        return config.out_dir

    shop_name = config.shop_name or _hostname_from_url(config.url)
    if not shop_name:
        raise ValueError(
            f"cannot derive <shop_name> from url={config.url!r}; pass "
            "shop_name on EvalConfig or use --shop-name on the CLI",
        )

    timestamp = (now or datetime.now(UTC)).strftime(RUN_ID_TIMESTAMP_FORMAT)
    root = base_dir if base_dir is not None else DEFAULT_OUTPUT_ROOT
    return root / shop_name / timestamp


def _hostname_from_url(url: str) -> str:
    """Return the lowercased hostname of ``url`` (empty if absent).

    ``urllib.parse.urlsplit`` returns ``None`` for the hostname when the
    URL has no scheme (e.g. ``"example.com"``); that is surfaced as the
    empty string so the caller can decide whether to raise.
    """
    return (urlsplit(url).hostname or "").lower()


def _build_rubric_client(config: EvalConfig) -> LLMVisionClient:
    """Build the vision client for the rubric (impl-plan M2).

    Module-level seam so unit tests can ``monkeypatch`` it with a fake
    :class:`~shop_arena.util._llm.LLMVisionClient` without dispatching
    against a real provider SDK.  Production callers route through
    :func:`shop_arena.util._llm.build_default_client`, which infers the
    provider from ``config.rubric_model``'s prefix.
    """
    return build_default_client(config.rubric_model)


def _build_pages_classifier_client(config: EvalConfig) -> LLMVisionClient:
    """Build the vision client for the ``/pages/<slug>`` classifier.

    Mirrors :func:`_build_rubric_client` but routes on
    ``config.pages_classifier_model``. Lives as a module-level seam so
    tests can ``monkeypatch`` it independently of the rubric client and
    inject a fake whose ``call_text`` returns a deterministic fixture.
    """
    return build_default_client(config.pages_classifier_model)


def _has_downstream_artifacts(run_dir: Path) -> bool:
    """Return ``True`` when any post-``pages.json`` artifact exists under ``run_dir``.

    Used to detect stale state at ``--rediscover`` time (spec §5.7 / impl-plan
    M6): EnvEval invalidates ``pages.json`` only, so downstream artifacts left
    over from a prior run survive the rediscovery.  Returns ``True`` when any
    file exists under ``observation/``, ``action/``, or ``transition/``, or
    when ``metrics.json`` is on disk — i.e. anything the orchestrator might
    otherwise reuse and that the new page selection could invalidate.
    """
    if (run_dir / "metrics.json").is_file():
        return True
    for sub in ("observation", "action", "transition"):
        sub_dir = run_dir / sub
        if not sub_dir.is_dir():
            continue
        for entry in sub_dir.rglob("*"):
            if entry.is_file():
                return True
    return False


def _cleanup_legacy_transition_states(run_dir: Path) -> None:
    """Remove pre-node-layout ``transition/states`` artifacts if present."""
    legacy_states_dir = run_dir / "transition" / "states"
    if legacy_states_dir.exists():
        shutil.rmtree(legacy_states_dir)


def _reset_node_layer_dir(layer_dir: Path) -> None:
    """Delete and recreate a node-derived observation/action directory."""
    if layer_dir.exists():
        shutil.rmtree(layer_dir)
    layer_dir.mkdir(parents=True, exist_ok=True)


def evaluate(config: EvalConfig) -> EvalResult:
    """Evaluate a single shop URL end-to-end (spec §5.1, impl plan M1-M6).

    Drives page selection (:mod:`shop_arena.env_eval.pages`), transition graph
    capture, node-derived observation, and node-derived action measurement
    against a single long-lived BrowserGym env. Observation/action artifacts
    use transition-node folder stems (for example ``home.*``); state nodes use
    the stateful pass's ``post.*`` axtree and screenshot. ``manifest.json``
    records the config snapshot, ``browser_navigations``, ``llm_calls``, and
    a per-step ``(ran, reused)`` table (impl-plan M6).

    M6 reuse wiring (spec §5.7): before any browser activity, EnvEval inspects
    the run directory.  When *every* step's required artifacts are already on
    disk (and ``--rediscover`` was not passed), the call short-circuits
    entirely — no BrowserGym env is opened and no LLM call is issued.  In the
    partial-reuse path, each step's ``(ran, reused)`` marker is predicted from
    :func:`shop_arena.env_eval.resume.can_skip` *before* the step runs; the
    step itself uses its own per-node cache logic to honour the prediction.

    Args:
        config: User-facing configuration. Used to resolve the run
            directory and drive the discovery / observation layers.

    Returns:
        :class:`~shop_arena.env_eval.config.EvalResult` pointing at the
        run directory and ``metrics.json``.

    Raises:
        ShopUnreachableError: Homepage navigation failed (spec §5.2 step 1).
    """
    started_at = datetime.now(UTC)
    base_url = pages_mod.normalize_base_url(config.url)
    run_dir = resolve_run_dir(config)
    run_dir.mkdir(parents=True, exist_ok=True)
    obs_dir = run_dir / "observation"
    obs_dir.mkdir(parents=True, exist_ok=True)
    action_dir = run_dir / "action"
    action_dir.mkdir(parents=True, exist_ok=True)
    transition_dir = run_dir / "transition"
    transition_dir.mkdir(parents=True, exist_ok=True)

    # ``--rediscover`` invalidates ``pages.json`` only (spec §5.7 / impl-plan
    # M6).  EnvEval does not cascade-delete downstream artifacts; if any are
    # present the caller has likely set up a stale run dir, so warn loudly so
    # the staleness is at least visible in logs.  Callers who want a clean
    # slate should point ``--out`` at a fresh directory.
    if config.rediscover and _has_downstream_artifacts(run_dir):
        logger.warning(
            "--rediscover invalidates pages.json only; downstream artifacts "
            "under %s (observation/, action/, transition/, metrics.json) are "
            "NOT deleted and may be stale relative to the new page selection. "
            "Use a fresh --out directory if you need a clean re-run.",
            run_dir,
        )

    # Pre-flight: short-circuit the entire run when every step's required
    # artifacts already exist on disk (spec §5.7).  ``pages.json`` is the
    # entry point — without it the rest of the artifact map cannot be
    # enumerated.  ``--rediscover`` always forces at least the pages step
    # to re-run, so the full short-circuit cannot fire under that flag.
    pre_pages_expected = resume_mod.expected_artifacts(
        run_dir,
        None,
        no_rubric=config.no_rubric,
    )
    pages_already_on_disk = not config.rediscover and resume_mod.can_skip(
        "pages",
        pre_pages_expected,
    )
    if pages_already_on_disk:
        cached_pages_doc = pages_mod.read_pages_json(run_dir)
        full_expected = resume_mod.expected_artifacts(
            run_dir,
            cached_pages_doc,
            no_rubric=config.no_rubric,
        )
        if all(resume_mod.can_skip(step, full_expected) for step in resume_mod.STEPS):
            _cleanup_legacy_transition_states(run_dir)
            steps = tuple(
                manifest_mod.StepRecord(name=step, ran=False, reused=True)
                for step in resume_mod.STEPS
            )
            manifest_mod.write_manifest(
                manifest_mod.build_manifest(
                    config,
                    eval_version=_version.__version__,
                    browser_navigations=0,
                    llm_calls=0,
                    steps=steps,
                    started_at=started_at,
                    ended_at=datetime.now(UTC),
                ),
                run_dir,
            )
            return EvalResult(
                run_dir=run_dir,
                metrics_path=run_dir / "metrics.json",
            )

    # Partial reuse or first run: open the browser and drive the pipeline.
    # Transition runs before observation/action now because the latter are
    # measured from ``transition/node/*`` artifacts (URL nodes use
    # ``screenshot.*``/``axtree.*``; state nodes use ``post.*``).
    step_reused: dict[resume_mod.Step, bool] = {"pages": pages_already_on_disk}
    rubric_client = _build_rubric_client(config) if not config.no_rubric else None
    pages_classifier_client = (
        _build_pages_classifier_client(config) if not config.no_rubric else None
    )
    with make_env(base_url, viewport=config.viewport) as session:
        pages_doc = pages_mod.load_or_discover(
            session,
            base_url,
            run_dir,
            rediscover=config.rediscover,
        )
        expected = resume_mod.expected_artifacts(
            run_dir,
            pages_doc,
            no_rubric=config.no_rubric,
        )
        step_reused["transition"] = resume_mod.can_skip("transition", expected)
        transition_block, transition_llm_calls, graph = _capture_transition(
            session,
            base_url,
            pages_doc,
            transition_dir,
            run_dir=run_dir,
            max_hops=config.max_hops,
            llm_client=rubric_client,
            pages_classifier_client=pages_classifier_client,
            pages_classifier_model=config.pages_classifier_model,
        )
        if not step_reused["transition"]:
            _reset_node_layer_dir(obs_dir)
            _reset_node_layer_dir(action_dir)

        expected = resume_mod.expected_artifacts(
            run_dir,
            pages_doc,
            no_rubric=config.no_rubric,
        )
        step_reused["observation"] = resume_mod.can_skip("observation", expected)
        observation, observation_llm_calls = _capture_observation_from_transition_nodes(
            graph,
            node_root=transition_dir / node_artifacts_mod.NODE_DIRNAME,
            obs_dir=obs_dir,
            base_url=base_url,
            pages_doc=pages_doc,
            no_rubric=config.no_rubric,
            rubric_client=rubric_client,
        )

        expected = resume_mod.expected_artifacts(
            run_dir,
            pages_doc,
            no_rubric=config.no_rubric,
        )
        step_reused["action"] = resume_mod.can_skip("action", expected)
        action_block = _capture_action_from_transition_nodes(
            graph,
            node_root=transition_dir / node_artifacts_mod.NODE_DIRNAME,
            action_dir=action_dir,
        )
        llm_calls = transition_llm_calls + observation_llm_calls
        # ``EnvEvalBrowserTask.setup`` does the homepage navigation before
        # yielding the session, so add 1 to the session's own ``goto`` tally.
        browser_navigations = session.nav_count + 1

    metrics = metrics_mod.Metrics(
        shop=_build_shop(pages_doc),
        pages=_pages_for_metrics(pages_doc),
        observation=observation,
        action=action_block,
        transition=transition_block,
    )
    # ``metrics.json`` is rewritten whenever the partial-reuse path is taken:
    # at least one upstream step ran live (otherwise the full-reuse short-
    # circuit above would have fired) so any cached ``metrics.json`` is stale.
    metrics_path = metrics_mod.dump_metrics(metrics, run_dir / "metrics.json")
    step_reused["metrics"] = False
    steps = tuple(
        manifest_mod.StepRecord(
            name=step,
            ran=not step_reused[step],
            reused=step_reused[step],
        )
        for step in resume_mod.STEPS
    )
    manifest_mod.write_manifest(
        manifest_mod.build_manifest(
            config,
            eval_version=_version.__version__,
            browser_navigations=browser_navigations,
            llm_calls=llm_calls,
            steps=steps,
            started_at=started_at,
            ended_at=datetime.now(UTC),
        ),
        run_dir,
    )
    return EvalResult(run_dir=run_dir, metrics_path=metrics_path)


# ---------------------------------------------------------------------------
# Rubric, URL, screenshot, and JSON helpers shared by node measurements.
# ---------------------------------------------------------------------------


def _resolve_rubric(
    rubric_path: Path,
    images: Sequence[bytes],
    *,
    axtree_text: str,
    no_rubric: bool,
    rubric_client: LLMVisionClient | None,
) -> tuple[metrics_mod.Rubric, int]:
    """Resolve the rubric counts + LLM-call count for one node.

    Three branches (spec §5.3 / impl-plan M2):

    * ``no_rubric=True`` → write the closed stub payload, return zero counts.
    * Existing non-stub ``*.rubric.json`` → load + reuse, no LLM call (spec §5.7).
    * Otherwise → call the rubric with ``images`` (and ``axtree_text`` for
      URL nodes; empty for state nodes that pass pre+post screenshots),
      persist the artifact, return its counts.
    """
    if no_rubric:
        _write_rubric_stub(rubric_path)
        return metrics_mod.Rubric(), 0
    if rubric_client is None:
        raise RuntimeError(
            "rubric_client is required when no_rubric=False; "
            "this is an internal pipeline invariant",
        )
    existing = _load_existing_rubric_artifact(rubric_path)
    if existing is not None:
        return existing.counts, 0
    artifact = run_rubric(rubric_client, images, axtree_text=axtree_text)
    write_rubric_artifact(artifact, rubric_path)
    return artifact.counts, 1


def _load_existing_rubric_artifact(path: Path) -> RubricArtifact | None:
    """Return the persisted rubric artifact at ``path``, or ``None`` to re-run.

    Stub artifacts (``{counts: {}, stub: true}``) and missing files both
    return ``None`` so the rubric is (re-)issued.  Real artifacts are
    validated against the closed :class:`RubricArtifact` schema; an
    unparseable file fails loudly rather than being silently overwritten.
    Artifacts whose ``prompt_version`` does not match the current
    :data:`RUBRIC_PROMPT_VERSION` are also treated as stale — the rubric
    contract (prompt body, input shape, schema) changed in a way that makes
    the cached counts incomparable, so we re-issue the call.
    """
    if not path.is_file():
        return None
    payload = cast("object", json.loads(path.read_text(encoding="utf-8")))
    if isinstance(payload, dict) and cast("dict[str, Any]", payload).get("stub") is True:
        return None
    artifact = RubricArtifact.model_validate(payload)
    if artifact.prompt_version != RUBRIC_PROMPT_VERSION:
        return None
    return artifact


def _reusable_rubric_counts(
    path: Path,
    *,
    no_rubric: bool,
) -> metrics_mod.Rubric | None:
    """Return the rubric counts to reuse for ``path``, or ``None`` to re-run.

    Stub artifacts (``{counts: {}, stub: true}``) only count as reusable when
    ``no_rubric`` is ``True``; otherwise the rubric step still owes us real
    counts and the node must rerun.  Artifacts whose ``prompt_version`` no
    longer matches :data:`RUBRIC_PROMPT_VERSION` are also rejected so a
    contract change invalidates the cache without requiring an explicit
    purge.  The file is assumed to exist; the per-node reuse caller checks
    :meth:`pathlib.Path.is_file` first.
    """
    payload = cast("object", json.loads(path.read_text(encoding="utf-8")))
    if isinstance(payload, dict) and cast("dict[str, Any]", payload).get("stub") is True:
        return metrics_mod.Rubric() if no_rubric else None
    artifact = RubricArtifact.model_validate(payload)
    if artifact.prompt_version != RUBRIC_PROMPT_VERSION:
        return None
    return artifact.counts


def _join_url(base_url: str, url: str) -> str:
    """Resolve ``url`` against ``base_url`` for absolute navigation."""
    if url.startswith(("http://", "https://")):
        return url
    base = base_url.rstrip("/")
    if not url.startswith("/"):
        return f"{base}/{url}"
    return f"{base}{url}"


def _encode_screenshot(screenshot: Any) -> bytes:
    """Encode an ``(H, W, 3)`` screenshot ndarray as PNG bytes."""
    arr = np.asarray(screenshot)
    if arr.dtype != np.uint8:
        arr = arr.astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def _write_axtree_json(path: Path, axtree: dict[str, Any]) -> None:
    """Write ``axtree`` as deterministic JSON (two-space indent, trailing newline)."""
    path.write_text(json.dumps(axtree, indent=2, default=_json_default) + "\n", encoding="utf-8")


def _write_axtree_text(path: Path, axtree_text: str) -> None:
    """Write the deterministic text-tree debug artifact (with trailing newline)."""
    path.write_text(axtree_text + "\n" if axtree_text else "", encoding="utf-8")


#: Body of the M1 stub rubric artifact written under ``--no-rubric``
#: (spec §5.3 / impl-plan M1). The closed observation rubric (M2) replaces
#: this with parsed LLM counts; the stub keeps the artifact set complete so
#: resume detection (M6, spec §5.7) recognises observation as done.
_RUBRIC_STUB_PAYLOAD: dict[str, Any] = {"counts": {}, "stub": True}


def _write_rubric_stub(path: Path) -> None:
    """Write the ``--no-rubric`` stub artifact to ``path``."""
    path.write_text(
        json.dumps(_RUBRIC_STUB_PAYLOAD, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _json_default(value: object) -> object:
    """Best-effort JSON encoder for axtree payloads with numpy / set values."""
    if isinstance(value, (set, frozenset)):
        return sorted(cast("set[Any] | frozenset[Any]", value))
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return cast("Any", tolist)()
    raise TypeError(f"axtree contains non-JSON value of type {type(value).__name__}")


# ---------------------------------------------------------------------------
############################ Node-driven observation/action ###################
# ---------------------------------------------------------------------------


def _capture_observation_from_transition_nodes(
    graph: TransitionGraph,
    *,
    node_root: Path,
    obs_dir: Path,
    base_url: str,
    pages_doc: pages_mod.PagesDoc,
    no_rubric: bool,
    rubric_client: LLMVisionClient | None,
) -> tuple[metrics_mod.Observation, int]:
    """Build observation metrics from transition graph node artifacts.

    URL graph nodes read ``transition/node/<folder>/screenshot.png`` and
    ``axtree.*``. Stateful graph nodes read the post-action state:
    ``post.png``, ``post.axtree.json``, and ``post.axtree.txt``. The copied
    per-node observation artifacts are written under ``observation/<folder>.*``.
    """
    obs_dir.mkdir(parents=True, exist_ok=True)
    total_llm_calls = 0
    measurements: list[_ObservationNodeMeasurement] = []
    for graph_node in graph.nodes.values():
        source = _transition_node_source(graph_node, node_root)
        measured_node = _measured_node(source)
        measurement, llm_calls = _measure_observation_node(
            source,
            measured_node,
            obs_dir,
            no_rubric=no_rubric,
            rubric_client=rubric_client,
        )
        measurements.append(measurement)
        total_llm_calls += llm_calls
    _write_node_layer_index(
        obs_dir,
        [_observation_index_entry(measurement.entry) for measurement in measurements],
    )
    return _observation_from_node_measurements(measurements), total_llm_calls


def _measure_observation_node(
    source: _TransitionNodeSource,
    measured_node: metrics_mod.MeasuredNode,
    obs_dir: Path,
    *,
    no_rubric: bool,
    rubric_client: LLMVisionClient | None,
) -> tuple[_ObservationNodeMeasurement, int]:
    """Resolve one node's observation artifact and metrics entry."""
    if source.error is not None:
        return (
            _ObservationNodeMeasurement(
                entry=metrics_mod.NodeNotFound(node=measured_node, reason=source.error),
                axtree=None,
            ),
            0,
        )

    png_path = obs_dir / f"{source.folder}.png"
    axtree_json_path = obs_dir / f"{source.folder}.axtree.json"
    axtree_txt_path = obs_dir / f"{source.folder}.axtree.txt"
    rubric_path = obs_dir / f"{source.folder}.rubric.json"

    if (
        png_path.is_file()
        and axtree_json_path.is_file()
        and axtree_txt_path.is_file()
        and rubric_path.is_file()
    ):
        rubric_counts = _reusable_rubric_counts(rubric_path, no_rubric=no_rubric)
        if rubric_counts is not None:
            axtree_cached = _read_json_object(axtree_json_path)
            entry = metrics_mod.ObservationNodeOk(
                node=measured_node,
                axtree=compute_axtree_stats(axtree_cached),
                rubric=rubric_counts,
            )
            return _ObservationNodeMeasurement(entry=entry, axtree=axtree_cached), 0

    if (
        source.screenshot_path is None
        or source.axtree_json_path is None
        or source.axtree_text_path is None
    ):
        return (
            _ObservationNodeMeasurement(
                entry=metrics_mod.NodeNotFound(
                    node=measured_node,
                    reason="node_capture_missing",
                ),
                axtree=None,
            ),
            0,
        )

    shutil.copyfile(source.screenshot_path, png_path)
    shutil.copyfile(source.axtree_json_path, axtree_json_path)
    shutil.copyfile(source.axtree_text_path, axtree_txt_path)

    png_bytes = png_path.read_bytes()
    axtree = _read_json_object(axtree_json_path)
    axtree_text = axtree_txt_path.read_text(encoding="utf-8")
    # State nodes pass pre+post screenshots (rubric prompt v0.3) so the model
    # can disambiguate transient overlays from the underlying chrome; the
    # post axtree is dropped because it duplicates the underlying URL node's
    # axtree and inflates input length.  URL nodes keep the v0.2 shape:
    # one screenshot plus the axtree text dump.
    if source.pre_screenshot_path is not None and source.pre_screenshot_path.is_file():
        rubric_images: tuple[bytes, ...] = (
            source.pre_screenshot_path.read_bytes(),
            png_bytes,
        )
        rubric_axtree_text = ""
    else:
        rubric_images = (png_bytes,)
        rubric_axtree_text = axtree_text
    rubric_counts, llm_calls = _resolve_rubric(
        rubric_path,
        rubric_images,
        axtree_text=rubric_axtree_text,
        no_rubric=no_rubric,
        rubric_client=rubric_client,
    )
    entry = metrics_mod.ObservationNodeOk(
        node=measured_node,
        axtree=compute_axtree_stats(axtree),
        rubric=rubric_counts,
    )
    return _ObservationNodeMeasurement(entry=entry, axtree=axtree), llm_calls


def _capture_action_from_transition_nodes(
    graph: TransitionGraph,
    *,
    node_root: Path,
    action_dir: Path,
) -> metrics_mod.Action:
    """Build action metrics from transition graph node axtrees."""
    action_dir.mkdir(parents=True, exist_ok=True)
    measurements: list[_ActionNodeMeasurement] = []
    for graph_node in graph.nodes.values():
        source = _transition_node_source(graph_node, node_root)
        measured_node = _measured_node(source)
        measurement = _measure_action_node(source, measured_node, action_dir)
        measurements.append(measurement)
    _write_node_layer_index(
        action_dir,
        [_action_index_entry(measurement.entry) for measurement in measurements],
    )
    return _action_from_node_measurements(measurements, graph)


def _measure_action_node(
    source: _TransitionNodeSource,
    measured_node: metrics_mod.MeasuredNode,
    action_dir: Path,
) -> _ActionNodeMeasurement:
    """Resolve one node's action artifact and metrics entry."""
    if source.error is not None:
        return _ActionNodeMeasurement(
            entry=metrics_mod.NodeNotFound(node=measured_node, reason=source.error),
        )
    if source.axtree_json_path is None:
        return _ActionNodeMeasurement(
            entry=metrics_mod.NodeNotFound(node=measured_node, reason="node_capture_missing"),
        )

    artifact_path = action_dir / f"{source.folder}.action_space.json"
    if artifact_path.is_file():
        payload = _read_json_object(artifact_path)
        if payload.get("heuristic_version") != action_mod.HEURISTIC_VERSION:
            axtree = _read_json_object(source.axtree_json_path)
            payload = action_mod.compute_action_space(axtree, None, None)
            artifact_path.write_text(
                json.dumps(payload, indent=2) + "\n",
                encoding="utf-8",
            )
    else:
        axtree = _read_json_object(source.axtree_json_path)
        payload = action_mod.compute_action_space(axtree, None, None)
        artifact_path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
    counts = _action_counts_from_payload(payload)
    entry = metrics_mod.ActionNodeOk(
        node=measured_node,
        click=counts.click,
        fill=counts.fill,
        hover=counts.hover,
        select_option=counts.select_option,
        scroll=counts.scroll,
        choice_target_count=counts.choice_target_count,
    )
    return _ActionNodeMeasurement(entry=entry)


def _transition_node_source(
    node: GraphNode,
    node_root: Path,
) -> _TransitionNodeSource:
    """Return the filesystem state files for ``node`` under ``transition/node``."""
    folder_name = node_artifacts_mod.node_folder_name(node.canonical_id)
    folder = node_root / folder_name
    node_json = folder / "node.json"
    kind = node.kind
    if not node_json.is_file():
        return _TransitionNodeSource(
            canonical_id=node.canonical_id,
            folder=folder_name,
            kind=kind,
            representative_url=node.representative_url,
            state_name=node.state_name,
            screenshot_path=None,
            axtree_json_path=None,
            axtree_text_path=None,
            error="node_json_missing",
        )
    if node.kind == "state":
        return _state_node_source(node, folder_name, folder, node_json)
    return _url_node_source(node, folder_name, folder, node_json)


def _url_node_source(
    node: GraphNode,
    folder_name: str,
    folder: Path,
    node_json: Path,
) -> _TransitionNodeSource:
    """Return source files for a URL node artifact."""
    kind = node.kind
    try:
        artifact = node_artifacts_mod.UrlNodeArtifact.model_validate_json(
            node_json.read_text(encoding="utf-8"),
        )
    except (OSError, ValueError) as exc:
        return _TransitionNodeSource(
            canonical_id=node.canonical_id,
            folder=folder_name,
            kind=kind,
            representative_url=node.representative_url,
            state_name=node.state_name,
            screenshot_path=None,
            axtree_json_path=None,
            axtree_text_path=None,
            error=f"node_json_invalid:{type(exc).__name__}",
        )
    screenshot = _node_file(folder, artifact.screenshot)
    axtree_json = _node_file(folder, artifact.axtree_json)
    axtree_text = _node_file(folder, artifact.axtree_text)
    error = artifact.error if artifact.capture_status != "ok" else None
    if error is None:
        error = _missing_source_file_reason(screenshot, axtree_json, axtree_text)
    return _TransitionNodeSource(
        canonical_id=node.canonical_id,
        folder=folder_name,
        kind=kind,
        representative_url=artifact.representative_url,
        state_name=node.state_name,
        screenshot_path=screenshot,
        axtree_json_path=axtree_json,
        axtree_text_path=axtree_text,
        error=error,
    )


def _state_node_source(
    node: GraphNode,
    folder_name: str,
    folder: Path,
    node_json: Path,
) -> _TransitionNodeSource:
    """Return pre- and post-action source files for a state node artifact.

    The post-action screenshot/axtree feed the published observation metrics
    (``screenshot_path`` / ``axtree_json_path`` / ``axtree_text_path``); the
    pre-action screenshot is exposed separately via ``pre_screenshot_path``
    so the rubric layer can opt into the v0.3 two-screenshot prompt for state
    nodes without disturbing the URL-node code path.
    """
    kind = node.kind
    try:
        artifact = node_artifacts_mod.StateNodeArtifact.model_validate_json(
            node_json.read_text(encoding="utf-8"),
        )
    except (OSError, ValueError) as exc:
        return _TransitionNodeSource(
            canonical_id=node.canonical_id,
            folder=folder_name,
            kind=kind,
            representative_url=node.representative_url,
            state_name=node.state_name,
            screenshot_path=None,
            axtree_json_path=None,
            axtree_text_path=None,
            error=f"node_json_invalid:{type(exc).__name__}",
        )
    screenshot = _node_file(folder, artifact.post_screenshot)
    axtree_json = _node_file(folder, artifact.post_axtree_json)
    axtree_text = _node_file(folder, artifact.post_axtree_text)
    pre_screenshot = _node_file(folder, artifact.pre_screenshot)
    return _TransitionNodeSource(
        canonical_id=node.canonical_id,
        folder=folder_name,
        kind=kind,
        representative_url=artifact.representative_url,
        state_name=artifact.state_name,
        screenshot_path=screenshot,
        axtree_json_path=axtree_json,
        axtree_text_path=axtree_text,
        pre_screenshot_path=pre_screenshot,
        error=_missing_source_file_reason(screenshot, axtree_json, axtree_text),
    )


def _node_file(folder: Path, filename: str | None) -> Path | None:
    """Return ``folder / filename`` when ``filename`` is present."""
    if filename is None:
        return None
    return folder / filename


def _missing_source_file_reason(*paths: Path | None) -> str | None:
    """Return a machine-readable reason if any source file is missing."""
    if any(path is None for path in paths):
        return "node_capture_missing"
    for path in paths:
        if path is None:
            return "node_capture_missing"
        if not path.is_file():
            return "node_capture_file_missing"
    return None


def _measured_node(source: _TransitionNodeSource) -> metrics_mod.MeasuredNode:
    """Convert an internal source record to the published node identity."""
    return metrics_mod.MeasuredNode(
        canonical_id=source.canonical_id,
        folder=source.folder,
        kind=source.kind,
        representative_url=source.representative_url,
        state_name=source.state_name,
    )


#: Raw action vocabulary keys aggregated into ``metrics.action``.
_ACTION_COUNT_KEYS: tuple[str, ...] = ("click", "fill", "hover", "select_option", "scroll")

#: Semantic action buckets published under ``metrics.action.semantic``.
_SEMANTIC_ACTION_KEYS: tuple[str, ...] = (
    "search",
    "filter",
    "goto_home",
    "goto_collection",
    "goto_product",
    "goto_policy",
    "goto_cart",
    "open_cart",
    "explore",
)


def _observation_from_node_measurements(
    measurements: list[_ObservationNodeMeasurement],
) -> metrics_mod.Observation:
    """Aggregate node-level observation measurements for ``metrics.json``."""
    node_count = 0
    interactive_count = 0
    max_depth = 0
    semantic_max_depth = 0
    content_character_count = 0
    distinct_signatures: set[str] = set()
    rubric_totals = _empty_rubric_counts()
    for measurement in measurements:
        entry = measurement.entry
        if not isinstance(entry, metrics_mod.ObservationNodeOk):
            continue
        stats = entry.axtree
        node_count += stats.node_count
        interactive_count += stats.interactive_count
        max_depth = max(max_depth, stats.max_depth)
        semantic_max_depth = max(semantic_max_depth, stats.semantic_max_depth)
        content_character_count += stats.content_character_count
        distinct_signatures.update(_axtree_node_signatures(measurement.axtree))
        _add_rubric_counts(rubric_totals, entry.rubric)
    return metrics_mod.Observation(
        node_count=node_count,
        interactive_count=interactive_count,
        distinct_node_count=len(distinct_signatures),
        max_depth=max_depth,
        semantic_max_depth=semantic_max_depth,
        content_character_count=content_character_count,
        rubric=metrics_mod.Rubric(**rubric_totals),
    )


def _action_from_node_measurements(
    measurements: list[_ActionNodeMeasurement],
    graph: TransitionGraph,
) -> metrics_mod.Action:
    """Aggregate node-level action measurements for ``metrics.json``."""
    raw_counts: dict[str, int] = dict.fromkeys(_ACTION_COUNT_KEYS, 0)
    choice_target_count = 0
    for measurement in measurements:
        entry = measurement.entry
        if not isinstance(entry, metrics_mod.ActionNodeOk):
            continue
        raw_counts["click"] += entry.click
        raw_counts["fill"] += entry.fill
        raw_counts["hover"] += entry.hover
        raw_counts["select_option"] += entry.select_option
        raw_counts["scroll"] += entry.scroll
        choice_target_count += entry.choice_target_count
    return metrics_mod.Action(
        click=raw_counts["click"],
        fill=raw_counts["fill"],
        hover=raw_counts["hover"],
        select_option=raw_counts["select_option"],
        scroll=raw_counts["scroll"],
        choice_target_count=choice_target_count,
        semantic=_semantic_action_counts(graph),
    )


def _empty_rubric_counts() -> dict[str, int]:
    """Return a zero-valued rubric count map keyed by the closed enum."""
    return dict.fromkeys(metrics_mod.RUBRIC_CATEGORIES, 0)


def _add_rubric_counts(counts: dict[str, int], rubric: metrics_mod.Rubric) -> None:
    """Add ``rubric`` into ``counts`` in place."""
    for category in metrics_mod.RUBRIC_CATEGORIES:
        value = getattr(rubric, category)
        if isinstance(value, int) and not isinstance(value, bool):
            counts[category] += value


def _axtree_node_signatures(axtree: dict[str, Any] | None) -> set[str]:
    """Return normalized role/name signatures for distinct website nodes."""
    if axtree is None:
        return set()
    raw_nodes = axtree.get("nodes", [])
    if not isinstance(raw_nodes, list):
        return set()
    signatures: set[str] = set()
    for raw_node in cast("list[object]", raw_nodes):
        if not isinstance(raw_node, dict):
            continue
        node = cast("dict[str, Any]", raw_node)
        role = _axtree_node_value(node.get("role"))
        name = _normalize_action_text(_axtree_node_value(node.get("name")))
        signatures.add(f"{role}\u241f{name}")
    return signatures


def _axtree_node_value(value: object) -> str:
    """Return a CDP ``{value: ...}`` string, or ``\"\"`` when absent."""
    if not isinstance(value, dict):
        return ""
    raw = cast("dict[str, object]", value).get("value")
    return raw if isinstance(raw, str) else ""


def _semantic_action_counts(
    graph: TransitionGraph,
) -> metrics_mod.ActionSemanticCounts:
    """Compute mutually exclusive semantic action counts from graph edges."""
    counts: dict[str, int] = dict.fromkeys(_SEMANTIC_ACTION_KEYS, 0)
    for edge in graph.edges:
        category = _semantic_category_for_edge(edge.target, graph)
        if category is not None:
            counts[category] += 1
    return metrics_mod.ActionSemanticCounts(**counts)


def _semantic_category_for_edge(
    target_id: str,
    graph: TransitionGraph,
) -> str | None:
    """Classify one transition edge target into a semantic action bucket."""
    target = graph.nodes.get(target_id)
    if target is None:
        return None
    if target.kind == "state":
        if target.state_name == "cart_drawer":
            return "open_cart"
        if target.state_name in {"search_overlay", "predictive_panel"}:
            return "search"
        if target.state_name in {"filter_panel_open", "sort_menu_open"}:
            return "filter"
        return "explore"
    return _canonical_page_category(target.canonical_id)


def _canonical_page_category(canonical_id: str) -> str:
    """Map a canonical URL node id to one semantic navigation bucket."""
    category = "explore"
    if canonical_id == "/":
        category = "goto_home"
    elif canonical_id == "/cart" or canonical_id.startswith("/cart/"):
        category = "goto_cart"
    elif canonical_id == "/search" or canonical_id.startswith("/search"):
        category = "search"
    elif canonical_id.startswith("/collections/") or canonical_id == "/collections":
        category = "goto_collection"
    elif canonical_id.startswith("/products/") or canonical_id == "/products":
        category = "goto_product"
    elif canonical_id.startswith("/policies/") or canonical_id == "/policies":
        category = "goto_policy"
    return category


def _normalize_action_text(text: str) -> str:
    """Lowercase and whitespace-normalize action text for matching."""
    return " ".join(text.casefold().split())


def _observation_index_entry(
    entry: metrics_mod.ObservationNodeOk | metrics_mod.NodeNotFound,
) -> dict[str, Any]:
    """Return one ``observation/index.json`` node entry."""
    base: dict[str, Any] = _node_index_base(entry)
    if isinstance(entry, metrics_mod.ObservationNodeOk):
        base.update(
            {
                "screenshot": f"{entry.node.folder}.png",
                "axtree_json": f"{entry.node.folder}.axtree.json",
                "axtree_text": f"{entry.node.folder}.axtree.txt",
                "rubric": f"{entry.node.folder}.rubric.json",
            },
        )
    else:
        base["reason"] = entry.reason
    return base


def _action_index_entry(
    entry: metrics_mod.ActionNodeOk | metrics_mod.NodeNotFound,
) -> dict[str, Any]:
    """Return one ``action/index.json`` node entry."""
    base: dict[str, Any] = _node_index_base(entry)
    if isinstance(entry, metrics_mod.ActionNodeOk):
        base["action_space"] = f"{entry.node.folder}.action_space.json"
    else:
        base["reason"] = entry.reason
    return base


def _node_index_base(
    entry: metrics_mod.ObservationNodeOk | metrics_mod.ActionNodeOk | metrics_mod.NodeNotFound,
) -> dict[str, Any]:
    """Return common index metadata for one measured node."""
    return {
        "canonical_id": entry.node.canonical_id,
        "folder": entry.node.folder,
        "kind": entry.node.kind,
        "representative_url": entry.node.representative_url,
        "state_name": entry.node.state_name,
        "status": entry.status,
    }


def _write_node_layer_index(layer_dir: Path, nodes: list[dict[str, Any]]) -> Path:
    """Write a deterministic node-layer ``index.json`` file."""
    payload: dict[str, Any] = {
        "artifact_version": _NODE_LAYER_ARTIFACT_VERSION,
        "nodes": nodes,
    }
    path = layer_dir / _NODE_LAYER_INDEX_FILENAME
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _read_json_object(path: Path) -> dict[str, Any]:
    """Read a JSON object from ``path`` and fail loudly on non-objects."""
    payload = cast("object", json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise TypeError(f"expected JSON object at {path}")
    return cast("dict[str, Any]", payload)


# ---------------------------------------------------------------------------
# Metrics block builders (M1 fills observation; M3+M4-M5 fill the rest).
# ---------------------------------------------------------------------------


def _build_shop(pages_doc: pages_mod.PagesDoc) -> metrics_mod.Shop:
    """Translate the storefront URL into the metrics ``shop`` block."""
    domain = urlsplit(pages_doc.base_url).hostname or ""
    return metrics_mod.Shop(url=pages_doc.base_url, domain=domain)


def _pages_for_metrics(pages_doc: pages_mod.PagesDoc) -> metrics_mod.Pages:
    """Translate the rich ``pages.json`` doc into the closed metrics block."""
    return metrics_mod.Pages(
        homepage=_page_to_metrics(pages_doc.homepage),
        collection=_page_to_metrics(pages_doc.collection),
        product=_page_to_metrics(pages_doc.product),
        policy=_page_to_metrics(pages_doc.policy),
        cart_and_search=metrics_mod.CartAndSearch(
            cart=_page_to_metrics(pages_doc.cart_and_search.cart),
            search=_search_to_metrics(pages_doc.cart_and_search.search),
        ),
    )


def _page_to_metrics(
    entry: pages_mod.PageOk | pages_mod.PageNotFound,
) -> metrics_mod.PageOk | metrics_mod.NotFound:
    """Map the ``pages`` page entry into its ``metrics`` counterpart."""
    if isinstance(entry, pages_mod.PageNotFound):
        return metrics_mod.NotFound(reason=entry.reason)
    return metrics_mod.PageOk(
        url=entry.url,
        canonical_url=entry.canonical_url,
        selected_by=entry.selected_by,
    )


def _search_to_metrics(
    entry: pages_mod.SearchPageOk | pages_mod.PageNotFound,
) -> metrics_mod.SearchPageOk | metrics_mod.NotFound:
    """Map the ``pages`` search entry into its ``metrics`` counterpart."""
    if isinstance(entry, pages_mod.PageNotFound):
        return metrics_mod.NotFound(reason=entry.reason)
    # ``raw_source`` is recorded in pages.json only — the published metrics
    # schema (§5.8) intentionally omits it so cohort comparisons stay clean.
    return metrics_mod.SearchPageOk(
        url=entry.url,
        query=entry.query,
        selected_by=entry.selected_by,
    )


def _action_counts_from_payload(payload: dict[str, Any]) -> metrics_mod.ActionCounts:
    """Project action-space artifact counts onto :class:`metrics.ActionCounts`."""
    raw = payload.get("by_action", {})
    by_action = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
    raw_category = payload.get("by_category", {})
    by_category = cast("dict[str, Any]", raw_category) if isinstance(raw_category, dict) else {}
    counts: dict[str, int] = {}
    for key in _ACTION_COUNT_KEYS:
        value = by_action.get(key, 0)
        counts[key] = value if isinstance(value, int) and not isinstance(value, bool) else 0
    choice = by_category.get("choice", 0)
    counts["choice_target_count"] = (
        choice if isinstance(choice, int) and not isinstance(choice, bool) else 0
    )
    return metrics_mod.ActionCounts(**counts)


# ---------------------------------------------------------------------------
# Transition layer (M4 structural BFS).
# ---------------------------------------------------------------------------


def _capture_transition(
    session: EnvEvalSession,
    base_url: str,
    pages_doc: pages_mod.PagesDoc,
    transition_dir: Path,
    *,
    run_dir: Path,
    max_hops: int,
    llm_client: LLMVisionClient | None,
    pages_classifier_client: LLMVisionClient | None,
    pages_classifier_model: str,
) -> tuple[metrics_mod.Transition, int, TransitionGraph]:
    """Drive the BFS + stateful passes and return the transition metrics block.

    Builds one :class:`bfs.BfsSeed` per ``ok`` measurable bucket (homepage,
    collection, product, policy, cart, search) and walks the graph with
    :func:`bfs.run_bfs`, bounded by ``max_hops`` and the spec §5.5 global
    cap (:data:`bfs.GLOBAL_CAP`). Persists ``transition/graph.json``,
    ``transition/trace.jsonl``, ``transition/pages_classification.json``,
    and one URL-node artifact folder per graph URL node, then returns the
    closed :class:`metrics.Transition` document.

    The ``/pages/<slug>`` classifier
    (:mod:`shop_arena.env_eval.transition.pages_classifier`) runs lazily
    inside the BFS: every page expansion that surfaces fresh slugs triggers
    one batched LLM call which returns the cumulative collapse set, then
    :func:`canonicalize_href` uses that set for the rest of the run.
    The current document is persisted after every update so resume picks
    up from disk on the next invocation.

    The M5 stateful pass (:mod:`shop_arena.env_eval.transition.stateful`)
    runs immediately after BFS — the executor walks the closed rule list,
    fires each rule against its page-class target, asks the state-namer LLM
    to disambiguate every structural diff, and extends the same graph in
    place with state nodes/edges plus per-node artifacts under
    ``transition/node/``. Stateful trace lines are appended to ``trace.jsonl``
    (``phase="stateful"``). When ``llm_client`` is ``None``
    (i.e. ``--no-rubric`` or any other no-LLM run) the stateful pass is
    skipped entirely — ``state_node_count`` stays ``0`` and
    ``homepage_to_cart_min_clicks`` only counts a hop to a reachable
    ``/cart`` URL node.

    Reuse follows spec §5.7: when ``graph.json``, ``trace.jsonl``, and the
    per-node artifact index already exist on disk, BFS *and* the stateful pass
    are skipped — the existing graph is reloaded and its metrics are recomputed
    from the persisted node/edge tables. The classifier document is also
    reused as-is (no fresh LLM call); when it is absent the final collapse
    set is empty.

    Args:
        session: Live BrowserGym session shared across the pipeline.
        base_url: Storefront base URL (scheme + host + ``/``).
        pages_doc: Page-selection document used to derive seeds.
        transition_dir: ``<run_dir>/transition/``.
        run_dir: Run directory; receives the classifier artifact.
        max_hops: BFS depth.
        llm_client: Vision client used by the stateful state-namer; ``None``
            disables the stateful pass.
        pages_classifier_client: Text-output client used by the
            ``/pages/`` classifier; ``None`` switches the classifier to
            the no-LLM stub. Today this mirrors ``llm_client`` (both
            ``None`` under ``--no-rubric``) — they are passed separately
            so a future flag can vary them independently.
        pages_classifier_model: Model id recorded on the classifier
            artifact's ``model`` field. Ignored in stub mode.

    Returns:
        ``(metrics, llm_calls, graph)`` — ``metrics`` is the closed
        :class:`metrics.Transition` block, ``llm_calls`` is the number of
        LLM calls actually issued by the classifier and the state-namer
        combined, and ``graph`` is returned so observation/action can
        consume the captured node artifacts.
    """
    graph_path = transition_dir / "graph.json"
    trace_path = transition_dir / "trace.jsonl"
    legacy_states_dir = transition_dir / "states"
    node_root = transition_dir / node_artifacts_mod.NODE_DIRNAME
    node_index_path = node_root / node_artifacts_mod.NODE_INDEX_FILENAME
    if graph_path.is_file() and trace_path.is_file() and node_index_path.is_file():
        payload = cast("dict[str, Any]", json.loads(graph_path.read_text(encoding="utf-8")))
        graph = TransitionGraph.from_dict(payload)
        if legacy_states_dir.exists():
            shutil.rmtree(legacy_states_dir)
        return graph.compute_metrics(), 0, graph

    if legacy_states_dir.exists():
        shutil.rmtree(legacy_states_dir)
    if node_root.exists():
        shutil.rmtree(node_root)

    classify_fn, classifier_calls_counter = _make_pages_classify_fn(
        run_dir=run_dir,
        base_url=base_url,
        model=pages_classifier_model,
        llm=pages_classifier_client,
    )

    seeds = _build_bfs_seeds(base_url, pages_doc)
    browser = _BfsSessionBrowser(session)
    result = bfs_mod.run_bfs(
        browser,
        base_url,
        seeds,
        max_hops=max_hops,
        classify_pages=classify_fn,
    )
    graph = TransitionGraph.from_bfs(result)
    bfs_mod.write_trace_jsonl(result.attempts, trace_path)

    final_collapse = _final_collapse_set(run_dir)
    bound_canonical_id = functools.partial(
        canonical_id_for_url,
        collapse_pages=final_collapse,
    )

    stateful_llm_calls = _run_stateful_pass(
        session=session,
        base_url=base_url,
        pages_doc=pages_doc,
        graph=graph,
        node_root=node_root,
        trace_path=trace_path,
        run_dir=run_dir,
        llm_client=llm_client,
        canonical_id_for_url=bound_canonical_id,
    )
    _capture_transition_node_artifacts(session, graph, node_root)
    write_graph_json(graph, graph_path)
    classifier_llm_calls = classifier_calls_counter()
    return (
        graph.compute_metrics(),
        stateful_llm_calls + classifier_llm_calls,
        graph,
    )


def _final_collapse_set(run_dir: Path) -> frozenset[str]:
    """Return the cumulative collapse set from the on-disk classifier doc.

    Returns an empty frozenset when the classifier artifact is absent
    (e.g. a run that never discovered any ``/pages/<slug>`` href).
    """
    classification_path = (
        run_dir
        / "transition"
        / pages_classifier_mod.PAGES_CLASSIFICATION_FILENAME
    )
    if not classification_path.is_file():
        return frozenset()
    doc = pages_classifier_mod.read_pages_classification(run_dir)
    return pages_classifier_mod.collapse_set_from(doc)


def _make_pages_classify_fn(
    *,
    run_dir: Path,
    base_url: str,
    model: str,
    llm: LLMVisionClient | None,
) -> tuple[bfs_mod.PagesClassifyFn, _LlmCallCounter]:
    """Build the BFS-callable classifier callback.

    Returns ``(classify_fn, counter)``. ``classify_fn`` accepts the
    BFS-discovered slugs, classifies any slug not yet covered by the
    persisted document, writes the updated document to disk, and returns
    the cumulative collapse set the BFS should use from now on.
    ``counter`` is a zero-arg callable returning the number of real LLM
    completions issued so far — the orchestrator folds the value into
    ``manifest.llm_calls`` after the BFS finishes.

    When ``llm`` is ``None`` the callback runs in stub mode: every new
    slug is recorded with label ``"unknown"`` and no path is collapsed;
    the document still lands on disk so resume detection sees a
    schema-valid artifact.
    """
    classification_path = (
        run_dir
        / "transition"
        / pages_classifier_mod.PAGES_CLASSIFICATION_FILENAME
    )
    if classification_path.is_file():
        existing: pages_classifier_mod.PagesClassification | None = (
            pages_classifier_mod.read_pages_classification(run_dir)
        )
    else:
        existing = None

    state = _PagesClassifierState(
        run_dir=run_dir,
        base_url=base_url,
        model=model,
        llm=llm,
        doc=existing,
        llm_calls=0,
    )

    def classify_fn(new_paths: Sequence[str]) -> frozenset[str]:
        return state.classify(new_paths)

    return classify_fn, state.llm_call_count


@dataclass
class _PagesClassifierState:
    """Mutable closure backing :func:`_make_pages_classify_fn`.

    Holds the running classification document, persists it after every
    update, and tracks the number of LLM completions issued.
    """

    run_dir: Path
    base_url: str
    model: str
    llm: LLMVisionClient | None
    doc: pages_classifier_mod.PagesClassification | None
    llm_calls: int

    def classify(self, new_paths: Sequence[str]) -> frozenset[str]:
        """Classify ``new_paths`` and return the cumulative collapse set."""
        before = self.doc
        if self.llm is None:
            stub = pages_classifier_mod.stub_classification(new_paths)
            self.doc = _merge_stub_doc(self.doc, stub)
        else:
            self.doc = pages_classifier_mod.merge_classifications(
                self.doc,
                new_paths=new_paths,
                base_url=self.base_url,
                model=self.model,
                llm=self.llm,
            )
            if self.doc is not before:
                self.llm_calls += 1
        if self.doc is not before:
            pages_classifier_mod.write_pages_classification(self.doc, self.run_dir)
        return pages_classifier_mod.collapse_set_from(self.doc)

    def llm_call_count(self) -> int:
        """Return the number of LLM completions issued so far."""
        return self.llm_calls


def _merge_stub_doc(
    existing: pages_classifier_mod.PagesClassification | None,
    fresh: pages_classifier_mod.PagesClassification,
) -> pages_classifier_mod.PagesClassification:
    """Append unseen ``fresh.entries`` onto ``existing``, preserving order.

    Mirrors the merge contract of
    :func:`pages_classifier.merge_classifications` for the no-LLM path:
    every existing entry is kept verbatim (so labels from a previous run
    are preserved) and only paths that ``existing`` has not seen yet are
    added. The resulting doc carries ``model="stub"`` so consumers can
    tell stub-mode artifacts apart from real classifier runs.
    """
    if existing is None:
        return fresh
    seen = {entry.path for entry in existing.entries}
    additions = [entry for entry in fresh.entries if entry.path not in seen]
    if not additions:
        return existing
    merged = list(existing.entries) + additions
    return pages_classifier_mod.PagesClassification(
        classifier_version=pages_classifier_mod.PAGES_CLASSIFIER_VERSION,
        model=fresh.model,
        entries=merged,
    )


#: Zero-arg callable returning the cumulative LLM-call count for the
#: ``/pages/`` classifier closure. Aliased so the orchestrator can fold the
#: tally into ``manifest.llm_calls`` without leaking implementation details.
type _LlmCallCounter = Callable[[], int]


#: Pure function ``(url) -> canonical_id`` already bound to the BFS-derived
#: ``collapse_pages`` set. Threaded into the stateful pass so URL→canonical
#: mapping there matches what the BFS used.
type _CanonicalIdFn = Callable[[str], str]


def _build_bfs_seeds(
    base_url: str,
    pages_doc: pages_mod.PagesDoc,
) -> list[bfs_mod.BfsSeed]:
    """Return one :class:`bfs.BfsSeed` per ``ok`` measurable bucket (spec §5.5.1).

    Iteration order matches the observation/action layers
    (homepage → collection → product → policy → cart → search) so the
    seed ordering recorded in :attr:`TransitionGraph.seeds` is byte-stable
    and easy to read alongside the rest of the run directory.  Buckets that
    discovery flagged ``not_found`` are skipped — they have no concrete URL
    to navigate to.  Duplicate canonical ids (e.g. when ``collection`` and
    ``product`` happen to share a template-collapsed id) are tolerated by
    :func:`bfs.run_bfs`; only the first occurrence is enqueued.
    """
    entries: list[pages_mod.PageOk | pages_mod.PageNotFound | pages_mod.SearchPageOk] = [
        pages_doc.homepage,
        pages_doc.collection,
        pages_doc.product,
        pages_doc.policy,
        pages_doc.cart_and_search.cart,
        pages_doc.cart_and_search.search,
    ]
    seeds: list[bfs_mod.BfsSeed] = []
    for entry in entries:
        if isinstance(entry, pages_mod.PageNotFound):
            continue
        target_url = _join_url(base_url, entry.url)
        seeds.append(
            bfs_mod.BfsSeed(
                canonical_id=canonical_id_for_url(target_url),
                representative_url=target_url,
            ),
        )
    return seeds


class _BfsSessionBrowser:
    """:class:`bfs.BfsBrowser` adapter backed by an :class:`EnvEvalSession`.

    The structural BFS only needs ``goto``, ``current_url``, and ``hrefs``.
    Tests inject a stub session whose ``page.evaluate`` returns ``[]`` to
    skip live link scanning.
    """

    def __init__(self, session: EnvEvalSession) -> None:
        self._session = session

    def goto(self, url: str) -> int | None:
        """Navigate to ``url`` and return the HTTP status (or ``None``)."""
        response = self._session.goto(url)
        return None if response is None else int(response.status)

    def current_url(self) -> str:
        """Return the browser's current URL after the latest navigation."""
        return self._session.page.url

    def hrefs(self, selector: str = "a[href]") -> list[str]:
        """Return absolute hrefs for ``selector`` matches in DOM order."""
        page = self._session.page
        result: Any = page.evaluate(
            "(sel) => Array.from(document.querySelectorAll(sel), (a) => a.href)",
            selector,
        )
        if not isinstance(result, list):
            return []
        out: list[str] = []
        for item in result:  # pyright: ignore[reportUnknownVariableType]
            if isinstance(item, str):
                out.append(item)
        return out


# ---------------------------------------------------------------------------
# Transition node artifact capture (URL nodes).
# ---------------------------------------------------------------------------


def _capture_transition_node_artifacts(
    session: EnvEvalSession,
    graph: TransitionGraph,
    node_root: Path,
) -> None:
    """Write ``transition/node/`` artifacts for every graph node.

    Stateful node folders are created by the stateful pass as soon as a rule
    fires because that pass owns the pre/post axtrees. This function captures
    URL-node browser states and writes the shared ``index.json`` after all graph
    mutations are complete.
    """
    node_root.mkdir(parents=True, exist_ok=True)
    for node in graph.nodes.values():
        if node.kind != "url":
            continue
        _capture_url_node_artifact(session, node, node_root)
    node_artifacts_mod.write_node_index(
        node_root=node_root,
        nodes=[(node.canonical_id, node.kind) for node in graph.nodes.values()],
    )


def _capture_url_node_artifact(
    session: EnvEvalSession,
    node: GraphNode,
    node_root: Path,
) -> None:
    """Capture screenshot + axtree for one URL graph node."""
    folder = node_root / node_artifacts_mod.node_folder_name(node.canonical_id)
    folder.mkdir(parents=True, exist_ok=True)
    axtree_json_path = folder / "axtree.json"
    axtree_text_path = folder / "axtree.txt"
    written_axtree_json_path: Path | None = None
    written_axtree_text_path: Path | None = None
    screenshot_png: bytes | None = None
    http_status: int | None = None
    error: str | None = None
    try:
        response = session.goto(node.representative_url)
        http_status = None if response is None else int(response.status)
        # Settle the page before snapshotting so delayed DOM mutations
        # (setTimeout newsletter modals, lazy chat launchers, fade-in
        # heroes) are reflected in the URL-node axtree + screenshot.
        # The homepage gets a min-wait floor because email-signup popups
        # almost exclusively target the first page of the visit and fire
        # on a 2-4s timer that does not re-arm the stability counter
        # (hero animations are pure CSS, fingerprint stays stable).  Other
        # surfaces almost never trigger first-load popups, so they pay no
        # extra latency.
        wait_for_axtree_settle(
            axtree=session.axtree,
            min_wait_ms=DEFAULT_AXTREE_MIN_WAIT_HOMEPAGE_MS
            if node.canonical_id == "/"
            else 0,
        )
        axtree = session.axtree()
        screenshot_png = _encode_screenshot(session.screenshot())
        _write_axtree_json(axtree_json_path, axtree)
        written_axtree_json_path = axtree_json_path
        _write_axtree_text(axtree_text_path, render_axtree_text(axtree))
        written_axtree_text_path = axtree_text_path
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    node_artifacts_mod.write_url_node_artifact(
        node_root=node_root,
        canonical_id=node.canonical_id,
        representative_url=node.representative_url,
        screenshot_png=screenshot_png,
        axtree_json_path=written_axtree_json_path,
        axtree_text_path=written_axtree_text_path,
        http_status=http_status,
        error=error,
    )


# ---------------------------------------------------------------------------
# Stateful pass (M5) glue.
# ---------------------------------------------------------------------------


def _run_stateful_pass(
    *,
    session: EnvEvalSession,
    base_url: str,
    pages_doc: pages_mod.PagesDoc,
    graph: TransitionGraph,
    node_root: Path,
    trace_path: Path,
    run_dir: Path,
    llm_client: LLMVisionClient | None,
    canonical_id_for_url: _CanonicalIdFn,
) -> int:
    """Run the stateful rule pass against the active session and append trace.

    Translates the live :class:`EnvEvalSession` + ``pages_doc`` into the call
    surface :func:`run_stateful_pass` consumes, writes node-scoped state
    artifacts under ``transition/node/``, then appends the resulting trace
    lines to ``trace.jsonl``. Returns the count of state-namer LLM calls
    actually issued so the orchestrator can fold them into
    ``manifest.llm_calls``.

    Skipped entirely when ``llm_client`` is ``None`` (``--no-rubric`` runs):
    a fired rule needs the state-namer to assign a closed-enum state name,
    so dropping the LLM means dropping the pass.

    Args:
        canonical_id_for_url: ``(url) -> canonical_id`` already bound to the
            BFS-derived ``collapse_pages`` set; threaded so the stateful
            pass collapses ``/pages/<slug>`` URLs into the same canonical
            id the BFS used.
    """
    if llm_client is None:
        return 0
    page_targets = _build_stateful_page_targets(base_url, pages_doc)
    if not page_targets:
        return 0
    derived_query = _derived_query(pages_doc)

    page = getattr(session, "page", None)

    def _goto(url: str) -> object:
        return session.goto(url)

    def _axtree() -> dict[str, Any]:
        return session.axtree()

    def _screenshot_png() -> bytes:
        return _encode_screenshot(session.screenshot())

    with tempfile.TemporaryDirectory(prefix="shop-env-eval-stateful-") as tmp_dir:
        attempts, llm_calls = run_stateful_pass(
            rules=RULES,
            page_targets=page_targets,
            derived_query=derived_query,
            graph=graph,
            states_dir=Path(tmp_dir),
            llm_client=llm_client,
            goto=_goto,
            axtree=_axtree,
            screenshot_png=_screenshot_png,
            page=page,
            canonical_id_for_url=canonical_id_for_url,
            node_root=node_root,
            run_dir=run_dir,
        )
    write_stateful_trace_lines(attempts, trace_path)
    return llm_calls


def _build_stateful_page_targets(
    base_url: str,
    pages_doc: pages_mod.PagesDoc,
) -> dict[str, str]:
    """Return ``{page_class: page_url}`` for every measurable bucket.

    Mirrors :func:`_build_bfs_seeds`'s bucket order; ``not_found`` buckets
    are dropped — their rules cannot fire because there is no concrete URL
    to navigate to.  ``cart_and_search`` is split into the two leaves the
    rule list addresses (``cart`` + ``search``) so each leaf is keyed by its
    own page class string.
    """
    targets: dict[str, str] = {}
    for page_class, entry in (
        ("homepage", pages_doc.homepage),
        ("collection", pages_doc.collection),
        ("product", pages_doc.product),
        ("cart", pages_doc.cart_and_search.cart),
        ("search", pages_doc.cart_and_search.search),
    ):
        if isinstance(entry, pages_mod.PageNotFound):
            continue
        targets[page_class] = _join_url(base_url, entry.url)
    return targets


def _derived_query(pages_doc: pages_mod.PagesDoc) -> str | None:
    """Return the search query inferred during page selection, or ``None``."""
    search = pages_doc.cart_and_search.search
    if isinstance(search, pages_mod.SearchPageOk):
        return search.query
    return None
