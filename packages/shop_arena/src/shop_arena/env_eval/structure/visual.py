"""Optional model-separated visual judging for representative shop pages."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from statistics import fmean
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shop_arena.env_eval.errors import StructureComparisonError
from shop_arena.env_eval.structure.schema import (
    REPRESENTATIVE_PAGE_TYPES,
    RepresentativePageType,
    StructureSnapshot,
    VisualModelResult,
    VisualPageJudgment,
    VisualSampleSummary,
    VisualShopDistance,
)
from shop_arena.env_eval.transition.node_artifacts import node_folder_name
from shop_arena.util._llm import LLMVisionClient, VisionResponse

VISUAL_PROMPT_VERSION: Final[str] = "0.1"
VISUAL_TEMPERATURE: Final[float] = 0.0
VISUAL_RESPONSE_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "shops": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sample": {"type": "integer", "minimum": 0},
                    "distance": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "rationale": {"type": "string", "minLength": 1},
                },
                "required": ["sample", "distance", "rationale"],
                "additionalProperties": False,
            },
        },
        "rationale": {"type": "string", "minLength": 1},
    },
    "required": ["shops", "rationale"],
    "additionalProperties": False,
}

_PROMPT_PACKAGE: Final[str] = "shop_arena.env_eval.structure"
_PROMPT_FILENAME: Final[str] = "visual_prompt.md"
_PROMPT_DIVIDER: Final[str] = "\n---\n"
_ROUND_DIGITS: Final[int] = 6
_MIN_VISUAL_SAMPLES: Final[int] = 2

type VisionClientBuilder = Callable[[str], LLMVisionClient]


@dataclass(frozen=True, slots=True)
class _VisualInput:
    """One screenshot and its stable report identity."""

    sample: int
    screenshot_path: Path
    screenshot_reference: str


class _Closed(BaseModel):
    """Closed response model used before publishing a judge result."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class _ResponseShop(_Closed):
    """One shop entry returned by a visual judge."""

    sample: int = Field(ge=0, strict=True)
    distance: float = Field(ge=0.0, le=1.0, strict=True)
    rationale: str = Field(min_length=1, strict=True)


class _Response(_Closed):
    """Strict response body returned by a visual judge."""

    shops: tuple[_ResponseShop, ...]
    rationale: str = Field(min_length=1, strict=True)


def load_visual_prompt() -> str:
    """Load the visual-judge prompt body bundled with ShopArena."""
    text = resources.files(_PROMPT_PACKAGE).joinpath(_PROMPT_FILENAME).read_text(encoding="utf-8")
    if _PROMPT_DIVIDER not in text:
        raise RuntimeError(
            f"{_PROMPT_FILENAME} is missing the required '---' divider between "
            "the documentation header and prompt body",
        )
    return text.split(_PROMPT_DIVIDER, 1)[1].strip() + "\n"


def run_visual_judges(
    *,
    models: Sequence[str],
    snapshots: Sequence[StructureSnapshot],
    run_dirs: Sequence[Path],
    comparison_dir: Path,
    client_builder: VisionClientBuilder,
) -> tuple[VisualModelResult, ...]:
    """Judge representative screenshots and persist model/page artifacts.

    Args:
        models: Vision-capable model ids. Each model is evaluated independently.
        snapshots: Structural snapshots in sample-index order.
        run_dirs: EnvEval run directories matching ``snapshots``.
        comparison_dir: Root used for artifacts and relative references.
        client_builder: Provider-independent vision-client constructor.

    Returns:
        One aggregate visual result per requested model.

    Raises:
        StructureComparisonError: A selected page screenshot is missing.
        ValueError: Snapshot and run-directory counts do not match.
    """
    if len(snapshots) != len(run_dirs):
        raise ValueError("snapshots and run_dirs must have the same length")
    page_inputs = _collect_page_inputs(snapshots, run_dirs, comparison_dir)
    results: list[VisualModelResult] = []
    for model_index, model in enumerate(models):
        client = client_builder(model)
        model_dir = comparison_dir / "visual" / _model_folder_name(model_index, model)
        model_dir.mkdir(parents=True, exist_ok=True)
        page_results: list[VisualPageJudgment] = []
        for page_type, inputs in page_inputs:
            artifact_path = model_dir / f"{page_type}.json"
            artifact_reference = _relative_path(artifact_path, comparison_dir)
            page_result = _judge_page(
                client=client,
                page_type=page_type,
                inputs=inputs,
                artifact_reference=artifact_reference,
            )
            _write_model(page_result, artifact_path)
            page_results.append(page_result)

        result_path = model_dir / "result.json"
        result = _aggregate_model_result(
            client=client,
            pages=page_results,
            artifact_reference=_relative_path(result_path, comparison_dir),
        )
        _write_model(result, result_path)
        results.append(result)
    return tuple(results)


