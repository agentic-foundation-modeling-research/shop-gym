"""``merge_manual_prose`` — Phase 1 multi-seed prose merge (spec §5.2).

Section-by-section LLM merge of the seed ``manual.md`` files conditioned
on the merged capabilities document produced by
:mod:`shop_gen.manual_merge.capabilities`. The merged capabilities are
treated as ground truth: the prompt forwards them verbatim and instructs
the model to drop any seed sentence that contradicts them (spec §5.2).

The step parses each seed manual into ``{section_name: body}`` mappings
keyed by H2 (``## ``) headings, walks the canonical section order from
the ``shop_explore`` ``synthesize_manual.md`` prompt, and for every
section that two or more seeds populate runs one LLM completion. Sections
that only one seed populates are copied verbatim — no LLM call needed —
so the merge stays as cheap as possible.

Brand safety. Per spec §5.6 the prose merge is brand-free *by prompt
rule*; the post-pass scrubber that runs once ``identity.json`` exists is
a Phase 2 concern. The prompt body explicitly forbids real-brand
mentions and only allows allowlist tokens once the identity exists.

Step contract (spec §5.7.1):

* ``id``: ``merge_manual_prose``.
* ``phase``: ``manual_merge``.
* ``inputs``: one :class:`~shop_gen.steps.base.FileInput` per seed
  ``manual.md`` plus a :class:`~shop_gen.steps.base.StepInput` for
  ``merge_capabilities`` (the merged capabilities are the prompt's
  ground-truth context).
* ``outputs``: ``manual/manual.md``.
* ``depends_on``: ``[merge_capabilities]``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

from harness.runtimes import LLMCompleter
from shop_gen.steps.base import FileInput, InputRef, StepContext, StepInput

_PHASE: Final[str] = "manual_merge"
_STEP_ID: Final[str] = "merge_manual_prose"
_UPSTREAM_ID: Final[str] = "merge_capabilities"
_STEP_VERSION: Final[int] = 1

_OUT_MANUAL: Final[Path] = Path("manual") / "manual.md"
_IN_CAPABILITIES: Final[Path] = Path("manual") / "capabilities.json"

_LLM_TIMEOUT_S: Final[float] = 120.0

# Canonical H2 section order, mirroring
# ``shop_explore/prompts/synthesize_manual.md`` §1. Sections produced by
# any seed but absent from this list are appended afterwards in their
# first-seen order so unfamiliar areas never get silently dropped.
_CANONICAL_SECTIONS: Final[tuple[str, ...]] = (
    "Overview",
    "Site shell",
    "Homepage",
    "Collections & navigation",
    "Product page",
    "Cart",
    "Search",
    "Internationalization",
    "Floating UX",
    "Policy & info pages",
    "UX Patterns Summary",
)

_FALLBACK_DESCRIPTOR: Final[str] = "Generic Storefront"

_SECTION_PROMPT_TEMPLATE: Final[str] = """\
You are merging the ``## {section}`` section of multiple
brand-anonymized storefront manuals into a single coherent section.

Treat the merged capabilities below as ground truth. Drop any sentence
from a seed that contradicts them. Where seeds describe the same surface
with overlapping detail, keep the most specific phrasing once and remove
duplicates.

Brand safety:
- Do not mention any real-world company, product, or trademark.
- Do not invent a fake brand name.
- The merged storefront has no name yet; refer to it as "the
  storefront", "the shop", or via its descriptor.

Style:
- Match the seed's structural register: short prose paragraphs and
  bullet lists. Preserve any ``### Element`` H3 blocks the seeds use.
- Do not add the ``## {section}`` heading — emit the section body only.
- End with a single newline.

## Merged capabilities (ground truth, JSON)

```json
{capabilities}
```

## Seed sections to merge

{seed_blocks}

