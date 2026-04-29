"""Sub-workspace + nested-iteration helper for visual verifiers (impl plan T1.1).

The :class:`~shop_gen.build.verifiers.visual_judge.VisualJudgeVerifier`
(M1) and the final-eval visual sweep (M5) both stage a sub-workspace
under a verifier-owned parent dir, hand it to
``ctx.runtime.run_iteration(...)`` so the agent can drive the
playwright skill, and parse the structured ``verdict.json`` the agent
writes back. Centralising the staging + parse pipeline here keeps both
callers thin and lets us share the score → verdict coercion rules from
spec §9.3.

The forgiving fenced/bare JSON parser mirrors
:func:`shop_gen.build.verifiers._judge.dispatch_judge` so the agent's
output format stays consistent across LLM verifiers (text-only judges
emit ``{"verdict", "feedback"}`` via :mod:`_judge`; visual judges emit
the richer §9.3 schema parsed here).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from harness.runtimes.base import AgentRuntime
from harness.verifiers import Verdict
from shop_gen.build.verifiers._judge import (
    JudgeParseError,
    _extract_json_object,  # pyright: ignore[reportPrivateUsage]
)

_VALID_VERDICT_TOKENS: Final[frozenset[str]] = frozenset({"pass", "fail"})
"""Verdict tokens the agent is allowed to emit (lowercase)."""

_VALID_SEVERITIES: Final[frozenset[str]] = frozenset({"critical", "major", "minor"})
"""Severity tokens the agent is allowed to attach to an issue (§9.3)."""


@dataclass(frozen=True, slots=True)
class VisualIssue:
    """One blocking issue surfaced by the agent's verdict (§9.3).

    Attributes:
        route: Route the issue was observed on (e.g. ``"/collections/outerwear"``).
        viewport: ``"desktop"`` or ``"mobile"``; passed through verbatim.
        screenshot: Path to the screenshot, relative to the sub-workspace.
        severity: One of :data:`_VALID_SEVERITIES`.
        summary: One-line human description.
        capability: Capability key the issue maps to (e.g. ``"collection.filters"``).
    """

    route: str
    viewport: str
    screenshot: str
    severity: str
    summary: str
    capability: str


@dataclass(frozen=True, slots=True)
class VisualVerdict:
    """Parsed structured verdict from a visual judge / sweep iteration.

    Attributes:
        verdict: Final verdict after applying the §9.3 coercion rules
            (``PASS`` or ``FAIL``).
        score: Overall page-bucket quality on a 0-10 scale.
        category_scores: Per-category 0-10 scores; missing keys are
            treated as "not assessed" by the verifier.
        feedback: Agent-emitted markdown body. Empty allowed on PASS.
        pages_judged: Distinct (route, viewport) pairs the agent
            claims to have rendered.
        issues: Severity-tagged issue list (§9.3). Empty tuple when
            the agent reported no issues.
        coercion_reason: ``None`` when :attr:`verdict` matches the
            agent's emitted token; otherwise a short string explaining
            why the parser coerced ``pass`` → ``fail`` (score below
            threshold or critical-severity issue). The verifier
            surfaces this in feedback so the next iteration sees why
            the gate flipped.
    """

    verdict: Verdict
    score: float
    category_scores: Mapping[str, float]
    feedback: str
    pages_judged: int
    issues: tuple[VisualIssue, ...]
    coercion_reason: str | None = None


def stage_sub_workspace(
    parent_dir: Path,
    *,
    prompt: str,
    routes: Mapping[str, Any],
) -> Path:
    """Lay out the sub-workspace handed to ``runtime.run_iteration``.

    Creates ``<parent_dir>/work/{prompt.md, routes.json, iter/}``. The
    runtime is expected to write its native log + screenshots into
    ``iter/`` and the agent writes ``verdict.json`` next to
    ``prompt.md`` (per spec §5.2.1 step 4).

    Args:
        parent_dir: Caller-owned dir under
            ``iters/<id>/checks/verifiers/visual_judge/`` (build loop)
            or ``<out_dir>/visual_eval/`` (final eval).
        prompt: Fully rendered prompt body, written verbatim to
            ``work/prompt.md``.
        routes: Route list + base URL + capability slice handed to
            the agent. Serialised as deterministic JSON (sorted keys,
            2-space indent) into ``work/routes.json``.

    Returns:
        Absolute path to the ``work/`` directory.
    """
    work = parent_dir / "work"
    iter_dir = work / "iter"
    iter_dir.mkdir(parents=True, exist_ok=True)
    (work / "prompt.md").write_text(prompt, encoding="utf-8")
    (work / "routes.json").write_text(
        json.dumps(routes, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return work


def parse_visual_verdict(  # noqa: PLR0911, PLR0912 - one early-return per §9.3 schema field, intentionally explicit
    verdict_path: Path,
    *,
    pass_threshold: float,
) -> VisualVerdict | None:
    """Parse the agent-written ``verdict.json`` per spec §9.3.

    Mirrors :func:`shop_gen.build.verifiers._judge.dispatch_judge`'s
    forgiving-parse pipeline (fenced ``json`` block, bare ``{...}``
    fallback). Returns ``None`` for any structural failure — missing
    file, malformed JSON, missing required keys, or an unrecognised
    verdict / severity token. The verifier maps ``None`` to a
    :attr:`~harness.verifiers.Verdict.FAIL` with a diagnostic
    pointing at the on-disk body.

    Applies the §9.3 score → verdict coercion rules on top of the
    agent's emitted token:

    - Any ``severity: "critical"`` issue forces ``verdict=fail``.
    - ``score < pass_threshold`` coerces ``verdict=pass`` to ``fail``.

    Coercion never *upgrades* a fail to pass — the score and severity
    only tighten the gate.

    Args:
        verdict_path: Path to the agent-written ``verdict.json``.
        pass_threshold: Minimum overall score for a ``pass`` token to
            survive coercion (typically 7.0 — see
            :attr:`shop_gen.config.ShopGenConfig.visual_judge_pass_threshold`
            once landed).

    Returns:
        A :class:`VisualVerdict` on success; ``None`` if the file is
        missing or the body cannot be coerced into the §9.3 schema.
    """
    try:
        raw = verdict_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        body = _extract_json_object(raw)
    except JudgeParseError:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    payload_dict = cast("dict[str, Any]", payload)

    verdict_token = _coerce_verdict_token(payload_dict.get("verdict"))
    if verdict_token is None:
        return None

    score = _coerce_number(payload_dict.get("score"))
    if score is None:
        return None

    pages_raw = payload_dict.get("pages_judged")
    if not isinstance(pages_raw, int) or isinstance(pages_raw, bool) or pages_raw < 0:
        return None
    pages_judged = pages_raw

    feedback_raw = payload_dict.get("feedback", "")
    if not isinstance(feedback_raw, str):
        return None

    category_scores = _coerce_category_scores(payload_dict.get("category_scores", {}))
    if category_scores is None:
        return None

    issues = _coerce_issues(payload_dict.get("issues", []))
    if issues is None:
        return None

    final_verdict = Verdict.PASS if verdict_token == "pass" else Verdict.FAIL
    coercion_reason: str | None = None
    if final_verdict is Verdict.PASS:
        if any(issue.severity == "critical" for issue in issues):
            final_verdict = Verdict.FAIL
            coercion_reason = "critical-severity issue forces fail"
        elif score < pass_threshold:
            final_verdict = Verdict.FAIL
            coercion_reason = f"score {score:.2f} < pass_threshold {pass_threshold:.2f}"

    return VisualVerdict(
        verdict=final_verdict,
        score=score,
        category_scores=category_scores,
        feedback=feedback_raw,
        pages_judged=pages_judged,
        issues=issues,
        coercion_reason=coercion_reason,
    )


def run_visual_iteration(
    runtime: AgentRuntime,
    *,
    parent_dir: Path,
    prompt: str,
    routes: Mapping[str, Any],
    timeout_s: float,
    pass_threshold: float,
) -> tuple[Path, VisualVerdict | None]:
    """Stage a sub-workspace, run the nested iteration, parse the verdict.

    The runtime call uses ``run_dir=work``, ``iter_dir=work/iter`` to
    match spec §5.2.1 step 5; both directories exist before the call.
    The verifier does not prepend the harness ``<<<harness-control>>>``
    header — this is a one-shot, plan-less invocation.

    Args:
        runtime: Agent runtime instance from
            :attr:`harness.verifiers.VerifierContext.runtime`.
        parent_dir: Verifier-owned parent dir for the sub-workspace.
        prompt: Fully rendered prompt body.
        routes: Route + capability payload written to ``routes.json``.
        timeout_s: Wall-clock budget for the nested iteration.
        pass_threshold: Score floor for the §9.3 coercion rule.

    Returns:
        ``(work_dir, verdict)`` — the sub-workspace path and the
        parsed verdict (``None`` when ``verdict.json`` is missing or
        malformed; the verifier renders a diagnostic FAIL in that
        case).

    Raises:
        subprocess.TimeoutExpired: Propagated from the runtime when
            the nested iteration exceeds ``timeout_s``.
    """
    work = stage_sub_workspace(parent_dir, prompt=prompt, routes=routes)
    runtime.run_iteration(
        run_dir=work,
        iter_dir=work / "iter",
        prompt=prompt,
        timeout=timeout_s,
    )
    verdict = parse_visual_verdict(
        work / "verdict.json",
        pass_threshold=pass_threshold,
    )
    return work, verdict


def _coerce_verdict_token(value: Any) -> str | None:
    """Return a normalised verdict token or ``None`` if invalid."""
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    if token not in _VALID_VERDICT_TOKENS:
        return None
    return token


def _coerce_number(value: Any) -> float | None:
    """Return ``value`` as a float or ``None`` if it is not numeric.

    Booleans are rejected even though they are technically ``int``
    instances — a JSON document with ``"score": true`` is malformed.
    """
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    return float(value)


def _coerce_category_scores(value: Any) -> dict[str, float] | None:
    """Validate the ``category_scores`` sub-object."""
    if not isinstance(value, dict):
        return None
    out: dict[str, float] = {}
    for raw_key, raw_value in cast("dict[Any, Any]", value).items():
        if not isinstance(raw_key, str):
            return None
        coerced = _coerce_number(raw_value)
        if coerced is None:
            return None
        out[raw_key] = coerced
    return out


def _coerce_issues(value: Any) -> tuple[VisualIssue, ...] | None:
    """Validate the ``issues`` array, rejecting unknown severity tokens."""
    if not isinstance(value, list):
        return None
    out: list[VisualIssue] = []
    for entry in cast("list[Any]", value):
        if not isinstance(entry, dict):
            return None
        entry_dict = cast("dict[str, Any]", entry)
        severity_raw = entry_dict.get("severity")
        if not isinstance(severity_raw, str) or severity_raw not in _VALID_SEVERITIES:
            return None
        out.append(
            VisualIssue(
                route=_string_or_empty(entry_dict.get("route")),
                viewport=_string_or_empty(entry_dict.get("viewport")),
                screenshot=_string_or_empty(entry_dict.get("screenshot")),
                severity=severity_raw,
                summary=_string_or_empty(entry_dict.get("summary")),
                capability=_string_or_empty(entry_dict.get("capability")),
            ),
        )
    return tuple(out)


def _string_or_empty(value: Any) -> str:
    """Return ``value`` if it is a string, else the empty string.

    The non-severity issue fields are descriptive — a missing route or
    summary is annoying for the human reading ``feedback.md`` but not
    structurally invalid, so we soften it to ``""`` rather than
    rejecting the whole verdict.
    """
    return value if isinstance(value, str) else ""


__all__ = [
    "VisualIssue",
    "VisualVerdict",
    "parse_visual_verdict",
    "run_visual_iteration",
    "stage_sub_workspace",
]
