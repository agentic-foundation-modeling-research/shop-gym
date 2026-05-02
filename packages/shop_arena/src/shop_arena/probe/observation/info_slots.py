"""Dispatcher for ``observation.info_slots`` rubric entries.

For every ``family=observation kind=info_slot`` entry in the rubric, and
each modality declared on the entry, calls
:func:`shop_arena.probe.judge.judge_slot` once and accumulates the verdicts
into the nested shape that :class:`shop_arena.probe.report.ObservationBlock`
expects.
"""

from __future__ import annotations

from pathlib import Path

from shop_arena.probe.capture.bundle import PageBundle
from shop_arena.probe.judge.client import judge_slot
from shop_arena.probe.report import SlotVerdict
from shop_arena.probe.rubric.schema import Modality, PageType, RubricEntry

InfoSlotsResult = dict[PageType, dict[str, dict[Modality, SlotVerdict]]]


async def judge_info_slots(
    entries: tuple[RubricEntry, ...],
    *,
    bundle: PageBundle,
    bundle_root: Path,
    prompts_root: Path,
    model: str,
    client: object,
) -> InfoSlotsResult:
    """Dispatch every info_slot entry against the bundle.

    Args:
        entries: All rubric entries; only ``family=observation
            kind=info_slot`` rows are dispatched.
        bundle: The 5-page capture bundle for this shop.
        bundle_root: Directory the bundle's relative paths resolve under.
        prompts_root: Directory under which entries' ``prompt`` paths are
            resolved.
        model: Provider-prefixed model id.
        client: Pre-built provider client.

    Returns:
        ``{page_type: {slot_id: {modality: SlotVerdict}}}``.
    """
    out: InfoSlotsResult = {}
    for entry in entries:
        if entry.family != "observation" or entry.kind != "info_slot":
            continue
        assert entry.page_type is not None
        assert entry.modalities is not None
        assert entry.prompt is not None
        capture = bundle.get(entry.page_type)
        if capture is None:
            continue
        prompt_body = (prompts_root / entry.prompt).read_text(encoding="utf-8")
        per_modality: dict[Modality, SlotVerdict] = {}
        for modality in entry.modalities:
            per_modality[modality] = await judge_slot(
                capture,
                bundle_root=bundle_root,
                modality=modality,
                prompt_body=prompt_body,
                model=model,
                client=client,
            )
        page_bucket = out.setdefault(entry.page_type, {})
        page_bucket[entry.id] = per_modality
    return out
