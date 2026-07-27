"""Optional representative-page visual-judge tests with a fake client."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from shop_arena.env_eval.errors import StructureComparisonError
from shop_arena.env_eval.structure.schema import (
    PageStructure,
    RepresentativePageType,
    SnapshotShop,
    StructureSnapshot,
)
from shop_arena.env_eval.structure.visual import (
    VISUAL_RESPONSE_SCHEMA,
    load_visual_prompt,
    run_visual_judges,
)
from shop_arena.env_eval.transition.node_artifacts import node_folder_name
from shop_arena.util._llm import VisionResponse


class _FakeClient:
    """Queue-backed client that records every visual-judge call."""

    def __init__(self, model: str, responses: Sequence[VisionResponse]) -> None:
        self._model = model
        self._responses = list(responses)
        self.calls: list[tuple[str, tuple[bytes, ...], Mapping[str, Any], float]] = []

    @property
    def model(self) -> str:
        """Return the configured fake model id."""
        return self._model

    def call(
        self,
        *,
        prompt: str,
        images: Sequence[bytes],
        schema: Mapping[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        """Record one call and return the next queued response."""
        self.calls.append((prompt, tuple(images), schema, temperature))
        return self._responses.pop(0)

    def call_text(
        self,
        *,
        prompt: str,
        schema: Mapping[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        """Reject text-only calls; visual comparison must always send images."""
        raise AssertionError((prompt, schema, temperature))


def _snapshot(
    sample: int,
    page_types: Sequence[RepresentativePageType],
) -> StructureSnapshot:
    """Build a compact snapshot with stable canonical ids."""
    canonical_ids: dict[RepresentativePageType, str] = {
        "homepage": "/",
        "collection": "/collections/<*>",
        "product": "/products/<*>",
        "policy": "/policies/<*>",
        "cart": "/cart",
        "search": "/search",
    }
    return StructureSnapshot(
        shop=SnapshotShop(url=f"https://shop-{sample}.example", eval_version="test"),
        pages=tuple(
            PageStructure(
                page_type=page_type,
                canonical_id=canonical_ids[page_type],
                element_type_histogram={"main": 1},
                maximum_depth=1,
            )
            for page_type in page_types
        ),
    )


def _write_screenshots(run_dir: Path, snapshot: StructureSnapshot, sample: int) -> None:
    """Write distinct fake PNG payloads at EnvEval's observation paths."""
    observation_dir = run_dir / "observation"
    observation_dir.mkdir(parents=True)
    for page in snapshot.pages:
        path = observation_dir / f"{node_folder_name(page.canonical_id)}.png"
        path.write_bytes(f"sample={sample};page={page.page_type}".encode())


def _response(distances: tuple[float, float, float], rationale: str) -> VisionResponse:
    """Return a valid response with deliberately shuffled sample order."""
    payload = {
        "shops": [
            {"sample": 2, "distance": distances[2], "rationale": "sample two"},
            {"sample": 0, "distance": distances[0], "rationale": "sample zero"},
            {"sample": 1, "distance": distances[1], "rationale": "sample one"},
        ],
        "rationale": rationale,
    }
    return VisionResponse(parsed=payload, raw_response=str(payload))


def test_visual_judge_computes_page_model_and_shop_means(tmp_path: Path) -> None:
    """Each page is one cohort call and all published means are code-computed."""
    snapshots = tuple(_snapshot(index, ("homepage", "collection")) for index in range(3))
    run_dirs = tuple(tmp_path / "runs" / f"{index:03d}" for index in range(3))
    for index, (run_dir, snapshot) in enumerate(zip(run_dirs, snapshots, strict=True)):
        _write_screenshots(run_dir, snapshot, index)
    client = _FakeClient(
        "gpt-5",
        (
            _response((0.1, 0.2, 0.6), "homepage cohort"),
            _response((0.3, 0.4, 0.5), "collection cohort"),
        ),
    )

    (result,) = run_visual_judges(
        models=("gpt-5",),
        snapshots=snapshots,
        run_dirs=run_dirs,
        comparison_dir=tmp_path,
        client_builder=lambda _model: client,
    )

    assert len(client.calls) == 2
    assert client.calls[0][1] == (
        b"sample=0;page=homepage",
        b"sample=1;page=homepage",
        b"sample=2;page=homepage",
    )
    assert client.calls[0][2] is VISUAL_RESPONSE_SCHEMA
    assert "image 1 -> sample 0" in client.calls[0][0]
    assert "page_type: homepage" in client.calls[0][0]
    assert [page.cohort_distance for page in result.pages] == [0.3, 0.4]
    assert result.visual_distance == 0.35
    assert [shop.model_dump() for shop in result.shops] == [
        {"sample": 0, "page_count": 2, "distance": 0.2},
        {"sample": 1, "page_count": 2, "distance": 0.3},
        {"sample": 2, "page_count": 2, "distance": 0.55},
    ]
    assert result.llm_calls == 2
    assert (tmp_path / result.artifact).is_file()
    assert all((tmp_path / page.artifact).is_file() for page in result.pages)


