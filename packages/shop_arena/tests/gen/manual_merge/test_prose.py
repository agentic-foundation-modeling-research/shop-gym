"""Unit tests for :mod:`shop_arena.gen.manual_merge.prose`.

Covers the T2.2 requirements from
``docs/impl/shop_gen_implementation.md``:

* Section-by-section LLM merge of seed ``manual.md`` files conditioned
  on the merged capabilities document.
* Stub :class:`~harness.runtimes.LLMCompleter` exercises the merge so
  the test stays hermetic — no API keys, no live model calls.
* The merged manual surfaces the canonical section count and only the
  fake-brand allowlist's tokens leak into the prose (spec §5.6).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from harness.runtimes import LLMCompleter
from shop_arena.explore.capabilities import Capabilities
from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.manual_merge.prose import (
    MergeManualProseStep,
    merge_manual_prose_seeds,
)
from shop_arena.gen.steps.base import FileInput, Step, StepContext, StepInput

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


@dataclass
class _StubCompleter:
    """Recording :class:`LLMCompleter` that returns canned responses.

    Each call dequeues one response from ``responses``; an empty queue
    raises so tests fail loudly when the merge calls the LLM more
    times than expected.
    """

    responses: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)

    def complete(self, prompt: str, *, timeout: float) -> str:
        del timeout
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("LLM was called more times than expected")
        return self.responses.pop(0)


def _write_manual(seed_dir: Path, body: str) -> Path:
    """Write ``manual.md`` under the canonical seed layout."""
    artifact = seed_dir / "artifact"
    artifact.mkdir(parents=True, exist_ok=True)
    path = artifact / "manual.md"
    path.write_text(body, encoding="utf-8")
    return path


def _seed_manual(descriptor: str, *, sections: dict[str, str]) -> str:
    """Render a manual body with H1 + named H2 sections."""
    pieces = [f"# Shop Manual — {descriptor}", ""]
    for name, body in sections.items():
        pieces.append(f"## {name}")
        pieces.append("")
        pieces.append(body.rstrip())
        pieces.append("")
    return "\n".join(pieces).rstrip() + "\n"


def _merged_capabilities(*, descriptor: str = "Premium Storefront") -> dict[str, object]:
    """Return a minimal merged-capabilities dict, schema-valid."""
    payload: dict[str, object] = {
        "version": "0.1",
        "shop": {
            "descriptor": descriptor,
            "category": "fashion",
            "currency": "USD",
            "tone": ["clean"],
        },
        "site_shell": {"nav_depth": 1},
        "homepage": {"section_types": [], "section_count": 0},
        "collection": {"filters": [], "sort": []},
        "product": {"variant_selectors": []},
        "search": {"predictive_types": []},
        "info_pages_present": [],
    }
    # Sanity check: the helper produces a schema-valid document.
    Capabilities.model_validate(payload)
    return payload


def _h2_section_names(body: str) -> list[str]:
    """Return every ``## <name>`` heading in ``body`` in document order."""
    return [match.group(1).strip() for match in re.finditer(r"^##\s+(.+)$", body, re.MULTILINE)]


# A small, *not* exhaustive denylist of real brand names. Used only as a
# negative-evidence smoke test for the brand-leak rule (spec §5.6); the
# full allowlist scanner lands in T3.1 and is out of scope here.
_REAL_BRAND_DENYLIST: tuple[str, ...] = (
    "Apple",
    "Nike",
    "Adidas",
    "Levi",
    "HexClad",
    "Lululemon",
    "Patagonia",
    "Tesla",
    "Amazon",
)


def _assert_no_real_brand_leaks(body: str) -> None:
    """Assert ``body`` does not mention any real-brand denylist token."""
    for token in _REAL_BRAND_DENYLIST:
        assert token not in body, f"real brand {token!r} leaked into merged manual"


# --------------------------------------------------------------------------- #
# merge_manual_prose_seeds — core merge logic
# --------------------------------------------------------------------------- #


