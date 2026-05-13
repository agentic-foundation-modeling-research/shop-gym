"""``split_manual_parts`` — slice the merged manual into per-area sub-manuals.

Pure-filesystem step that consumes ``manual/manual.md`` and emits six
area-scoped views under ``manual/parts/``: ``homepage.md``,
``navigation.md``, ``product.md``, ``collections.md``,
``cart_and_search.md``, ``info_pages.md``. The build executor uses
each sub-manual as a focused brief for its owned ``gen_*`` task so the
agent does not have to re-read the full storefront manual every
iteration.

Routing is deterministic. Every canonical H2 section in the merged
manual maps to zero or one sub-manual via :data:`_SECTION_TO_PART`;
sections that route to no sub-manual (``Overview``, ``UX Patterns
Summary``, unrecognized headings) stay in ``manual/manual.md`` only.
The helper validates that the merged manual carries at least one of
the structural sections required for a coherent storefront — a
regressed merge that would otherwise produce empty sub-manuals raises
``ValueError``.

Step contract (spec §5.7.1, paired with
``docs/specs/shop_arena/manual_split.md``):

* ``id``: ``split_manual_parts``.
* ``phase``: ``manual_merge``.
* ``inputs``: :class:`StepInput` for the upstream manual producer
  (``merge_manual_prose`` for multi-seed runs, ``copy_seed_manual``
  for single-seed runs).
* ``outputs``: ``manual/parts/<area>.md`` for each of the six
  canonical sub-manuals.
* ``depends_on``: ``[<upstream_step_id>]``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

from shop_arena.gen.manual_merge.prose import (
    _CANONICAL_SECTIONS,  # pyright: ignore[reportPrivateUsage]  # sibling-module reuse
    _parse_manual_sections,  # pyright: ignore[reportPrivateUsage]  # sibling-module reuse
)
from shop_arena.gen.steps.base import InputRef, StepContext, StepInput

_log = logging.getLogger(__name__)

_PHASE: Final[str] = "manual_merge"
_STEP_ID: Final[str] = "split_manual_parts"
_STEP_VERSION: Final[int] = 1

_MANUAL_DIR: Final[Path] = Path("manual")
_MANUAL_FILE: Final[Path] = _MANUAL_DIR / "manual.md"
_PARTS_DIR: Final[Path] = _MANUAL_DIR / "parts"

_PART_NAMES: Final[tuple[str, ...]] = (
    "homepage",
    "navigation",
    "product",
    "collections",
    "cart_and_search",
    "info_pages",
)
"""Deterministic order in which sub-manuals are emitted."""

_SECTION_TO_PART: Final[dict[str, tuple[str, ...]]] = {
    "Overview": (),
    "Site shell": ("navigation",),
    "Homepage": ("homepage",),
    "Collections & navigation": ("collections",),
    "Product page": ("product",),
    "Cart": ("cart_and_search",),
    "Search": ("cart_and_search",),
    "Internationalization": ("navigation",),
    "Floating UX": ("homepage",),
    "Policy & info pages": ("info_pages",),
    "UX Patterns Summary": (),
}
"""Routing map from a canonical H2 section to the sub-manuals it joins.

Sections mapped to ``()`` stay in the full ``manual/manual.md`` only.
The downstream consumer of those sections is ``gen_theme`` /
``visual_fix`` (which read the full manual) plus any human reader.
"""

_REQUIRED_ANY_OF: Final[frozenset[str]] = frozenset(
    {
        "Homepage",
        "Product page",
        "Collections & navigation",
        "Cart",
        "Policy & info pages",
    },
)
"""Validation: at least one of these sections must be present.

A merged manual with none of these is structurally broken — the merge
prompt collapsed everything or the step ran on the wrong file. Failing
loudly here catches the regression before the planner reads garbage.
"""

_EMPTY_BODY_PLACEHOLDER: Final[str] = (
    "_(no sections from the merged manual route to this part)_"
)
"""Body emitted when a sub-manual receives zero canonical sections.

