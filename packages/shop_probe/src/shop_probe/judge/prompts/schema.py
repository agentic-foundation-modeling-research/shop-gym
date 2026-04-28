"""Closed schema for the axis-C pairwise judge prompt template (T4.7).

Implements the typed contract for ``judge/prompts/v1/system.md`` +
``judge/prompts/v1/pairwise.md`` referenced by
``docs/specs/shop_arena/web_probe.md`` §5.5 step 5 + §8.3 + §5.8:

* :class:`JudgePromptSet` — the loaded, hashed prompt template
  (``version`` + ``system_template`` + ``pairwise_template`` +
  ``content_hash``); pinned per :class:`shop_probe.report.JudgeCall` via
  ``prompt_hash`` so every pairwise call is reproducible (spec §5.8).

The pairwise template uses ``string.Template``-style ``$placeholders``
rather than ``str.format``-style ``{}`` placeholders because the prompt
body itself contains literal JSON braces describing the required
response shape. The placeholders enforced at load time are:

* ``$task_description``        — natural-language task from
                                  ``judge/tasks/v1.yaml`` (spec §5.5
                                  step 1).
* ``$anonymized_trajectory_a`` — first trajectory in randomized A/B
                                  order (spec §5.5 step 5).
* ``$anonymized_trajectory_b`` — second trajectory in randomized A/B
                                  order (spec §5.5 step 5).

Per spec §5.5 step 5 the prompt is *identical* for experimental
``(sandbox, source)`` pairs and control ``(real, real)`` pairs — the
template body must not branch on condition. Tests pin this invariant.

The model sets ``extra="forbid"`` and ``frozen=True``: the prompt is
content-addressable and must round-trip exactly. The module is
import-safe — it performs no I/O at import time. Filesystem loading
lives in :mod:`shop_probe.judge.prompts.loader`.
"""

from __future__ import annotations

import re
from string import Template

from pydantic import BaseModel, ConfigDict, Field, model_validator

REQUIRED_PAIRWISE_PLACEHOLDERS: tuple[str, ...] = (
    "task_description",
    "anonymized_trajectory_a",
    "anonymized_trajectory_b",
)
"""Placeholders the pairwise template must expose (spec §8.3).

Enforced at validation time. New required placeholders bump the
template version per spec §5.8 so every :class:`JudgeCall` continues
to pin the exact template revision used at run time.
"""


class JudgePromptSet(BaseModel):
    """A loaded, validated, content-hashed pairwise judge prompt template.

    The ``content_hash`` field is a SHA-256 hex digest over the
    canonical UTF-8 bytes of the source files (see
    :func:`shop_probe.judge.prompts.loader.compute_content_hash` for the
    canonical byte form). It pins a specific prompt template revision
    into every :class:`shop_probe.report.JudgeCall` so judge calls can
    be re-attributed unambiguously (spec §5.8).

    Attributes:
        version: Prompt template version string, e.g. ``"v1"``. Frozen
            per spec §5.8 — changes bump this.
        content_hash: 64-char lowercase hex SHA-256 over the canonical
            byte form of the source files. Reviewers reproducing the
            report recompute this and compare.
        system_template: Verbatim contents of ``system.md`` (spec §8.3
            SYSTEM block). Static; no placeholders.
        pairwise_template: Verbatim contents of ``pairwise.md`` (spec
            §8.3 USER block). Must expose every placeholder in
            :data:`REQUIRED_PAIRWISE_PLACEHOLDERS`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    system_template: str = Field(min_length=1)
    pairwise_template: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_required_placeholders(self) -> JudgePromptSet:
        """Reject pairwise templates missing a required placeholder."""
        identifiers = _extract_identifiers(self.pairwise_template)
        missing = tuple(p for p in REQUIRED_PAIRWISE_PLACEHOLDERS if p not in identifiers)
        if missing:
            msg = (
                f"judge prompt {self.version!r}: pairwise template missing "
                f"required placeholder(s) {list(missing)}"
            )
            raise ValueError(msg)
        return self

    def render_pairwise(
        self,
        *,
        task_description: str,
        anonymized_trajectory_a: str,
        anonymized_trajectory_b: str,
    ) -> str:
        """Render the pairwise template with the given trajectory pair.

        Substitution uses :class:`string.Template`'s ``safe_substitute``
        semantics with explicit kwargs — unused placeholders raise, and
        literal JSON braces in the template body are passed through
        verbatim.

        Args:
            task_description: Task prompt from ``judge/tasks/v1.yaml``.
            anonymized_trajectory_a: Anonymized trajectory shown in slot
                ``"A"`` (spec §5.5 step 3 + step 5).
            anonymized_trajectory_b: Anonymized trajectory shown in slot
                ``"B"`` (spec §5.5 step 3 + step 5).

        Returns:
            The rendered user-prompt body, ready to send as the user
            turn alongside :attr:`system_template`.

        Raises:
            KeyError: The template references a placeholder beyond the
                three required identifiers (spec §8.3).
        """
        return Template(self.pairwise_template).substitute(
            task_description=task_description,
            anonymized_trajectory_a=anonymized_trajectory_a,
            anonymized_trajectory_b=anonymized_trajectory_b,
        )


_TEMPLATE_PATTERN: re.Pattern[str] = Template.pattern  # type: ignore[attr-defined]
"""Compiled regex used by :class:`string.Template` to find ``$``-placeholders.

Re-used here so identifier extraction stays consistent with substitution.
"""


def _extract_identifiers(template: str) -> frozenset[str]:
    """Return the set of placeholder identifiers in a Template body.

    Mirrors :class:`string.Template` parsing: matches both ``$name`` and
    ``${name}`` forms, ignores escapes (``$$``) and invalid identifiers.

    Args:
        template: Raw template body.

    Returns:
        Frozen set of identifier names, with no duplicates.
    """
    found: set[str] = set()
    for match in _TEMPLATE_PATTERN.finditer(template):
        named = match.group("named") or match.group("braced")
        if named:
            found.add(named)
    return frozenset(found)