def test_single_seed_passthrough_uses_no_llm(tmp_path: Path) -> None:
    """A 1-seed merge copies every section verbatim — no LLM call needed."""
    manual = _write_manual(
        tmp_path / "a",
        _seed_manual(
            "Premium Storefront",
            sections={
                "Overview": "A focused, brand-anonymized storefront.",
                "Site shell": "Sticky header, mega menu disabled.",
                "Cart": "Right-side drawer with promo input.",
            },
        ),
    )
    completer = _StubCompleter(responses=[])

    body = merge_manual_prose_seeds(
        [manual],
        merged_capabilities=_merged_capabilities(),
        completer=completer,
    )

    assert body.startswith("# Shop Manual — Premium Storefront\n")
    assert _h2_section_names(body) == ["Overview", "Site shell", "Cart"]
    assert completer.prompts == []
    _assert_no_real_brand_leaks(body)


def test_multi_seed_merge_calls_llm_per_overlapping_section(tmp_path: Path) -> None:
    """Sections contributed by 2+ seeds each get one LLM call; singletons are copied."""
    seed_a = _write_manual(
        tmp_path / "a",
        _seed_manual(
            "Premium Storefront",
            sections={
                "Overview": "Seed A overview.",
                "Site shell": "Seed A site shell.",
                "Cart": "Seed A cart drawer.",
            },
        ),
    )
    seed_b = _write_manual(
        tmp_path / "b",
        _seed_manual(
            "Premium Storefront",
            sections={
                "Overview": "Seed B overview.",
                "Site shell": "Seed B site shell.",
                "Search": "Seed B search modal.",
            },
        ),
    )
    completer = _StubCompleter(
        responses=[
            "Merged overview prose.",
            "Merged site shell prose.",
        ]
    )

    body = merge_manual_prose_seeds(
        [seed_a, seed_b],
        merged_capabilities=_merged_capabilities(),
        completer=completer,
    )

    # Two overlapping sections (Overview, Site shell) → two LLM calls.
    assert len(completer.prompts) == 2  # noqa: PLR2004 - matches the two overlapping sections
    # Canonical order: Overview, Site shell, Cart, Search (Floating UX etc. absent).
    assert _h2_section_names(body) == ["Overview", "Site shell", "Cart", "Search"]
    assert "Merged overview prose." in body
    assert "Merged site shell prose." in body
    # Singletons copied verbatim.
    assert "Seed A cart drawer." in body
    assert "Seed B search modal." in body
    _assert_no_real_brand_leaks(body)


def test_canonical_section_order_with_extras_appended(tmp_path: Path) -> None:
    """Canonical sections come first; unknown sections append in first-seen order."""
    seed_a = _write_manual(
        tmp_path / "a",
        _seed_manual(
            "Premium Storefront",
            sections={
                # Out-of-order on purpose — the merger should re-canonicalize.
                "Cart": "Seed A cart.",
                "Overview": "Seed A overview.",
                "Loyalty Programs": "Seed A loyalty.",  # extra, non-canonical
            },
        ),
    )
    seed_b = _write_manual(
        tmp_path / "b",
        _seed_manual(
            "Premium Storefront",
            sections={
                "Site shell": "Seed B shell.",
                "Subscriptions": "Seed B subs.",  # extra, non-canonical
            },
        ),
    )
    completer = _StubCompleter(responses=[])  # no overlapping canonical sections

    body = merge_manual_prose_seeds(
        [seed_a, seed_b],
        merged_capabilities=_merged_capabilities(),
        completer=completer,
    )

    names = _h2_section_names(body)
    # Canonical first (Overview, Site shell, Cart) in canonical order;
    # extras appended in first-seen seed order.
    assert names == [
        "Overview",
        "Site shell",
        "Cart",
        "Loyalty Programs",
        "Subscriptions",
    ]
    assert completer.prompts == []


def test_merge_uses_capabilities_descriptor_for_h1(tmp_path: Path) -> None:
    """The H1 line is taken from ``shop.descriptor``, not the seed H1s."""
    seed = _write_manual(
        tmp_path / "a",
        _seed_manual(
            "Wrong Descriptor",
            sections={"Overview": "Body."},
        ),
    )
    body = merge_manual_prose_seeds(
        [seed],
        merged_capabilities=_merged_capabilities(descriptor="Boutique Outdoor Shop"),
        completer=None,
    )
    first_line = body.splitlines()[0]
    assert first_line == "# Shop Manual — Boutique Outdoor Shop"