Downstream consumers can rely on ``manual/parts/<area>.md`` always
existing; the placeholder makes the file non-empty and explains the
state to a human reader.
"""


def split_manual_into_parts(manual_text: str) -> dict[str, str]:
    """Slice ``manual_text`` into six canonical sub-manuals.

    Args:
        manual_text: Full ``manual/manual.md`` body (H1 + canonical
            H2 sections in canonical order, terminated by a single
            newline).

    Returns:
        Mapping from sub-manual name (one of :data:`_PART_NAMES`) to
        its rendered body. Each body has a single H1 line ``# Sub-Manual
        — <area>`` followed by the routed H2 sections in canonical
        order, ending with a single trailing newline. Sub-manuals with
        zero routed sections receive a placeholder body so callers can
        always write a non-empty file.

    Raises:
        ValueError: ``manual_text`` contains none of the structural
            sections in :data:`_REQUIRED_ANY_OF` — the merge regressed
            and the sub-manuals would otherwise be empty.
    """
    sections = _parse_manual_sections(manual_text)
    present = sections.keys() & _REQUIRED_ANY_OF
    if not present:
        raise ValueError(
            "merged manual is missing every required structural section "
            f"({sorted(_REQUIRED_ANY_OF)!r}); refusing to split into "
            "empty sub-manuals",
        )

    for name in sections:
        if name not in _SECTION_TO_PART:
            _log.warning(
                "split_manual_parts: section %r is not in the canonical "
                "routing map; it will remain in manual.md only",
                name,
            )

    bodies: dict[str, str] = {}
    for part_name in _PART_NAMES:
        bodies[part_name] = _render_part(part_name, sections)
    return bodies


class SplitManualPartsStep:
    """Phase 1 ``split_manual_parts`` step.

    Reads ``<out_dir>/manual/manual.md``, slices it into six per-area
    sub-manuals via :func:`split_manual_into_parts`, and writes each to
    ``<out_dir>/manual/parts/<area>.md``.

    Attributes:
        id: Step id (``split_manual_parts``).
        phase: ``manual_merge``.
        inputs: One :class:`StepInput` for the upstream manual producer.
        outputs: ``manual/parts/<area>.md`` for each canonical sub-manual.
        depends_on: ``[<upstream_step_id>]``.
        version: Bumped when the routing map or step behaviour changes.
    """

    def __init__(self, *, upstream_step_id: str) -> None:
        """Build the step.

        Args:
            upstream_step_id: Id of the step that wrote
                ``manual/manual.md``. Multi-seed runs pass
                ``"merge_manual_prose"``; single-seed runs pass
                ``"copy_seed_manual"``.
        """
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [StepInput(step_id=upstream_step_id)]
        self.outputs: list[Path] = [_PARTS_DIR / f"{name}.md" for name in _PART_NAMES]
        self.depends_on: list[str] = [upstream_step_id]
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Slice ``manual/manual.md`` into ``manual/parts/<area>.md``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is unused — the
                split is deterministic.

        Raises:
            FileNotFoundError: ``manual/manual.md`` does not exist.
            ValueError: The merged manual is structurally broken (see
                :func:`split_manual_into_parts`).
        """
        manual_path = ctx.out_dir / _MANUAL_FILE
        if not manual_path.exists():
            raise FileNotFoundError(
                f"merged manual not found at {manual_path}; run the "
                "manual-merge upstream step first",
            )
        manual_text = manual_path.read_text(encoding="utf-8")
        parts = split_manual_into_parts(manual_text)

        parts_dir = ctx.out_dir / _PARTS_DIR
        parts_dir.mkdir(parents=True, exist_ok=True)
        for part_name, body in parts.items():
            (parts_dir / f"{part_name}.md").write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


_PART_HEADINGS: Final[dict[str, str]] = {
    "homepage": "Homepage",
    "navigation": "Navigation",
    "product": "Product",
    "collections": "Collections",
    "cart_and_search": "Cart & Search",
    "info_pages": "Info Pages",
}
"""Human-readable label inserted into the H1 line of each sub-manual."""


def _render_part(part_name: str, sections: dict[str, str]) -> str:
    """Render the body of one sub-manual.

    Walks :data:`_CANONICAL_SECTIONS` in canonical order, appending
    each section that routes to ``part_name`` and is present in
    ``sections``. Empty parts receive :data:`_EMPTY_BODY_PLACEHOLDER`.

    Args:
        part_name: Sub-manual name (one of :data:`_PART_NAMES`).
        sections: H2-keyed mapping from the merged manual.

    Returns:
        The rendered body, ending with a single newline.
    """
    label = _PART_HEADINGS[part_name]
    pieces: list[str] = [f"# Sub-Manual — {label}", ""]
    appended_any = False
    for section_name in _CANONICAL_SECTIONS:
        targets = _SECTION_TO_PART.get(section_name, ())
        if part_name not in targets:
            continue
        body = sections.get(section_name)
        if body is None or not body.strip():
            continue
        pieces.append(f"## {section_name}")
        pieces.append("")
        pieces.append(body.rstrip())
        pieces.append("")
        appended_any = True
    if not appended_any:
        pieces.append(_EMPTY_BODY_PLACEHOLDER)
        pieces.append("")
    return "\n".join(pieces).rstrip() + "\n"


__all__ = [
    "SplitManualPartsStep",
    "split_manual_into_parts",
]
