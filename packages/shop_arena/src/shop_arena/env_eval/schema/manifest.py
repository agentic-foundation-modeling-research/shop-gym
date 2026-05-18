"""Closed-schema ``manifest.json`` (spec §5.7).

``manifest.json`` is the per-run *operations* record:
which steps ran vs. reused, the BrowserGym version, prompt/rule/heuristic
versions, browser-navigation and LLM-call counters, run timestamps, and a
snapshot of the ``EvalConfig`` that produced the run.  These run facts
intentionally stay out of ``metrics.json`` so the published metrics stay a
clean comparable measurement artifact.

Public surface:

* ``ConfigSnapshot`` — frozen+closed mirror of :class:`EvalConfig`.
* ``StepRecord`` — per-step ``(ran, reused)`` accounting entry.
* ``Manifest`` — frozen+closed top-level document.
* ``build_manifest`` / ``write_manifest`` — helpers used by
  :func:`shop_arena.env_eval.pipeline.evaluate`.

M6 added the full §5.7 field set on top of the M1 skeleton:
``started_at``/``ended_at`` timestamps, ``browsergym_version``, the
rubric/state prompt versions, ``rule_version``, and ``heuristic_version``.
The closed-schema discipline here keeps any future extension loud.
"""

from __future__ import annotations

import json
from datetime import datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from shop_arena.env_eval.action import HEURISTIC_VERSION
from shop_arena.env_eval.config import EvalConfig
from shop_arena.env_eval.observation.rubric import RUBRIC_PROMPT_VERSION
from shop_arena.env_eval.resume import Step
from shop_arena.env_eval.transition.pages_classifier import PAGES_CLASSIFIER_VERSION
from shop_arena.env_eval.transition.rules import RULE_VERSION
from shop_arena.env_eval.transition.stateful import STATE_PROMPT_VERSION

__all__ = [
    "MANIFEST_JSON_FILENAME",
    "MANIFEST_VERSION",
    "ConfigSnapshot",
    "Manifest",
    "StepRecord",
    "build_manifest",
    "resolve_browsergym_version",
    "write_manifest",
]

#: Filename for the per-run manifest, fixed by spec §5.6.
MANIFEST_JSON_FILENAME: Final[str] = "manifest.json"

#: Version of the ``manifest.json`` schema itself.  Distinct from the
#: package version (:data:`shop_arena.env_eval._version.__version__`)
#: and from :data:`shop_arena.env_eval.schema.metrics.METRICS_SCHEMA_VERSION`.
#: M6 fields land under the same ``"0.1"`` schema; a breaking shape
#: change bumps this string.
MANIFEST_VERSION: Literal["0.1"] = "0.1"


class ConfigSnapshot(BaseModel):
    """Frozen snapshot of the :class:`EvalConfig` that drove this run.

    Stored verbatim so M6's resume logic can detect a config-drift
    mismatch between a saved run and a re-invocation against the same
    ``out_dir``.  ``out_dir`` is recorded as the user-supplied value
    (a string path or ``None``); the *resolved* run directory is the
    file's parent and does not need to be repeated in the payload.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(min_length=1)
    out_dir: str | None = None
    viewport: tuple[int, int]
    max_hops: int = Field(ge=0)
    rubric_model: str = Field(min_length=1)
    pages_classifier_model: str = Field(min_length=1)
    rediscover: bool
    shop_name: str | None = None
    no_rubric: bool


class StepRecord(BaseModel):
    """Per-step ``(ran, reused)`` record (spec §5.7 / impl-plan M6).

    The pipeline records one entry per :data:`shop_arena.env_eval.resume.STEPS`
    literal in execution order.  ``ran`` and ``reused`` are mutually exclusive:
    a step either performed its measurement work (``ran=True``) or short-
    circuited via existing artifacts on disk (``reused=True``).  Both ``False``
    is invalid; both ``True`` is invalid; the model rejects either combination
    at validation time so drift is loud.

    Attributes:
        name: Step identifier.  One of :data:`shop_arena.env_eval.resume.STEPS`.
        ran: ``True`` iff the step performed live work (browser/LLM/file write).
        reused: ``True`` iff the step short-circuited via existing artifacts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Step
    ran: bool
    reused: bool

    def model_post_init(self, _context: object) -> None:  # type: ignore[override]
        """Reject the two impossible ``(ran, reused)`` combinations."""
        if self.ran == self.reused:
            msg = (
                f"step {self.name!r}: ran={self.ran} and reused={self.reused} "
                "must be mutually exclusive (exactly one True)"
            )
            raise ValueError(msg)