def test_descriptor_fallback_when_capability_blank(tmp_path: Path) -> None:
    """Empty / missing ``shop.descriptor`` falls back to the generic descriptor."""
    seed = _write_manual(
        tmp_path / "a",
        _seed_manual("X", sections={"Overview": "Body."}),
    )
    body = merge_manual_prose_seeds(
        [seed],
        merged_capabilities={"shop": {"descriptor": "  "}},
        completer=None,
    )
    assert body.splitlines()[0] == "# Shop Manual — Generic Storefront"


def test_multi_seed_overlap_without_completer_raises(tmp_path: Path) -> None:
    """Multi-seed sections require an LLM completer."""
    seed_a = _write_manual(
        tmp_path / "a",
        _seed_manual("X", sections={"Overview": "A."}),
    )
    seed_b = _write_manual(
        tmp_path / "b",
        _seed_manual("X", sections={"Overview": "B."}),
    )
    with pytest.raises(ValueError, match="LLMCompleter"):
        merge_manual_prose_seeds(
            [seed_a, seed_b],
            merged_capabilities=_merged_capabilities(),
            completer=None,
        )


def test_empty_llm_response_raises(tmp_path: Path) -> None:
    """An empty model response is treated as a hard error, not a silent gap."""
    seed_a = _write_manual(
        tmp_path / "a",
        _seed_manual("X", sections={"Overview": "A."}),
    )
    seed_b = _write_manual(
        tmp_path / "b",
        _seed_manual("X", sections={"Overview": "B."}),
    )
    completer = _StubCompleter(responses=["   \n"])
    with pytest.raises(ValueError, match="empty body"):
        merge_manual_prose_seeds(
            [seed_a, seed_b],
            merged_capabilities=_merged_capabilities(),
            completer=completer,
        )


def test_missing_seed_path_raises(tmp_path: Path) -> None:
    """A non-existent seed path raises immediately."""
    with pytest.raises(FileNotFoundError, match="seed manual file"):
        merge_manual_prose_seeds(
            [tmp_path / "missing.md"],
            merged_capabilities=_merged_capabilities(),
            completer=None,
        )


def test_empty_seed_paths_rejected() -> None:
    """No seeds → no merge."""
    with pytest.raises(ValueError, match="at least one path"):
        merge_manual_prose_seeds(
            [],
            merged_capabilities=_merged_capabilities(),
            completer=None,
        )


def test_prompt_embeds_capabilities_and_seed_blocks(tmp_path: Path) -> None:
    """Per-section prompt must carry the merged capabilities + every seed body.

    The merged capabilities are the prompt's ground-truth context (spec
    §5.2); the seeds are the qualitative source. Both must be present
    verbatim so the LLM can reconcile contradictions.
    """
    seed_a = _write_manual(
        tmp_path / "a",
        _seed_manual("X", sections={"Overview": "Body A unique-token-aaa."}),
    )
    seed_b = _write_manual(
        tmp_path / "b",
        _seed_manual("X", sections={"Overview": "Body B unique-token-bbb."}),
    )
    completer = _StubCompleter(responses=["Merged."])
    merge_manual_prose_seeds(
        [seed_a, seed_b],
        merged_capabilities=_merged_capabilities(descriptor="Marker-Storefront"),
        completer=completer,
    )

    [prompt] = completer.prompts
    assert "## Merged capabilities" in prompt
    assert "Marker-Storefront" in prompt
    assert "unique-token-aaa" in prompt
    assert "unique-token-bbb" in prompt
    assert "## {section}" not in prompt  # template was rendered, not raw


# --------------------------------------------------------------------------- #
# T2.2 acceptance check — section count + brand allowlist
# --------------------------------------------------------------------------- #


def test_merged_manual_section_count_and_no_real_brand_leaks(tmp_path: Path) -> None:
    """T2.2 acceptance: section count matches inputs; no real brand leaks.

    With 3 canonical sections covered by both seeds, the merged manual
    surfaces exactly 3 H2s. The stub LLM is the only source of section
    bodies for overlapping sections, and it returns brand-free prose;
    every other section is copied verbatim from seeds whose bodies are
    likewise brand-free. The denylist scan is a smoke test for the
    spec §5.6 ``no real-brand mentions`` rule (the full allowlist
    scanner lands in T3.1).
    """
    sections = ["Overview", "Site shell", "Homepage"]
    seed_a = _write_manual(
        tmp_path / "a",
        _seed_manual(
            "Premium Storefront",
            sections={s: f"Seed A — {s} body." for s in sections},
        ),
    )
    seed_b = _write_manual(
        tmp_path / "b",
        _seed_manual(
            "Premium Storefront",
            sections={s: f"Seed B — {s} body." for s in sections},
        ),
    )
    completer = _StubCompleter(
        responses=[f"Merged {s.lower()} body, brand-anonymized." for s in sections]
    )

    body = merge_manual_prose_seeds(
        [seed_a, seed_b],
        merged_capabilities=_merged_capabilities(),
        completer=completer,
    )

    assert _h2_section_names(body) == sections
    assert len(_h2_section_names(body)) == len(sections)
    _assert_no_real_brand_leaks(body)


