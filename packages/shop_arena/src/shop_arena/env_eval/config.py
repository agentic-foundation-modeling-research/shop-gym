"""``EvalConfig`` and ``EvalResult`` pydantic v2 models.

These are the user-facing types referenced from spec §4.1 ("I/O contract")
and §5.9 ("CLI surface"). They are imported into the package public
surface (``shop_arena.env_eval.evaluate`` accepts an ``EvalConfig`` and
returns an ``EvalResult``).

Both models are **frozen** and **closed**: spec §5.8 makes the closed-schema
guarantee about ``metrics.json`` itself, but the same discipline is applied
here so that drift in the input/output contract is loud (unknown CLI flags
or library kwargs raise instead of being silently ignored).

Defaults match spec §4.1:

* ``viewport`` — ``(1440, 900)``
* ``max_hops`` — ``3``
* ``rubric_model`` — ``"claude-sonnet-4-6"``
* ``rediscover`` — ``False``

``shop_name``, ``out_dir``, and ``no_rubric`` default to ``None`` / ``False``;
the pipeline (M1) is responsible for deriving the run directory from
``shop_name`` (or hostname, per impl-plan M0 decisions) when ``out_dir``
is not set, and for honouring ``no_rubric`` in the observation layer.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from shop_arena.env_eval.transition.pages_classifier import DEFAULT_PAGES_CLASSIFIER_MODEL

__all__ = [
    "DEFAULT_MAX_HOPS",
    "DEFAULT_PAGES_CLASSIFIER_MODEL",
    "DEFAULT_RUBRIC_MODEL",
    "DEFAULT_VIEWPORT",
    "EvalConfig",
    "EvalResult",
]

#: Default desktop viewport, spec §4.1. Kept as a module-level constant so
#: the CLI and tests share the same source of truth.
DEFAULT_VIEWPORT: tuple[int, int] = (1440, 900)

#: Default BFS depth for the transition layer, spec §4.1 / §5.5.
DEFAULT_MAX_HOPS: int = 3

#: Default LLM model for the screenshot rubric, impl-plan M0 decision /
#: spec §5.3 ("default `claude-sonnet-4-6`").
DEFAULT_RUBRIC_MODEL: str = "claude-sonnet-4-6"


class EvalConfig(BaseModel):
    """Configuration for one ``evaluate()`` call.

    Mirrors the CLI flags in spec §5.9 ``shop-env-eval run``. The library
    entrypoint accepts this object directly so callers do not need to go
    through the CLI.

    Attributes:
        url: Public storefront base URL (required). Normalisation
            (scheme + host + trailing slash) is performed by the page
            discovery layer (M1), not here.
        out_dir: Optional pre-computed run directory. When ``None``, the
            pipeline picks
            ``outputs/shop_env_evals/<shop_name>/<run_id>/`` per spec
            §5.6. An existing directory is treated as a resumable run.
        viewport: ``(width, height)`` desktop viewport. v0.1 only
            supports a single viewport.
        max_hops: BFS depth for the transition graph. Must be ``>= 0``;
            ``0`` disables the BFS pass.
        rubric_model: Model id for the screenshot rubric (spec §5.3).
            Provider is selected by prefix at call time
            (impl-plan M0 decision).
        pages_classifier_model: Model id used by the
            ``/pages/<slug>`` classifier
            (:mod:`shop_arena.env_eval.transition.pages_classifier`).
            Provider is selected by prefix at call time, mirroring
            ``rubric_model``. Defaults to
            :data:`DEFAULT_PAGES_CLASSIFIER_MODEL`.
        rediscover: When ``True``, ignore an existing ``pages.json`` and
            select pages again (spec §5.2 / §5.7).
        shop_name: Override for the ``<shop_name>`` directory segment.
            When ``None``, the pipeline derives it from the URL hostname
            (impl-plan M0 decision).
        no_rubric: When ``True``, write a stub rubric artifact and skip
            all observation-layer LLM calls (spec §5.3, impl-plan M1).
            Also stubs the ``/pages/`` classifier (every discovered slug
            is recorded as ``"unknown"`` and no path is collapsed) — the
            classifier shares the rubric's "no live LLM" budget so a
            single flag suffices.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(min_length=1)
    out_dir: Path | None = None
    viewport: tuple[int, int] = DEFAULT_VIEWPORT
    max_hops: int = Field(default=DEFAULT_MAX_HOPS, ge=0)
    rubric_model: str = Field(default=DEFAULT_RUBRIC_MODEL, min_length=1)
    pages_classifier_model: str = Field(
        default=DEFAULT_PAGES_CLASSIFIER_MODEL,
        min_length=1,
    )
    rediscover: bool = False
    shop_name: str | None = None
    no_rubric: bool = False


class EvalResult(BaseModel):
    """Return value of ``evaluate()``.

    Holds filesystem locators only; the parsed ``metrics.json`` document
    is exposed as a separate field once the ``Metrics`` schema lands
    (next M1 task). Keeping this model frozen + closed mirrors
    ``EvalConfig`` and lets callers safely use it as a dict key.

    Attributes:
        run_dir: Absolute path to the per-shop run directory containing
            ``pages.json``, ``observation/``, ``action/``, ``transition/``,
            ``metrics.json``, and ``manifest.json`` (spec §5.6).
        metrics_path: Absolute path to ``metrics.json`` inside
            ``run_dir``. This is the file ``compare`` and ``aggregate``
            consume; the CLI prints it on stdout per spec SC1.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_dir: Path
    metrics_path: Path
