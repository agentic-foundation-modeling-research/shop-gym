"""``action.space`` — mechanical action-space metrics.

For v1 minimal we compute on the a11y modality only:

* ``actionable_count`` — total interactive nodes (button / link / input /
  combobox / checkbox / radio / menuitem / tab / switch / searchbox /
  spinbutton / slider).
* ``unique_role_name_rate`` — share of actionables whose ``(role, name)``
  pair is unique within the page. A page where every button shares the
  same accessible name (e.g. all ``"Add to cart"``) has a low rate;
  visually-distinct controls but a11y-cloned labels are a transferability
  hazard for text-based agents and the rate makes that visible.

Screenshot action-space metrics (button-shaped region detection) are
deferred to a future iteration.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final, cast

from shop_probe.capture.bundle import PageBundle, PageCapture
from shop_probe.report import ActionSpaceMetrics
from shop_probe.rubric.schema import Modality, PageType

_ACTIONABLE_ROLES: Final[tuple[str, ...]] = (
    "button",
    "link",
    "textbox",
    "combobox",
    "checkbox",
    "radio",
    "menuitem",
    "tab",
    "switch",
    "searchbox",
    "spinbutton",
    "slider",
)

_ACTIONABLE_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r'^\s*-\s+(' + "|".join(_ACTIONABLE_ROLES) + r')(?:\s+"([^"]*)")?',
    re.MULTILINE,
)
"""Match ``- <role> "name"`` lines in the aria_snapshot. Name is optional."""


def _read_a11y_text(bundle_root: Path, capture: PageCapture) -> str:
    if capture.accessibility_rel is None:
        return ""
    try:
        payload = json.loads(
            (bundle_root / capture.accessibility_rel).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    snap = cast(dict[str, Any], payload).get("aria_snapshot", "")
    return snap if isinstance(snap, str) else ""


def _space_a11y(text: str) -> ActionSpaceMetrics:
    if not text:
        return ActionSpaceMetrics()
    matches = _ACTIONABLE_LINE_RE.findall(text)
    if not matches:
        return ActionSpaceMetrics(actionable_count=0)
    pairs = [(role, name) for role, name in matches]
    unique_pairs = len(set(pairs))
    actionable_count = len(pairs)
    rate = unique_pairs / actionable_count
    return ActionSpaceMetrics(
        actionable_count=actionable_count,
        unique_role_name_rate=rate,
    )


def compute_action_space(
    bundle: PageBundle,
    *,
    bundle_root: Path,
    modalities: tuple[Modality, ...] = ("a11y",),
) -> dict[PageType, dict[Modality, ActionSpaceMetrics]]:
    """Compute action.space metrics across the bundle.

    Only the ``a11y`` modality is implemented in v1; other modalities in
    ``modalities`` produce empty :class:`ActionSpaceMetrics` rows.
    """
    out: dict[PageType, dict[Modality, ActionSpaceMetrics]] = {}
    for capture in bundle.captures:
        per_modality: dict[Modality, ActionSpaceMetrics] = {}
        for modality in modalities:
            if modality == "a11y":
                text = (
                    _read_a11y_text(bundle_root, capture) if capture.applicable else ""
                )
                per_modality[modality] = _space_a11y(text)
            else:
                # Screenshot action-space deferred to a future iteration.
                per_modality[modality] = ActionSpaceMetrics()
        out[capture.page_type] = per_modality
    return out
