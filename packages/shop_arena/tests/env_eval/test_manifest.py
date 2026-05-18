"""Unit tests for :mod:`shop_arena.env_eval.schema.manifest` (impl-plan M1).

Covers the M1 skeleton:

* ``ConfigSnapshot`` mirrors ``EvalConfig`` (closed schema, frozen).
* ``Manifest`` holds the snapshot + ``browser_navigations`` /
  ``llm_calls`` counters under a closed schema.
* :func:`build_manifest` populates the snapshot from an ``EvalConfig``.
* :func:`write_manifest` serialises deterministic JSON to
  ``<run_dir>/manifest.json`` and round-trips back through
  :meth:`Manifest.model_validate`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from shop_arena.env_eval import _version as _ev_version
from shop_arena.env_eval.action import HEURISTIC_VERSION
from shop_arena.env_eval.config import EvalConfig
from shop_arena.env_eval.observation.rubric import RUBRIC_PROMPT_VERSION
from shop_arena.env_eval.schema.manifest import (
    MANIFEST_JSON_FILENAME,
    MANIFEST_VERSION,
    ConfigSnapshot,
    Manifest,
    StepRecord,
    build_manifest,
    resolve_browsergym_version,
    write_manifest,
)
from shop_arena.env_eval.transition.pages_classifier import (
    DEFAULT_PAGES_CLASSIFIER_MODEL,
    PAGES_CLASSIFIER_VERSION,
)
from shop_arena.env_eval.transition.rules import RULE_VERSION
from shop_arena.env_eval.transition.stateful import STATE_PROMPT_VERSION

_T0 = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
_T1 = _T0 + timedelta(seconds=42)


def _sample_config(out_dir: Path | None = None) -> EvalConfig:
    return EvalConfig(
        url="https://example-shop.com/",
        out_dir=out_dir,
        viewport=(1280, 720),
        max_hops=2,
        rubric_model="claude-sonnet-4-6",
        rediscover=True,
        shop_name="example",
        no_rubric=True,
    )


def test_manifest_version_constant_is_zero_one() -> None:
    """Schema version is pinned to ``"0.1"`` for the v0.1 release."""
    assert MANIFEST_VERSION == "0.1"


def test_manifest_default_filename_matches_spec() -> None:
    """Spec §5.6 fixes the manifest filename as ``manifest.json``."""
    assert MANIFEST_JSON_FILENAME == "manifest.json"


def test_build_manifest_snapshots_eval_config(tmp_path: Path) -> None:
    """``build_manifest`` mirrors every ``EvalConfig`` field into the snapshot."""
    out_dir = tmp_path / "run"
    config = _sample_config(out_dir=out_dir)

    manifest = build_manifest(
        config,
        eval_version=_ev_version.__version__,
        browser_navigations=5,
        llm_calls=0,
        started_at=_T0,
        ended_at=_T1,
    )

    assert manifest.manifest_version == MANIFEST_VERSION
    assert manifest.eval_version == _ev_version.__version__
    assert manifest.browser_navigations == 5
    assert manifest.llm_calls == 0
    snap = manifest.config
    assert snap.url == "https://example-shop.com/"
    assert snap.out_dir == str(out_dir)
    assert snap.viewport == (1280, 720)
    assert snap.max_hops == 2
    assert snap.rubric_model == "claude-sonnet-4-6"
    assert snap.pages_classifier_model == DEFAULT_PAGES_CLASSIFIER_MODEL
    assert snap.rediscover is True
    assert snap.shop_name == "example"
    assert snap.no_rubric is True


def test_build_manifest_records_none_out_dir_as_null() -> None:
    """An unset ``out_dir`` round-trips as JSON ``null``, not ``"None"``."""
    config = EvalConfig(url="https://shop.test/")

    manifest = build_manifest(
        config,
        eval_version=_ev_version.__version__,
        browser_navigations=1,
        started_at=_T0,
        ended_at=_T1,
    )

    assert manifest.config.out_dir is None
    payload = manifest.model_dump(mode="json")
    assert payload["config"]["out_dir"] is None


def test_build_manifest_default_llm_calls_is_zero() -> None:
    """M1 makes no LLM calls; ``llm_calls`` defaults to ``0``."""
    config = EvalConfig(url="https://shop.test/")

    manifest = build_manifest(
        config,
        eval_version=_ev_version.__version__,
        browser_navigations=0,
        started_at=_T0,
        ended_at=_T1,
    )

    assert manifest.llm_calls == 0


def test_write_manifest_emits_deterministic_json(tmp_path: Path) -> None:
    """Output is two-space indented JSON with a trailing newline."""
    config = _sample_config()
    manifest = build_manifest(
        config,
        eval_version=_ev_version.__version__,
        browser_navigations=3,
        started_at=_T0,
        ended_at=_T1,
    )

    target = write_manifest(manifest, tmp_path)

    assert target == tmp_path / MANIFEST_JSON_FILENAME
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    payload = json.loads(text)
    # Pretty-print check: two-space indent introduces "  \"" on inner lines.
    assert '  "manifest_version": "0.1",' in text
    # Round-trip back through the model so closed-schema discipline holds.
    assert Manifest.model_validate(payload) == manifest


def test_write_manifest_creates_missing_run_dir(tmp_path: Path) -> None:
    """The target directory is created if it does not yet exist."""
    config = _sample_config()
    manifest = build_manifest(
        config,
        eval_version=_ev_version.__version__,
        browser_navigations=0,
        started_at=_T0,
        ended_at=_T1,
    )
    nested = tmp_path / "nested" / "run"

    target = write_manifest(manifest, nested)

    assert target.is_file()
    assert target.parent == nested


def test_manifest_rejects_unknown_keys() -> None:
    """``extra="forbid"`` keeps the closed schema honest."""
    payload = {
        "manifest_version": "0.1",
        "eval_version": _ev_version.__version__,
        "config": {
            "url": "https://shop.test/",
            "viewport": [1440, 900],
            "max_hops": 3,
            "rubric_model": "claude-sonnet-4-6",
            "rediscover": False,
            "no_rubric": False,
        },
        "browser_navigations": 0,
        "llm_calls": 0,
        "unexpected": "field",
    }

    with pytest.raises(ValidationError):
        Manifest.model_validate(payload)


def test_config_snapshot_rejects_unknown_keys() -> None:
    """The nested snapshot is also closed."""
    payload = {
        "url": "https://shop.test/",
        "viewport": [1440, 900],
        "max_hops": 3,
        "rubric_model": "claude-sonnet-4-6",
        "rediscover": False,
        "no_rubric": False,
        "stray": "value",
    }

    with pytest.raises(ValidationError):
        ConfigSnapshot.model_validate(payload)


def test_manifest_rejects_negative_counts() -> None:
    """Counters are non-negative."""
    config = _sample_config()
    snapshot = ConfigSnapshot(
        url=config.url,
        viewport=config.viewport,
        max_hops=config.max_hops,
        rubric_model=config.rubric_model,
        pages_classifier_model=config.pages_classifier_model,
        rediscover=config.rediscover,
        no_rubric=config.no_rubric,
    )
    common: dict[str, object] = {
        "eval_version": _ev_version.__version__,
        "config": snapshot,
        "started_at": _T0,
        "ended_at": _T1,
        "browsergym_version": "0.14.3",
        "rubric_prompt_version": RUBRIC_PROMPT_VERSION,
        "state_prompt_version": STATE_PROMPT_VERSION,
        "rule_version": RULE_VERSION,
        "heuristic_version": HEURISTIC_VERSION,
        "pages_classifier_version": PAGES_CLASSIFIER_VERSION,
    }

    with pytest.raises(ValidationError):
        Manifest(**common, browser_navigations=-1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Manifest(**common, browser_navigations=0, llm_calls=-2)  # type: ignore[arg-type]


def test_step_record_rejects_both_true() -> None:
    """``ran`` and ``reused`` must be mutually exclusive (both True is invalid)."""
    with pytest.raises(ValidationError):
        StepRecord(name="pages", ran=True, reused=True)


def test_step_record_rejects_both_false() -> None:
    """``ran`` and ``reused`` must be mutually exclusive (both False is invalid)."""
    with pytest.raises(ValidationError):
        StepRecord(name="pages", ran=False, reused=False)


def test_step_record_rejects_unknown_step_name() -> None:
    """``name`` is constrained to the closed :data:`resume.STEPS` literal."""
    with pytest.raises(ValidationError):
        StepRecord(name="not-a-step", ran=True, reused=False)  # type: ignore[arg-type]


def test_build_manifest_accepts_steps_tuple() -> None:
    """:func:`build_manifest` records the per-step ``(ran, reused)`` table."""
    config = _sample_config()
    steps = (
        StepRecord(name="pages", ran=False, reused=True),
        StepRecord(name="observation", ran=True, reused=False),
        StepRecord(name="action", ran=True, reused=False),
        StepRecord(name="transition", ran=True, reused=False),
        StepRecord(name="metrics", ran=True, reused=False),
    )

    manifest = build_manifest(
        config,
        eval_version=_ev_version.__version__,
        browser_navigations=4,
        steps=steps,
        started_at=_T0,
        ended_at=_T1,
    )

    assert manifest.steps == steps
    payload = manifest.model_dump(mode="json")
    assert [entry["name"] for entry in payload["steps"]] == [
        "pages",
        "observation",
        "action",
        "transition",
        "metrics",
    ]


def test_manifest_steps_default_is_empty_tuple() -> None:
    """Legacy callers that omit ``steps`` produce an empty tuple, not ``None``."""
    config = _sample_config()
    manifest = build_manifest(
        config,
        eval_version=_ev_version.__version__,
        browser_navigations=0,
        started_at=_T0,
        ended_at=_T1,
    )
    assert manifest.steps == ()


def test_build_manifest_records_version_pins_by_default() -> None:
    """M6: rubric/state prompt + rule + heuristic versions are recorded."""
    config = _sample_config()

    manifest = build_manifest(
        config,
        eval_version=_ev_version.__version__,
        browser_navigations=0,
        started_at=_T0,
        ended_at=_T1,
        browsergym_version="0.14.3",
    )

    assert manifest.rubric_prompt_version == RUBRIC_PROMPT_VERSION
    assert manifest.state_prompt_version == STATE_PROMPT_VERSION
    assert manifest.rule_version == RULE_VERSION
    assert manifest.heuristic_version == HEURISTIC_VERSION
    assert manifest.pages_classifier_version == PAGES_CLASSIFIER_VERSION
    assert manifest.browsergym_version == "0.14.3"
    assert manifest.started_at == _T0
    assert manifest.ended_at == _T1


def test_build_manifest_records_pages_classifier_model_override() -> None:
    """Custom ``pages_classifier_model`` round-trips through the snapshot."""
    config = EvalConfig(
        url="https://shop.test/",
        pages_classifier_model="gpt-5-nano",
    )

    manifest = build_manifest(
        config,
        eval_version=_ev_version.__version__,
        browser_navigations=0,
        started_at=_T0,
        ended_at=_T1,
    )

    assert manifest.config.pages_classifier_model == "gpt-5-nano"
    payload = manifest.model_dump(mode="json")
    assert payload["config"]["pages_classifier_model"] == "gpt-5-nano"


def test_build_manifest_resolves_browsergym_version_when_unset() -> None:
    """Omitting ``browsergym_version`` resolves it from package metadata."""
    config = _sample_config()

    manifest = build_manifest(
        config,
        eval_version=_ev_version.__version__,
        browser_navigations=0,
        started_at=_T0,
        ended_at=_T1,
    )

    # browsergym is a real dep of shop_arena — metadata must resolve.
    assert manifest.browsergym_version == resolve_browsergym_version()
    assert manifest.browsergym_version != ""


def test_manifest_rejects_ended_before_started() -> None:
    """``ended_at < started_at`` is invalid (clock skew is not silently tolerated)."""
    config = _sample_config()

    with pytest.raises(ValidationError):
        build_manifest(
            config,
            eval_version=_ev_version.__version__,
            browser_navigations=0,
            started_at=_T1,
            ended_at=_T0,
        )


def test_manifest_payload_contains_full_field_set() -> None:
    """The serialised payload includes every spec §5.7 field."""
    config = _sample_config()
    manifest = build_manifest(
        config,
        eval_version=_ev_version.__version__,
        browser_navigations=2,
        started_at=_T0,
        ended_at=_T1,
        browsergym_version="0.14.3",
    )

    payload = manifest.model_dump(mode="json")
    assert set(payload) == {
        "manifest_version",
        "eval_version",
        "config",
        "started_at",
        "ended_at",
        "browsergym_version",
        "browser_navigations",
        "llm_calls",
        "steps",
        "rubric_prompt_version",
        "state_prompt_version",
        "rule_version",
        "heuristic_version",
        "pages_classifier_version",
    }
    assert payload["started_at"].startswith("2026-05-03T12:00:00")
    assert payload["ended_at"].startswith("2026-05-03T12:00:42")