def _collect_page_inputs(
    snapshots: Sequence[StructureSnapshot],
    run_dirs: Sequence[Path],
    comparison_dir: Path,
) -> tuple[tuple[RepresentativePageType, tuple[_VisualInput, ...]], ...]:
    """Resolve eligible page-type screenshot cohorts in stable order."""
    page_maps = [{page.page_type: page for page in snapshot.pages} for snapshot in snapshots]
    groups: list[tuple[RepresentativePageType, tuple[_VisualInput, ...]]] = []
    for page_type in REPRESENTATIVE_PAGE_TYPES:
        inputs: list[_VisualInput] = []
        for sample, (pages, run_dir) in enumerate(zip(page_maps, run_dirs, strict=True)):
            page = pages.get(page_type)
            if page is None:
                continue
            screenshot_path = run_dir / "observation" / f"{node_folder_name(page.canonical_id)}.png"
            if not screenshot_path.is_file():
                raise StructureComparisonError(
                    "representative page screenshot is missing for "
                    f"sample {sample}, page type {page_type!r}: {screenshot_path}",
                )
            inputs.append(
                _VisualInput(
                    sample=sample,
                    screenshot_path=screenshot_path,
                    screenshot_reference=_relative_path(screenshot_path, comparison_dir),
                ),
            )
        if len(inputs) >= _MIN_VISUAL_SAMPLES:
            groups.append((page_type, tuple(inputs)))
    return tuple(groups)


def _judge_page(
    *,
    client: LLMVisionClient,
    page_type: RepresentativePageType,
    inputs: Sequence[_VisualInput],
    artifact_reference: str,
) -> VisualPageJudgment:
    """Call one judge for one page type and validate exact sample coverage."""
    response = client.call(
        prompt=_build_prompt(page_type, inputs),
        images=tuple(item.screenshot_path.read_bytes() for item in inputs),
        schema=VISUAL_RESPONSE_SCHEMA,
        temperature=VISUAL_TEMPERATURE,
    )
    parsed, errors = _validate_response(response, inputs)
    if parsed is None:
        return VisualPageJudgment(
            prompt_version=VISUAL_PROMPT_VERSION,
            model=client.model,
            temperature=VISUAL_TEMPERATURE,
            page_type=page_type,
            sample_count=len(inputs),
            artifact=artifact_reference,
            raw_response=response.raw_response,
            parse_errors=errors,
        )

    by_sample = {shop.sample: shop for shop in parsed.shops}
    shops = tuple(
        VisualShopDistance(
            sample=item.sample,
            screenshot=item.screenshot_reference,
            distance=_rounded(by_sample[item.sample].distance),
            rationale=by_sample[item.sample].rationale,
        )
        for item in inputs
    )
    return VisualPageJudgment(
        prompt_version=VISUAL_PROMPT_VERSION,
        model=client.model,
        temperature=VISUAL_TEMPERATURE,
        page_type=page_type,
        sample_count=len(inputs),
        artifact=artifact_reference,
        cohort_distance=_rounded(fmean(shop.distance for shop in shops)),
        shops=shops,
        rationale=parsed.rationale,
        raw_response=response.raw_response,
        parse_errors=errors,
    )


