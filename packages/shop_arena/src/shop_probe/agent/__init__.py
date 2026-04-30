"""Capture-judge support: one provider call per rubric entry.

The capture-judge tier is an axis-A extension that handles affordances
deterministic Playwright probes can't decide (e.g. "does this page expose
a sort dropdown?"). For each ``level: capture_judge`` rubric entry the
dispatcher hands the bundle slice + rubric question to
:func:`shop_probe.agent.judge.run_capture_judge`, which routes to
either the Anthropic Messages API or the OpenAI Chat Completions API
based on the ``<provider>:<model>`` prefix on the model id.

This module is import-safe: it performs no I/O at import time.
"""

from __future__ import annotations

from shop_probe.agent.judge import JudgeVerdict, run_capture_judge

__all__ = [
    "JudgeVerdict",
    "run_capture_judge",
]