class Manifest(BaseModel):
    """Top-level ``manifest.json`` document (spec §5.7).

    Attributes:
        manifest_version: Schema version of the manifest document.
        eval_version: Package version of ``shop_arena.env_eval`` that
            produced the run.
        config: Snapshot of the input :class:`EvalConfig`.
        started_at: UTC timestamp captured before any pipeline work runs.
        ended_at: UTC timestamp captured after every step has either run
            or been skipped.  ``ended_at >= started_at`` is enforced.
        browsergym_version: Installed ``browsergym`` package version
            (:func:`importlib.metadata.version`), or ``"unknown"`` when
            the metadata is unavailable.
        browser_navigations: Total count of ``page.goto()`` calls made
            during the run, including the initial homepage navigation
            done by :meth:`EnvEvalBrowserTask.setup`.
        llm_calls: Total count of LLM completions issued during the
            run (rubric + state-namer combined).
        steps: Per-step ``(ran, reused)`` records.  Empty tuple means the
            orchestrator did not record step status (legacy payload); a
            populated tuple lists one :class:`StepRecord` per known step
            in execution order.
        rubric_prompt_version: Pinned version of the screenshot-rubric
            prompt + schema (:data:`observation.rubric.RUBRIC_PROMPT_VERSION`).
        state_prompt_version: Pinned version of the state-namer prompt
            (:data:`transition.stateful.STATE_PROMPT_VERSION`).
        rule_version: Pinned version of the closed stateful rule list
            (:data:`transition.rules.RULE_VERSION`).
        heuristic_version: Pinned version of the role/action heuristic
            (:data:`action.HEURISTIC_VERSION`).
        pages_classifier_version: Pinned version of the ``/pages/<slug>``
            classifier prompt + schema
            (:data:`transition.pages_classifier.PAGES_CLASSIFIER_VERSION`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_version: Literal["0.1"] = MANIFEST_VERSION
    eval_version: str = Field(min_length=1)
    config: ConfigSnapshot
    started_at: AwareDatetime
    ended_at: AwareDatetime
    browsergym_version: str = Field(min_length=1)
    browser_navigations: int = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    steps: tuple[StepRecord, ...] = Field(default_factory=tuple)
    rubric_prompt_version: str = Field(min_length=1)
    state_prompt_version: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    heuristic_version: str = Field(min_length=1)
    pages_classifier_version: str = Field(min_length=1)

    def model_post_init(self, _context: object) -> None:  # type: ignore[override]
        """Reject ``ended_at`` strictly before ``started_at``."""
        if self.ended_at < self.started_at:
            msg = (
                f"ended_at={self.ended_at.isoformat()} precedes "
                f"started_at={self.started_at.isoformat()}"
            )
            raise ValueError(msg)


def resolve_browsergym_version() -> str:
    """Return the installed ``browsergym`` version, or ``"unknown"``.

    Read at call time via :func:`importlib.metadata.version` so the manifest
    records what actually drove the run.  Falls back to the literal string
    ``"unknown"`` when the package metadata is missing (e.g. a vendored or
    editable install with no dist-info), keeping ``manifest.json`` writable
    rather than failing loud at the very end of a run.
    """
    try:
        return _pkg_version("browsergym")
    except PackageNotFoundError:
        return "unknown"


def build_manifest(
    config: EvalConfig,
    *,
    eval_version: str,
    browser_navigations: int,
    started_at: datetime,
    ended_at: datetime,
    llm_calls: int = 0,
    steps: tuple[StepRecord, ...] = (),
    browsergym_version: str | None = None,
    rubric_prompt_version: str = RUBRIC_PROMPT_VERSION,
    state_prompt_version: str = STATE_PROMPT_VERSION,
    rule_version: str = RULE_VERSION,
    heuristic_version: str = HEURISTIC_VERSION,
    pages_classifier_version: str = PAGES_CLASSIFIER_VERSION,
) -> Manifest:
    """Build a :class:`Manifest` from an ``EvalConfig`` + run counters.

    Args:
        config: User-supplied configuration.  Snapshotted verbatim.
        eval_version: ``shop_arena.env_eval`` package version
            (:data:`shop_arena.env_eval._version.__version__`).
        browser_navigations: Count of ``page.goto()`` calls made during
            the run.
        started_at: UTC timestamp captured before any pipeline work runs.
        ended_at: UTC timestamp captured after every step has either run
            or been skipped.
        llm_calls: Count of LLM completions issued during the run.
            Defaults to ``0`` for callers that do no LLM work.
        steps: Per-step ``(ran, reused)`` records.  Defaults to empty so
            unit tests that do not exercise the resume layer keep building
            valid manifests.
        browsergym_version: Override for :func:`resolve_browsergym_version`.
            Tests inject a fixed value; production callers leave it ``None``
            and the live package version is recorded.
        rubric_prompt_version: Override for :data:`RUBRIC_PROMPT_VERSION`.
        state_prompt_version: Override for :data:`STATE_PROMPT_VERSION`.
        rule_version: Override for :data:`RULE_VERSION`.
        heuristic_version: Override for :data:`HEURISTIC_VERSION`.
        pages_classifier_version: Override for
            :data:`PAGES_CLASSIFIER_VERSION`.
    """
    snapshot = ConfigSnapshot(
        url=config.url,
        out_dir=str(config.out_dir) if config.out_dir is not None else None,
        viewport=config.viewport,
        max_hops=config.max_hops,
        rubric_model=config.rubric_model,
        pages_classifier_model=config.pages_classifier_model,
        rediscover=config.rediscover,
        shop_name=config.shop_name,
        no_rubric=config.no_rubric,
    )
    return Manifest(
        eval_version=eval_version,
        config=snapshot,
        started_at=started_at,
        ended_at=ended_at,
        browsergym_version=(
            browsergym_version if browsergym_version is not None else resolve_browsergym_version()
        ),
        browser_navigations=browser_navigations,
        llm_calls=llm_calls,
        steps=steps,
        rubric_prompt_version=rubric_prompt_version,
        state_prompt_version=state_prompt_version,
        rule_version=rule_version,
        heuristic_version=heuristic_version,
        pages_classifier_version=pages_classifier_version,
    )


def write_manifest(manifest: Manifest, run_dir: Path | str) -> Path:
    """Serialise ``manifest`` to ``<run_dir>/manifest.json``.

    The ``run_dir`` is created if it does not already exist; output is
    deterministic JSON (two-space indent, trailing newline) so the
    file is byte-stable for fixed inputs.
    """
    target = Path(run_dir) / MANIFEST_JSON_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = manifest.model_dump(mode="json")
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target