def test_visual_judge_quarantines_wrong_sample_set(tmp_path: Path) -> None:
    """Missing sample ids produce a null score rather than a false zero."""
    snapshots = tuple(_snapshot(index, ("homepage",)) for index in range(3))
    run_dirs = tuple(tmp_path / "runs" / f"{index:03d}" for index in range(3))
    for index, (run_dir, snapshot) in enumerate(zip(run_dirs, snapshots, strict=True)):
        _write_screenshots(run_dir, snapshot, index)
    bad_payload = {
        "shops": [
            {"sample": 0, "distance": 0.1, "rationale": "first"},
            {"sample": 1, "distance": 0.2, "rationale": "second"},
        ],
        "rationale": "missing third sample",
    }
    client = _FakeClient(
        "claude-test",
        (VisionResponse(parsed=bad_payload, raw_response="raw bad response"),),
    )

    (result,) = run_visual_judges(
        models=("claude-test",),
        snapshots=snapshots,
        run_dirs=run_dirs,
        comparison_dir=tmp_path,
        client_builder=lambda _model: client,
    )

    assert result.visual_distance is None
    assert result.successful_page_count == 0
    assert result.shops == ()
    assert result.pages[0].cohort_distance is None
    assert result.pages[0].shops == ()
    assert "do not match expected" in result.pages[0].parse_errors[0]
    assert result.pages[0].raw_response == "raw bad response"


def test_visual_judges_keep_models_independent(tmp_path: Path) -> None:
    """Each requested model gets its own call, score, and artifact directory."""
    snapshots = (_snapshot(0, ("homepage",)), _snapshot(1, ("homepage",)))
    run_dirs = (tmp_path / "runs" / "000", tmp_path / "runs" / "001")
    for index, (run_dir, snapshot) in enumerate(zip(run_dirs, snapshots, strict=True)):
        _write_screenshots(run_dir, snapshot, index)
    clients = {
        "gpt-5": _FakeClient(
            "gpt-5",
            (
                VisionResponse(
                    parsed={
                        "shops": [
                            {"sample": 0, "distance": 0.2, "rationale": "first"},
                            {"sample": 1, "distance": 0.4, "rationale": "second"},
                        ],
                        "rationale": "openai result",
                    },
                    raw_response="openai raw",
                ),
            ),
        ),
        "claude-test": _FakeClient(
            "claude-test",
            (
                VisionResponse(
                    parsed={
                        "shops": [
                            {"sample": 0, "distance": 0.6, "rationale": "first"},
                            {"sample": 1, "distance": 0.8, "rationale": "second"},
                        ],
                        "rationale": "anthropic result",
                    },
                    raw_response="anthropic raw",
                ),
            ),
        ),
    }

    results = run_visual_judges(
        models=("gpt-5", "claude-test"),
        snapshots=snapshots,
        run_dirs=run_dirs,
        comparison_dir=tmp_path,
        client_builder=clients.__getitem__,
    )

    assert [result.visual_distance for result in results] == [0.3, 0.7]
    assert [result.model for result in results] == ["gpt-5", "claude-test"]
    assert results[0].artifact.startswith("visual/000-gpt-5/")
    assert results[1].artifact.startswith("visual/001-claude-test/")
    assert len(clients["gpt-5"].calls) == 1
    assert len(clients["claude-test"].calls) == 1


def test_visual_judge_requires_selected_page_screenshot(tmp_path: Path) -> None:
    """A selected page without its captured screenshot fails loudly."""
    snapshots = (_snapshot(0, ("homepage",)), _snapshot(1, ("homepage",)))
    run_dirs = (tmp_path / "runs" / "000", tmp_path / "runs" / "001")
    _write_screenshots(run_dirs[0], snapshots[0], 0)

    with pytest.raises(StructureComparisonError, match="screenshot is missing"):
        run_visual_judges(
            models=("gpt-5",),
            snapshots=snapshots,
            run_dirs=run_dirs,
            comparison_dir=tmp_path,
            client_builder=lambda _model: pytest.fail("client must not be constructed"),
        )


def test_visual_prompt_scopes_content_independent_design() -> None:
    """The bundled prompt pins design dimensions and ignored product content."""
    prompt = load_visual_prompt()

    assert "visual hierarchy" in prompt
    assert "typography" in prompt
    assert "spacing and density" in prompt
    assert "Ignore product identity" in prompt
    assert "text semantics" in prompt
