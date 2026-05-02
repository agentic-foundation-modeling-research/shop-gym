"""v1.0 rubric: family/kind discriminators, page types, modalities, loader."""

from shop_arena.probe.rubric.loader import (
    RubricLoadError,
    compute_content_hash,
    load_rubric,
    load_rubric_bytes,
)
from shop_arena.probe.rubric.schema import (
    Family,
    Kind,
    Modality,
    PageType,
    Rubric,
    RubricEntry,
)

__all__ = [
    "Family",
    "Kind",
    "Modality",
    "PageType",
    "Rubric",
    "RubricEntry",
    "RubricLoadError",
    "compute_content_hash",
    "load_rubric",
    "load_rubric_bytes",
]