def _validate_response(
    response: VisionResponse,
    inputs: Sequence[_VisualInput],
) -> tuple[_Response | None, tuple[str, ...]]:
    """Validate the closed response and exact expected sample-index set."""
    if response.parsed is None:
        errors = response.parse_errors or ("visual judge returned no parsed response",)
        return None, errors
    try:
        parsed = _Response.model_validate(dict(response.parsed))
    except ValidationError as exc:
        return None, (*response.parse_errors, *_validation_errors(exc))

    expected = tuple(item.sample for item in inputs)
    returned = tuple(shop.sample for shop in parsed.shops)
    if len(set(returned)) != len(returned):
        return None, (*response.parse_errors, "visual judge returned duplicate sample indices")
    if set(returned) != set(expected):
        return None, (
            *response.parse_errors,
            f"visual judge samples {sorted(returned)} do not match expected {sorted(expected)}",
        )
    return parsed, response.parse_errors


def _aggregate_model_result(
    *,
    client: LLMVisionClient,
    pages: Sequence[VisualPageJudgment],
    artifact_reference: str,
) -> VisualModelResult:
    """Compute equal-page-weight model and per-shop visual means."""
    successful = tuple(page for page in pages if page.cohort_distance is not None)
    sample_values: dict[int, list[float]] = {}
    for page in successful:
        for shop in page.shops:
            sample_values.setdefault(shop.sample, []).append(shop.distance)
    shops = tuple(
        VisualSampleSummary(
            sample=sample,
            page_count=len(values),
            distance=_rounded(fmean(values)),
        )
        for sample, values in sorted(sample_values.items())
    )
    visual_distance = (
        _rounded(
            fmean(page.cohort_distance for page in successful if page.cohort_distance is not None),
        )
        if successful
        else None
    )
    return VisualModelResult(
        prompt_version=VISUAL_PROMPT_VERSION,
        model=client.model,
        temperature=VISUAL_TEMPERATURE,
        artifact=artifact_reference,
        page_count=len(pages),
        successful_page_count=len(successful),
        llm_calls=len(pages),
        visual_distance=visual_distance,
        shops=shops,
        pages=tuple(pages),
    )


def _build_prompt(
    page_type: RepresentativePageType,
    inputs: Sequence[_VisualInput],
) -> str:
    """Append deterministic page and image-to-sample context to the prompt."""
    mapping = "\n".join(
        f"- image {image_index} -> sample {item.sample}"
        for image_index, item in enumerate(inputs, start=1)
    )
    return (
        load_visual_prompt().rstrip()
        + "\n\n--- COHORT ---\n"
        + f"page_type: {page_type}\n"
        + f"sample_count: {len(inputs)}\n"
        + "image_mapping:\n"
        + mapping
        + "\n"
    )


def _validation_errors(exc: ValidationError) -> tuple[str, ...]:
    """Render Pydantic response errors in stable human-readable form."""
    errors: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        errors.append(f"visual judge schema validation: {location}: {error['msg']}")
    return tuple(errors)


def _model_folder_name(index: int, model: str) -> str:
    """Return a stable, portable artifact folder for one judge model."""
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", model).strip("-.")
    return f"{index:03d}-{(normalized or 'model')[:80]}"


def _relative_path(path: Path, root: Path) -> str:
    """Return a portable comparison-relative artifact path."""
    return path.relative_to(root).as_posix()


def _write_model(model: BaseModel, path: Path) -> None:
    """Write one closed visual artifact as deterministic JSON."""
    path.write_text(
        json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _rounded(value: float) -> float:
    """Round visual scores for readable, byte-stable artifacts."""
    return round(value, _ROUND_DIGITS)


__all__ = [
    "VISUAL_PROMPT_VERSION",
    "VISUAL_RESPONSE_SCHEMA",
    "VISUAL_TEMPERATURE",
    "VisionClientBuilder",
    "load_visual_prompt",
    "run_visual_judges",
]