# --------------------------------------------------------------------------- #
# MergeManualProseStep — IO contract
# --------------------------------------------------------------------------- #


def test_step_metadata_matches_spec(tmp_path: Path) -> None:
    """Step contract surfaces the spec §5.7.1 attributes correctly."""
    seed_a = _write_manual(tmp_path / "a", _seed_manual("X", sections={"Overview": "A."}))
    seed_b = _write_manual(tmp_path / "b", _seed_manual("X", sections={"Overview": "B."}))
    step = MergeManualProseStep(seed_manual_paths=[seed_a, seed_b])

    assert isinstance(step, Step)
    assert step.id == "merge_manual_prose"
    assert step.phase == "manual_merge"
    assert step.depends_on == ["merge_capabilities"]
    assert step.outputs == [Path("manual") / "manual.md"]
    file_inputs = [ref for ref in step.inputs if isinstance(ref, FileInput)]
    step_inputs = [ref for ref in step.inputs if isinstance(ref, StepInput)]
    assert [ref.path for ref in file_inputs] == [seed_a, seed_b]
    assert [ref.step_id for ref in step_inputs] == ["merge_capabilities"]


def test_step_run_writes_manual_md_under_out_dir(tmp_path: Path) -> None:
    """End-to-end: step reads merged caps from disk and writes ``manual/manual.md``."""
    seed_a_dir = tmp_path / "seed_a"
    seed_b_dir = tmp_path / "seed_b"
    seed_a = _write_manual(
        seed_a_dir,
        _seed_manual(
            "Premium Storefront",
            sections={"Overview": "Seed A overview."},
        ),
    )
    seed_b = _write_manual(
        seed_b_dir,
        _seed_manual(
            "Premium Storefront",
            sections={"Overview": "Seed B overview."},
        ),
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # The runtime contract: ``merge_capabilities`` writes the merged
    # capabilities before the prose step runs. We pre-populate the file
    # here to exercise the step in isolation.
    caps_path = out_dir / "manual" / "capabilities.json"
    caps_path.parent.mkdir(parents=True, exist_ok=True)
    caps_path.write_text(json.dumps(_merged_capabilities()), encoding="utf-8")

    cfg = ShopGenConfig(seeds=[seed_a_dir, seed_b_dir], out_dir=out_dir)
    completer = _StubCompleter(responses=["Merged overview body."])
    ctx = StepContext(config=cfg, out_dir=out_dir, runtime=cast(LLMCompleter, completer))

    step = MergeManualProseStep(seed_manual_paths=[seed_a, seed_b])
    step.run(ctx)

    manual_path = out_dir / "manual" / "manual.md"
    body = manual_path.read_text(encoding="utf-8")
    assert body.startswith("# Shop Manual — Premium Storefront\n")
    assert "Merged overview body." in body
    assert _h2_section_names(body) == ["Overview"]
    _assert_no_real_brand_leaks(body)


def test_step_run_requires_upstream_capabilities(tmp_path: Path) -> None:
    """Step refuses to run when ``merge_capabilities`` hasn't written its output."""
    seed_a = _write_manual(tmp_path / "a", _seed_manual("X", sections={"Overview": "A."}))
    seed_b = _write_manual(tmp_path / "b", _seed_manual("X", sections={"Overview": "B."}))
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = ShopGenConfig(seeds=[tmp_path / "a", tmp_path / "b"], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir, runtime=None)

    step = MergeManualProseStep(seed_manual_paths=[seed_a, seed_b])
    with pytest.raises(FileNotFoundError, match="merge_capabilities first"):
        step.run(ctx)
