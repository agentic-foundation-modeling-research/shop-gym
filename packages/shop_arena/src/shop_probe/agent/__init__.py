"""Capture-judge support: one Anthropic Messages call per rubric entry.

The capture-judge tier is an axis-A extension that handles affordances
deterministic Playwright probes can't decide (e.g. "does this page expose
a sort dropdown?"). For each ``level: capture_judge`` rubric entry the
dispatcher hands the bundle slice + rubric question to
:func:`shop_probe.agent.judge.run_capture_judge`.

This module is import-safe: it performs no I/O at import time.
"""

from __future__ import annotations

from shop_probe.agent.judge import JudgeVerdict, run_capture_judge

__all__ = [
    "JudgeVerdict",
    "run_capture_judge",
]
