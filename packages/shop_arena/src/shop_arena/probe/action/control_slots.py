"""Dispatcher for ``action.control_slots`` rubric entries.

Same shape as :mod:`shop_arena.probe.observation.info_slots` but selects
``family=action kind=control_slot`` entries and writes into the
:class:`shop_arena.probe.report.ActionBlock` ``control_slots`` field.
"""

from __future__ import annotations

from pathlib import Path

from shop_arena.probe.capture.bundle import PageBundle
from shop_arena.probe.judge.client import judge_slot
from shop_arena.probe.report import SlotVerdict
from shop_arena.probe.rubric.schema import Modality, PageType, RubricEntry

ControlSlotsResult = dict[PageType, dict[str, dict[Modality, SlotVerdict]]]


async def judge_control_slots(
    entries: tuple[RubricEntry, ...],
    *,
    bundle: PageBundle,
    bundle_root: Path,
    prompts_root: Path,
    model: str,
    client: object,
) -> ControlSlotsResult:
    """Dispatch every control_slot entry against the bundle."""
    out: ControlSlotsResult = {}
    for entry in entries:
        if entry.family != "action" or entry.kind != "control_slot":
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
