"""Unit tests for :mod:`shop_explore.synthesize` (T3.1).

Covers the deterministic synthesis path with a mocked LLM and the
loud-failure path when the LLM returns an empty / short response. Both
tests build a populated ``run_dir`` from the hand-crafted
``fixture_drawer_shop`` cassette so they exercise the full
capabilities deep-merge + stats compute + manifest assembly without
touching the harness loop.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from shop_explore.synthesize import (
    MANUAL_MIN_CHARS,
    SynthesisError,
    SynthesisResult,
    synthesize,
)

_CASSETTE_DIR = Path(__file__).resolve().parent.parent / "cassettes" / "fixture_drawer_shop"
_FINAL_ITER_DIR = _CASSETTE_DIR / "exec-0004"
_EXPECTED_TASK_IDS: tuple[str, ...] = (
    "homepage_sections",
    "cart_drawer",
    "search_predictive",
    "collection_filters",
)
_MANUAL_PROMPT = "Merge the per-task notes into one anonymized Shop Manual."

_EXPECTED_PRODUCT_COUNT = 2
_EXPECTED_COLLECTION_COUNT = 2
_EXPECTED_PRICE_MIN = 12.0
_EXPECTED_PRICE_MAX = 48.0
_EXPECTED_HOMEPAGE_SECTIONS = 5
_EXPECTED_PLAN_TOTAL = 4
_EXPECTED_PLAN_DONE = 4
_EXPECTED_EXEC_ITERS = 4


# --------------------------------------------------------------------------- #
# Fixture setup
# --------------------------------------------------------------------------- #


def _seed_run_dir(tmp_path: Path) -> Path:
    """Build a populated ``run_dir`` mirroring a finished harness run.

    Lays out:

    * ``<run_dir>/plan.md`` — final cassette plan (all four tasks done).
    * ``<run_dir>/artifact/parts/`` — every fragment from the cassette.
    * ``<run_dir>/artifact/prefetch/`` — minimal Shopify-shaped JSON
      sufficient for stats compute.
    * ``<run_dir>/run.json`` — harness summary echo.
    """
    domain_dir = tmp_path / "example-shop.com"
    run_dir = domain_dir / "20251024T120000Z-deadbeef"
    artifact_dir = run_dir / "artifact"
    parts_dir = artifact_dir / "parts"
    prefetch_dir = artifact_dir / "prefetch"
    parts_dir.mkdir(parents=True)
    prefetch_dir.mkdir(parents=True)

    # Copy parts (md + caps.json) from the four cassette executor iters.
    for task_id, exec_dir in zip(
        _EXPECTED_TASK_IDS,
        ("exec-0001", "exec-0002", "exec-0003", "exec-0004"),
        strict=True,
    ):
        src_parts = _CASSETTE_DIR / exec_dir / "workspace_after" / "artifact" / "parts"
        shutil.copy2(src_parts / f"{task_id}.md", parts_dir / f"{task_id}.md")
        shutil.copy2(src_parts / f"{task_id}.caps.json", parts_dir / f"{task_id}.caps.json")

    # Copy the final plan.md (all tasks `[x]`, one omitted area).
    shutil.copy2(_FINAL_ITER_DIR / "workspace_after" / "plan.md", run_dir / "plan.md")

    # Minimal prefetch shaped as Shopify ajax responses so stats compute.
    (prefetch_dir / "products.json").write_text(
        json.dumps(
            {
                "products": [
                    {
                        "id": 1,
                        "title": "Item A",
                        "options": [{"name": "Size"}, {"name": "Color"}],
                        "variants": [
                            {"id": 11, "price": "12.00"},
                            {"id": 12, "price": "12.00"},
                        ],
                    },
                    {
                        "id": 2,
                        "title": "Item B",
                        "options": [{"name": "Material"}],
                        "variants": [{"id": 21, "price": "48.00"}],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (prefetch_dir / "collections.json").write_text(
        json.dumps(
            {
                "collections": [
                    {"id": 100, "products_count": 8},
                    {"id": 101, "products_count": 2},
                ]
            }
        ),
        encoding="utf-8",
    )
    (prefetch_dir / "cart.js").write_text(
        json.dumps({"items": [], "currency": "USD"}), encoding="utf-8"
    )

    # Harness run.json summary echo (selected fields surfaced in manifest).
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "final_status": "completed",
                "plan_iter_count": 1,
                "exec_iter_count": 4,
                "trajectory_paths": [],
                "tasks_final": [],
                "config_snapshot": {"runtime": "pi"},
                "runtime": "pi",
            }
        ),
        encoding="utf-8",
    )
    return run_dir


class _StubLLM:
    """Minimal :class:`LLMClient` that records the prompt and returns ``response``."""

    def __init__(self, response: str | Callable[[str], str]) -> None:
        self._response = response
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._response(prompt) if callable(self._response) else self._response


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_synthesize_writes_all_published_artifacts_with_llm_response(
    tmp_path: Path,
) -> None:
    """Deterministic path: LLM returns a long manual; all four files written."""
    run_dir = _seed_run_dir(tmp_path)
    manual_body = "# Shop Manual\n\n" + ("Structured prose. " * 40)
    assert len(manual_body.strip()) >= MANUAL_MIN_CHARS  # sanity-check fixture
    llm = _StubLLM(manual_body)

    result = synthesize(run_dir, llm=llm, manual_prompt=_MANUAL_PROMPT)

    # SynthesisResult points at the four §5.10 artifacts.
    assert isinstance(result, SynthesisResult)
    artifact = run_dir / "artifact"
    assert result.manual_path == artifact / "manual.md"
    assert result.capabilities_path == artifact / "capabilities.json"
    assert result.stats_path == artifact / "stats.json"
    assert result.manifest_path == artifact / "manifest.json"
    assert result.capability_conflicts == ()

    # manual.md contains the LLM body verbatim (with trailing newline).
    assert result.manual_path.read_text(encoding="utf-8").startswith(manual_body)

    # capabilities.json parses as a closed §5.5 document with all four
    # fragments merged (drawer cart, predictive search, mega menu, …).
    caps = json.loads(result.capabilities_path.read_text(encoding="utf-8"))
    assert caps["cart"]["type"] == "drawer"
    assert caps["search"]["has_predictive"] is True
    assert caps["site_shell"]["has_mega_menu"] is True
    assert caps["collection"]["filters"] == ["size", "color", "price"]
    assert caps["homepage"]["section_count"] == _EXPECTED_HOMEPAGE_SECTIONS

    # stats.json reflects the seeded prefetch fixture.
    stats = json.loads(result.stats_path.read_text(encoding="utf-8"))
    assert stats["products_total"] == _EXPECTED_PRODUCT_COUNT
    assert "products_truncated" not in stats  # T6.4 dropped the truncation flag
    assert stats["collections_total"] == _EXPECTED_COLLECTION_COUNT
    assert stats["price"]["currency"] == "USD"
    assert stats["price"]["min"] == _EXPECTED_PRICE_MIN
    assert stats["price"]["max"] == _EXPECTED_PRICE_MAX
    assert sorted(stats["variant_axes_observed"]) == ["color", "material", "size"]

    # manifest.json mirrors the harness run summary + plan tallies.
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert "manual_fallback" not in manifest  # fallback removed in M3 — failures are loud
    assert manifest["harness_status"] == "completed"
    assert manifest["runtime"] == "pi"
    assert manifest["iters"] == {"plan": 1, "exec": _EXPECTED_EXEC_ITERS}
    assert manifest["plan_tasks_total"] == _EXPECTED_PLAN_TOTAL
    assert manifest["plan_tasks_done"] == _EXPECTED_PLAN_DONE
    assert manifest["plan_tasks_blocked"] == 0
    assert manifest["capability_conflicts"] == []
    assert manifest["domain"] == "example-shop.com"
    assert manifest["run_id"] == run_dir.name
    assert manifest["omitted_areas"] == [
        {
            "area": "age_gate",
            "reason": "prefetch shows no overlay markup; storefront is not age-restricted.",
        }
    ]
    assert manifest["paths"]["manual"] == "artifact/manual.md"

    # Single LLM call; prompt carries the merge prompt, capabilities,
    # and concatenated parts.
    assert len(llm.calls) == 1
    sent = llm.calls[0]
    assert _MANUAL_PROMPT in sent
    assert "## Capabilities" in sent
    assert "## Per-task parts" in sent
    for task_id in _EXPECTED_TASK_IDS:
        assert f"# {task_id}" in sent


def test_synthesize_raises_when_llm_response_is_empty(tmp_path: Path) -> None:
    """Empty LLM response → :class:`SynthesisError`; no ``manual.md`` written.

    Earlier revisions silently fell back to a deterministic concatenation of
    ``parts/*.md`` (``manifest.manual_fallback=true``). That path masked
    LLM-client misconfiguration and was removed in M3 — failures are now
    loud.
    """
    run_dir = _seed_run_dir(tmp_path)
    llm = _StubLLM("")

    with pytest.raises(SynthesisError, match="manual render failed"):
        synthesize(run_dir, llm=llm, manual_prompt=_MANUAL_PROMPT)

    assert not (run_dir / "artifact" / "manual.md").exists()
    assert not (run_dir / "artifact" / "manifest.json").exists()


def test_synthesize_raises_when_llm_complete_raises(tmp_path: Path) -> None:
    """Wire-level ``complete`` failure → :class:`SynthesisError` (no silent fallback)."""
    run_dir = _seed_run_dir(tmp_path)

    class _BoomLLM:
        def complete(self, prompt: str) -> str:
            raise RuntimeError("boom: api unavailable")

    with pytest.raises(SynthesisError, match="manual render failed: boom"):
        synthesize(run_dir, llm=_BoomLLM(), manual_prompt=_MANUAL_PROMPT)

    assert not (run_dir / "artifact" / "manual.md").exists()


def test_synthesize_raises_when_artifact_layout_missing(tmp_path: Path) -> None:
    """Missing ``parts/`` raises :class:`SynthesisError` (no partial outputs)."""
    run_dir = tmp_path / "domain" / "run"
    (run_dir / "artifact").mkdir(parents=True)
    (run_dir / "artifact" / "prefetch").mkdir()

    with pytest.raises(SynthesisError, match="missing parts dir"):
        synthesize(run_dir, llm=_StubLLM("ignored"), manual_prompt=_MANUAL_PROMPT)
