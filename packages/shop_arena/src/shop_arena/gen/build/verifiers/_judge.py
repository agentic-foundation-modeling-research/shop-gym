"""Shared helpers for LLM-based build-loop verifiers (spec §5.5.3 + T5.5).

The two LLM verifiers in this package — :class:`QualityJudgeVerifier` and
:class:`CrossTaskConsistencyVerifier` — share the same output contract:
the LLM is asked to emit a single JSON object with two fields
(``verdict`` and ``feedback``) and the verifier translates that into a
:class:`harness.verifiers.VerifierResult`. They also share the source-
block rendering pipeline that turns ``hydrogen/app/**`` into the
``{source_blocks}`` slot of the prompt template, with byte caps applied
so a single oversize file cannot blow the LLM context budget.

This module owns the parser, the runtime guard, and the source-block
rendering helpers so both verifiers stay focused on their applicability
+ prompt-assembly logic.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from harness.runtimes.base import LLMCompleter
from harness.verifiers import Verdict, VerifierResult

_VALID_VERDICTS: Final[frozenset[str]] = frozenset({"pass", "fail"})
"""Verdict tokens the LLM is allowed to emit (lowercase)."""

_FENCE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"```(?:json)?\s*(?P<body>\{.*?\})\s*```",
    re.DOTALL,
)
"""Match the first fenced ```json``` block in a model response."""

_BARE_OBJECT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?P<body>\{.*\})",
    re.DOTALL,
)
"""Match a bare top-level JSON object as a fallback."""


@dataclass(frozen=True, slots=True)
class JudgeOutput:
    """Parsed LLM judge response.

    Attributes:
        verdict: Either :attr:`Verdict.PASS` or :attr:`Verdict.FAIL`.
            ``ADVISORY`` and ``ERROR`` are reserved for the harness;
            judge prompts are gating, so the LLM is asked to pick a
            binary outcome.
        feedback: Free-form markdown body. On ``PASS`` it is allowed to
            be empty; on ``FAIL`` it must be non-empty so the next
            iteration's executor has something to react to.
    """

    verdict: Verdict
    feedback: str


class JudgeParseError(ValueError):
    """Raised when the LLM response cannot be coerced into :class:`JudgeOutput`.

    The verifier catches this and renders an ``ERROR``-shaped FAIL result
    (the LLM is the source of truth and the harness expects a verdict —
    surfacing the malformed body in feedback gives the next iteration's
    executor a chance to react, even though the immediate cause is a
    judge bug rather than an executor bug).
    """


def parse_judge_output(raw: str) -> JudgeOutput:
    """Parse an LLM judge response into :class:`JudgeOutput`.

    The LLM is instructed to emit exactly one JSON object of the shape
    ``{"verdict": "pass" | "fail", "feedback": "..."}``. The parser is
    forgiving about surrounding chatter — it strips leading / trailing
    prose, accepts a fenced ``json`` code block, and finally falls back
    to the first ``{...}`` substring it can find. This keeps the
    contract robust against minor instruction-following slips without
    degrading the gating signal.

    Args:
        raw: Raw model completion text.

    Returns:
        A :class:`JudgeOutput` with a normalized verdict + feedback.

    Raises:
        JudgeParseError: ``raw`` does not contain a JSON object, the
            object is missing a required field, the verdict token is
            not in :data:`_VALID_VERDICTS`, or a ``fail`` verdict has
            an empty ``feedback`` field.
    """
    body = _extract_json_object(raw)
    try:
        payload: Any = json.loads(body)
    except json.JSONDecodeError as exc:
        raise JudgeParseError(
            f"judge response is not valid JSON: {exc.msg} (body={body!r})",
        ) from exc

    if not isinstance(payload, dict):
        raise JudgeParseError(
            f"judge response must be a JSON object; got {type(payload).__name__}",
        )

    payload_dict = cast("dict[str, Any]", payload)
    verdict_raw = payload_dict.get("verdict")
    feedback_raw = payload_dict.get("feedback", "")
    if not isinstance(verdict_raw, str):
        raise JudgeParseError(
            f"judge response is missing a string `verdict` field; got {verdict_raw!r}",
        )
    if not isinstance(feedback_raw, str):
        raise JudgeParseError(
            f"judge response `feedback` field must be a string; got {type(feedback_raw).__name__}",
        )

    verdict_token = verdict_raw.strip().lower()
    if verdict_token not in _VALID_VERDICTS:
        raise JudgeParseError(
            f"judge response `verdict` must be one of {sorted(_VALID_VERDICTS)}; "
            f"got {verdict_raw!r}",
        )

    feedback = feedback_raw.strip()
    if verdict_token == "fail" and not feedback:
        raise JudgeParseError(
            "judge response `verdict` is `fail` but `feedback` is empty; "
            "the next iteration needs a description of the gap",
        )

    verdict = Verdict.PASS if verdict_token == "pass" else Verdict.FAIL
    return JudgeOutput(verdict=verdict, feedback=feedback)


def require_completer(runtime: object, *, verifier_name: str) -> LLMCompleter:
    """Narrow ``runtime`` to :class:`LLMCompleter` or raise.

    ``VerifierContext.runtime`` is the loop's :class:`AgentRuntime`. The
    LLM verifiers need the optional :class:`LLMCompleter` sub-protocol
    too. We treat a runtime without ``complete`` as a wiring bug — the
    build-loop driver is expected to pick a runtime that implements it
    (``replay``, ``claude_code``, ``pi`` all do per
    ``harness.runtimes``).

    Args:
        runtime: Value pulled from ``VerifierContext.runtime``.
        verifier_name: Verifier name surfaced in the error message.

    Returns:
        ``runtime`` typed as :class:`LLMCompleter`.

    Raises:
        TypeError: ``runtime`` does not implement :class:`LLMCompleter`.
    """
    if not isinstance(runtime, LLMCompleter):
        raise TypeError(
            f"{verifier_name} requires a runtime that implements LLMCompleter; "
            f"got {type(runtime).__name__}",
        )
    return runtime


def dispatch_judge(
    completer: LLMCompleter,
    *,
    prompt: str,
    timeout_s: float,
    verifier_name: str,
) -> JudgeOutput | VerifierResult:
    """Run the LLM judge call and parse the verdict.

    Wraps the two failure modes shared by both LLM verifiers — transport
    error (timeout or arbitrary exception) and parse error — so each
    verifier's ``run()`` can stay flat. Successful calls return a
    :class:`JudgeOutput` the verifier maps onto its final
    :class:`~harness.verifiers.VerifierResult`; failure modes are pre-
    rendered as ``FAIL`` results so the verifier can return them
    verbatim.

    Args:
        completer: Pre-narrowed runtime (see :func:`require_completer`).
        prompt: Fully rendered judge prompt body.
        timeout_s: Wall-clock budget in seconds.
        verifier_name: Verifier name surfaced in failure feedback.

    Returns:
        :class:`JudgeOutput` on success;
        :class:`~harness.verifiers.VerifierResult` (verdict ``FAIL``)
        on transport / parse failure.
    """
    try:
        raw = completer.complete(prompt, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback=(
                f"`{verifier_name}` LLM call exceeded the verifier timeout of {timeout_s:.0f}s."
            ),
            details={"timeout_s": timeout_s, "phase": "llm_complete"},
        )
    except Exception as exc:
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback=(f"`{verifier_name}` LLM call raised {type(exc).__name__}: {exc}"),
            details={"phase": "llm_complete", "error": str(exc)},
        )
    try:
        return parse_judge_output(raw)
    except JudgeParseError as exc:
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback=(f"`{verifier_name}` could not parse the LLM verdict. Reason: {exc}"),
            details={"phase": "parse", "raw": raw},
        )


def _extract_json_object(raw: str) -> str:
    """Return the first JSON object body found in ``raw``.

    Tries (in order): a fenced ```json`` block, a fenced ``` block, then
    the first balanced-looking ``{...}`` slice. The fallbacks keep the
    parser robust against minor formatting quirks; an unrecoverable
    response surfaces as :class:`JudgeParseError` further down the
    pipeline.

    Args:
        raw: Raw model response.

    Returns:
        The JSON body as a string (still subject to
        :func:`json.loads` validation).

    Raises:
        JudgeParseError: ``raw`` does not contain a ``{...}`` slice.
    """
    fence_match = _FENCE_PATTERN.search(raw)
    if fence_match is not None:
        return fence_match.group("body")
    bare_match = _BARE_OBJECT_PATTERN.search(raw)
    if bare_match is not None:
        return bare_match.group("body")
    raise JudgeParseError(
        f"judge response does not contain a JSON object; got {raw!r}",
    )


_SOURCE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".tsx", ".ts", ".css", ".md"},
)
"""Source-file extensions reviewed by the LLM judges (spec §5.5.3)."""


def render_source_blocks(
    app_dir: Path,
    *,
    max_bytes_per_file: int,
    max_total_bytes: int,
) -> tuple[str, int, int]:
    """Render the reviewed hydrogen sources as labelled markdown blocks.

    Walks ``app_dir`` in deterministic order (sorted ``rglob``), applies
    the per-file and aggregate byte caps, and returns the rendered
    blocks plus accounting counters used in
    :class:`~harness.verifiers.VerifierResult.details`.

    Args:
        app_dir: ``hydrogen/app/`` directory.
        max_bytes_per_file: Per-file truncation cap.
        max_total_bytes: Aggregate cap across all rendered files.

    Returns:
        ``(blocks, files_reviewed, files_elided)`` — the markdown body,
        the number of files included (in full or truncated), and the
        number of files dropped because the aggregate cap was hit.
    """
    pieces: list[str] = []
    total_bytes = 0
    files_reviewed = 0
    files_elided = 0
    for path in sorted(app_dir.rglob("*")):
        if not path.is_file() or path.suffix not in _SOURCE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        body, _truncated = _truncate_body(text, limit=max_bytes_per_file)
        encoded_size = len(body.encode("utf-8"))
        if total_bytes + encoded_size > max_total_bytes:
            files_elided += 1
            continue
        total_bytes += encoded_size
        files_reviewed += 1
        rel = path.relative_to(app_dir.parent.parent)
        pieces.append(f"### `{rel}`\n\n```\n{body.rstrip()}\n```")

    if files_elided:
        pieces.append(
            f"> {files_elided} additional file(s) elided to stay within the "
            f"{max_total_bytes} byte review budget.",
        )
    if not pieces:
        pieces.append("> The hydrogen `app/` tree contained no reviewable source files.")
    return "\n\n".join(pieces) + "\n", files_reviewed, files_elided


def _truncate_body(text: str, *, limit: int) -> tuple[str, bool]:
    """Truncate ``text`` to ``limit`` UTF-8 bytes with an elision marker.

    Args:
        text: Source body.
        limit: Maximum number of bytes the returned body should encode
            to (excluding the elision marker).

    Returns:
        ``(body, truncated)`` — the (possibly truncated) body plus a
        flag indicating whether truncation happened.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    head = encoded[:limit].decode("utf-8", errors="ignore")
    elided = len(encoded) - limit
    return f"{head}\n... {elided} bytes elided ...\n", True


__all__ = [
    "JudgeOutput",
    "JudgeParseError",
    "dispatch_judge",
    "parse_judge_output",
    "render_source_blocks",
    "require_completer",
]