Output: the merged section body for ``## {section}``. No commentary, no
H2 heading, no fenced wrappers. End with a single newline.
"""


def merge_manual_prose_seeds(
    seed_manual_paths: Sequence[Path],
    *,
    merged_capabilities: dict[str, Any],
    completer: LLMCompleter | None = None,
) -> str:
    """Merge per-seed ``manual.md`` files into a single prose document.

    Parses each seed manual into its H2 sections, walks the canonical
    section order, copies single-seed sections verbatim, and delegates
    every multi-seed section to ``completer``. Returns the assembled
    manual body — H1 line + merged H2 sections in canonical order, plus
    any extra seed-specific sections appended in first-seen order.

    Args:
        seed_manual_paths: One ``manual.md`` per seed, in the user's
            seed order.
        merged_capabilities: Merged capabilities document (Phase 1
            ``merge_capabilities`` output) used as the ground-truth
            context for every LLM call. The ``shop.descriptor`` field
            populates the H1 line.
        completer: Optional one-shot LLM. Required when at least one
            section is contributed by two or more seeds.

    Returns:
        The merged manual body as a single string ending with a newline.

    Raises:
        ValueError: ``seed_manual_paths`` is empty, or an LLM merge was
            needed but ``completer`` is ``None``, or the LLM returned
            an empty body.
        FileNotFoundError: A seed path does not exist.
    """
    if not seed_manual_paths:
        raise ValueError("seed_manual_paths must contain at least one path")

    seed_sections: list[dict[str, str]] = [
        _parse_manual_sections(path.read_text(encoding="utf-8"))
        if path.exists()
        else _raise_missing(path)
        for path in seed_manual_paths
    ]
    seed_names = [f"seed_{index}" for index in range(len(seed_sections))]

    descriptor = _descriptor_from_capabilities(merged_capabilities)
    capabilities_json = json.dumps(merged_capabilities, indent=2, sort_keys=True)

    ordered_sections = _ordered_section_names(seed_sections)
    pieces: list[str] = [f"# Shop Manual — {descriptor}", ""]
    for section in ordered_sections:
        body = _merge_section(
            section=section,
            seed_names=seed_names,
            seed_sections=seed_sections,
            capabilities_json=capabilities_json,
            completer=completer,
        )
        pieces.append(f"## {section}")
        pieces.append("")
        pieces.append(body.rstrip())
        pieces.append("")
    # Single trailing newline (rstrip + final "\n" join below).
    return "\n".join(pieces).rstrip() + "\n"


class MergeManualProseStep:
    """Phase 1 ``merge_manual_prose`` step (spec §5.2).

    Reads each seed's ``manual.md`` and the merged capabilities written
    by the upstream ``merge_capabilities`` step, runs a section-by-section
    LLM merge via :func:`merge_manual_prose_seeds`, and writes the
    resulting prose to ``manual/manual.md``.

    Attributes:
        id: Step id (``merge_manual_prose``).
        phase: ``manual_merge``.
        inputs: One :class:`FileInput` per seed ``manual.md`` plus a
            :class:`StepInput` for ``merge_capabilities``.
        outputs: ``manual/manual.md``.
        depends_on: ``[merge_capabilities]``.
        version: Bumped when the merge behaviour changes (spec §5.7.1).
    """

    def __init__(self, seed_manual_paths: Sequence[Path]) -> None:
        """Build the step from the per-seed ``manual.md`` paths.

        Args:
            seed_manual_paths: One path per seed, in the user's seed
                order. May be empty, in which case the step lists only
                its id / phase (used by
                :func:`shop_gen.pipeline.list_steps`).
        """
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [
            *(FileInput(path=path) for path in seed_manual_paths),
            StepInput(step_id=_UPSTREAM_ID),
        ]
        self.outputs: list[Path] = [_OUT_MANUAL]
        self.depends_on: list[str] = [_UPSTREAM_ID]
        self.version: int = _STEP_VERSION
        self._seed_paths: tuple[Path, ...] = tuple(seed_manual_paths)

    def run(self, ctx: StepContext) -> None:
        """Merge the seed manuals into ``manual/manual.md``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is forwarded as the
                LLM completer for per-section merges.

        Raises:
            ValueError: ``seed_manual_paths`` is empty, or an LLM merge
                was needed but ``ctx.runtime`` is ``None``, or the LLM
                returned an empty body.
            FileNotFoundError: A seed path is missing, or the upstream
                ``manual/capabilities.json`` has not been written yet.
        """
        capabilities_path = ctx.out_dir / _IN_CAPABILITIES
        if not capabilities_path.exists():
            raise FileNotFoundError(
                f"merged capabilities not found at {capabilities_path}; "
                "run merge_capabilities first",
            )
        raw_capabilities: Any = json.loads(capabilities_path.read_text(encoding="utf-8"))
        if not isinstance(raw_capabilities, dict):
            raise ValueError(
                f"{capabilities_path} must contain a JSON object, "
                f"got {type(raw_capabilities).__name__}",
            )
        merged_capabilities = cast("dict[str, Any]", raw_capabilities)

        body = merge_manual_prose_seeds(
            self._seed_paths,
            merged_capabilities=merged_capabilities,
            completer=ctx.runtime,
        )
        out_path = ctx.out_dir / _OUT_MANUAL
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


_H1_PATTERN: Final[re.Pattern[str]] = re.compile(r"^#\s+.*$", re.MULTILINE)
_H2_PATTERN: Final[re.Pattern[str]] = re.compile(r"^##\s+(?P<name>.+?)\s*$", re.MULTILINE)


def _parse_manual_sections(text: str) -> dict[str, str]:
    """Split a ``manual.md`` body into ``{section_name: body}``.

    Sections are keyed by the H2 (``## ``) heading text. The H1 line and
    any preamble before the first H2 are dropped (they carry no
    section-level signal). Section bodies preserve internal H3+ blocks
    verbatim and are right-stripped so the merge concatenation can
    re-insert exactly one blank line between sections.

    Args:
        text: Full ``manual.md`` contents.

    Returns:
        Ordered mapping from H2 heading to its body. Heading names
        appear in the same order as in ``text``.
    """
    sections: dict[str, str] = {}
    matches = list(_H2_PATTERN.finditer(text))
    for index, match in enumerate(matches):
        name = match.group("name").strip()
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip("\n").rstrip()
        sections[name] = body
    return sections


def _ordered_section_names(seed_sections: Sequence[dict[str, str]]) -> list[str]:
    """Return the canonical section order, plus seed-specific tail sections.

    Sections from :data:`_CANONICAL_SECTIONS` come first (in canonical
    order, only when at least one seed populated them). Any extra
    section the seeds produced — not in the canonical list — is
    appended in first-seen order so unfamiliar areas never get
    silently dropped.
    """
    contributed: set[str] = set()
    for sections in seed_sections:
        contributed.update(sections.keys())

    ordered: list[str] = [name for name in _CANONICAL_SECTIONS if name in contributed]
    extras: list[str] = []
    seen: set[str] = set(ordered)
    for sections in seed_sections:
        for name in sections:
            if name in seen:
                continue
            seen.add(name)
            extras.append(name)
    return ordered + extras


def _merge_section(
    *,
    section: str,
    seed_names: Sequence[str],
    seed_sections: Sequence[dict[str, str]],
    capabilities_json: str,
    completer: LLMCompleter | None,
) -> str:
    """Merge one named H2 section across all seeds.

    Sections contributed by exactly one seed are copied verbatim. With
    two or more contributors, delegates to ``completer`` with the
    canonical per-section prompt.

    Raises:
        ValueError: A multi-seed section needs the LLM but ``completer``
            is ``None``, or the LLM returned an empty body.
    """
    contributions: list[tuple[str, str]] = [
        (name, sections[section])
        for name, sections in zip(seed_names, seed_sections, strict=True)
        if section in sections and sections[section].strip()
    ]
    if not contributions:
        # Reachable only if a seed left a ``## Section`` header with an
        # empty body. Treat as missing — the canonical-order builder
        # would have skipped a fully-absent section anyway.
        return ""
    if len(contributions) == 1:
        return contributions[0][1].rstrip() + "\n"
    if completer is None:
        raise ValueError(
            f"section {section!r} has multiple seed contributions and "
            "requires a runtime with LLMCompleter; got None",
        )
    seed_blocks = "\n\n".join(f"### {name}\n\n{body}".rstrip() for name, body in contributions)
    prompt = _SECTION_PROMPT_TEMPLATE.format(
        section=section,
        capabilities=capabilities_json,
        seed_blocks=seed_blocks,
    )
    raw = completer.complete(prompt, timeout=_LLM_TIMEOUT_S)
    body = raw.strip("\n").rstrip()
    if not body:
        raise ValueError(f"section {section!r}: LLM returned an empty body")
    return body + "\n"


def _descriptor_from_capabilities(merged: dict[str, Any]) -> str:
    """Pull the H1 descriptor out of merged capabilities.

    Falls back to :data:`_FALLBACK_DESCRIPTOR` when ``shop.descriptor``
    is missing or empty. The descriptor merge in
    :func:`shop_gen.manual_merge.capabilities.merge_capabilities_seeds`
    keeps it brand-free by construction, so the fallback path matters
    only for malformed callers.
    """
    shop: Any = merged.get("shop")
    if isinstance(shop, dict):
        descriptor: Any = cast("dict[str, Any]", shop).get("descriptor")
        if isinstance(descriptor, str) and descriptor.strip():
            return descriptor.strip()
    return _FALLBACK_DESCRIPTOR


def _raise_missing(path: Path) -> dict[str, str]:
    """Helper for the inline parsing list comprehension."""
    raise FileNotFoundError(f"seed manual file not found: {path}")


__all__ = [
    "MergeManualProseStep",
    "merge_manual_prose_seeds",
]
