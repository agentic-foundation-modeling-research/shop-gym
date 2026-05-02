"""Screenshot-based LLM judge for ShopGuru tasks.

Uses the OpenAI SDK against an optional ``base_url``; when unset the
SDK reads ``OPENAI_BASE_URL`` from the environment (populated from
the project ``.env`` — see :mod:`shop_guru._dotenv`). The same call
path therefore works for OpenAI proper or any OpenAI-compatible
endpoint. Returns a structured ``JudgementResult``.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# Transient proxy/LLM failures worth retrying (e.g. Cloudflare 1102
# from a private gateway surfaces as InternalServerError). Name-based
# match so the openai import stays lazy.
_RETRIABLE_EXC_NAMES = frozenset(
    {
        "InternalServerError",
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "APIError",
    }
)


def _resize_b64_png(b64_png: str, scale: float = 0.5) -> str:
    """Decode a base64 PNG, resize by ``scale`` on each axis, re-encode as base64 PNG.

    Returns the original string unchanged on any failure. ``scale`` outside
    (0, 1) is a no-op.
    """
    if not b64_png or scale <= 0 or scale >= 1:
        return b64_png
    try:
        from PIL import Image

        raw = base64.b64decode(b64_png)
        with Image.open(io.BytesIO(raw)) as img:
            new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            resized = img.resize(new_size, Image.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format="PNG", optimize=True)
            return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        logger.debug("screenshot resize failed (%s); using original", exc)
        return b64_png


class JudgementResult(BaseModel):
    # Parsed fields returned by the judge LLM.
    reasoning: str | None = Field(default=None, description="Explanation of the judgement")
    verdict: bool = Field(description="Whether the trace was successful or not")
    failure_reason: str | None = Field(
        default=None, description="Why the task was not completed successfully"
    )
    impossible_task: bool = Field(
        default=False, description="True if task was impossible to complete"
    )
    reached_captcha: bool = Field(
        default=False, description="True if agent encountered captcha"
    )

    # Full response metadata — preserved so every run keeps the complete
    # evidence trail (raw LLM text, model, token counts, finish reason,
    # any extra JSON fields the LLM emitted). Anything set here lands in
    # `task_info["judgement"]` verbatim via `model_dump()`.
    raw_response: str | None = Field(
        default=None, description="Raw message.content string returned by the judge LLM"
    )
    raw_payload: dict[str, Any] | None = Field(
        default=None,
        description="Parsed JSON payload from the judge LLM (superset of the typed fields)",
    )
    model_used: str | None = Field(
        default=None, description="Judge model name (what was actually sent to the API)"
    )
    finish_reason: str | None = Field(
        default=None, description="OpenAI-compatible finish_reason from the judge response"
    )
    usage: dict[str, Any] | None = Field(
        default=None, description="Token usage dict from the judge response (if provided)"
    )
    error: str | None = Field(
        default=None,
        description="If the judge call or parse failed, the error summary (else None)",
    )
    prompt_messages: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "The chat-completion messages sent to the judge, preserved "
            "verbatim except that each image block's base64 data URL is "
            "replaced with a `<redacted:base64-png:<bytes>-bytes>` marker. "
            "Block shape stays OpenAI-compatible (`type: image_url`, "
            "`image_url.url`) so a failed verdict can be inspected from "
            "summary_info.json alone."
        ),
    )


def _truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 20] + "...[truncated]..."


def _format_url_trajectory(url_trajectory: list[tuple[int, str]] | None) -> str:
    """Render the URL list as a numbered log."""
    if not url_trajectory:
        return ""
    lines = [f"{step:>3d}. {url}" for step, url in url_trajectory]
    return "\n".join(lines)


def _redact_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of the chat-completion messages with image payloads stripped.

    Preserves the exact shape of what was sent to the judge — each image
    block keeps ``type: "image_url"`` and an ``image_url.url`` string —
    but swaps the base64 blob for a short ``<redacted:base64-png:<size>-bytes>``
    marker. The redacted copy is safe to log at INFO and is persisted on
    ``JudgementResult.prompt_messages`` so a failed verdict can be
    reproduced from ``summary_info.json`` alone.
    """
    redacted: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            new_content: list[dict[str, Any]] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "image_url":
                    image_url = block.get("image_url") or {}
                    url = image_url.get("url", "")
                    marker = f"<redacted:base64-png:{len(url)}-bytes>"
                    new_block = dict(block)
                    new_block["image_url"] = {**image_url, "url": marker}
                    new_content.append(new_block)
                else:
                    new_content.append(block)
            redacted.append({**msg, "content": new_content})
        else:
            redacted.append(msg)
    return redacted


def _build_messages(
    task: str,
    final_result: str,
    agent_steps: list[str],
    screenshots_b64: list[str],
    max_images: int,
    url_trajectory: list[tuple[int, str]] | None = None,
) -> list[dict[str, Any]]:
    task_truncated = _truncate(task, 40_000)
    final_result_truncated = _truncate(final_result, 40_000)
    steps_text_truncated = _truncate("\n".join(agent_steps), 40_000)
    url_trajectory_text = _truncate(_format_url_trajectory(url_trajectory), 40_000)

    # Dedupe while preserving chronological order, then keep the last max_images.
    seen: set[str] = set()
    unique_reversed = [s for s in reversed(screenshots_b64) if s not in seen and not seen.add(s)]
    selected = list(reversed(unique_reversed[:max_images]))

    system_prompt = """You are an expert judge evaluating browser automation agent performance.

<evaluation_framework>
**PRIMARY EVALUATION CRITERIA (in order of importance):**
1. **Task Satisfaction (Most Important)**: Did the agent accomplish what the user asked for? Break down the task into the key criteria and evaluate if the agent all of them. Focus on user intent and final outcome.
2. **Output Quality**: Is the final result in the correct format and complete? Does it match exactly what was requested?
3. **Tool Effectiveness**: Did the browser interactions work as expected? Were tools used appropriately? How many % of the tools failed?
4. **Agent Reasoning**: Quality of decision-making, planning, and problem-solving throughout the trajectory.
5. **Browser Handling**: Navigation stability, error recovery, and technical execution. If the browser crashes, does not load or a captcha blocks the task, the score must be very low.

**VERDICT GUIDELINES:**
- true: Task completed as requested, human-like execution, all of the users criteria were met and the agent did not make up any information.
- false: Task not completed, or only partially completed.

**Examples of task completion verdict:**
- If task asks for 10 items and agent finds 4 items correctly: false
- If task completed to full user requirements but with some errors to improve in the trajectory: true
- If task impossible due to captcha/login requirements: false
- If the trajectory is ideal and the output is perfect: true
- If the task asks to search all headphones on a marketplace under $100 but the agent searches all headphones and the lowest price is $150: false
- If the task asks to research a property and create a google doc with the result but the agents only returns the results in text: false
- If the task asks to complete an action on the page, and the agent reports that the action is completed but the screenshot or page shows the action is not actually complete: false
- If the task asks to use a certain tool or site to complete the task but the agent completes the task without using it: false
- If the task asks to look for a section of a page that does not exist: false
- If the agent concludes the task is impossible but it is not: false
- If the agent concludes the task is impossible and it truly is impossible: false
- If the agent is unable to complete the task because no login information was provided and it is truly needed to complete the task: false

**FAILURE CONDITIONS (automatically set verdict to false):**
- Blocked by captcha or missing authentication
- Output format completely wrong or missing
- Infinite loops or severe technical failures
- Critical user requirements ignored
- Page not loaded
- Browser crashed
- Agent could not interact with required UI elements
- The agent moved on from a important step in the task without completing it
- The agent made up content that is not in the screenshot or the page state
- The agent calls done action before completing all key points of the task

**IMPOSSIBLE TASK DETECTION:**
Set `impossible_task` to true when the task fundamentally could not be completed due to:
- Vague or ambiguous task instructions that cannot be reasonably interpreted
- Website genuinely broken or non-functional (be conservative - temporary issues don't count)
- Required links/pages truly inaccessible (404, 403, etc.)
- Task requires authentication/login but no credentials were provided
- Task asks for functionality that doesn't exist on the target site
- Other insurmountable external obstacles beyond the agent's control

Do NOT mark as impossible if:
- Agent made poor decisions but task was achievable
- Temporary page loading issues that could be retried
- Agent didn't try the right approach
- Website works but agent struggled with it

**CAPTCHA DETECTION:**
Set `reached_captcha` to true if:
- Screenshots show captcha challenges (reCAPTCHA, hCaptcha, etc.)
- Agent reports being blocked by bot detection
- Error messages indicate captcha/verification requirements
- Any evidence the agent encountered anti-bot measures during execution

**IMPORTANT EVALUATION NOTES:**
- **evaluate for action** - For each key step of the trace, double check whether the action that the agent tried to performed actually happened. If the required action did not actually occur, the verdict should be false.
- **screenshot is not entire content** - The agent has the entire DOM content, but the screenshot is only part of the content. If the agent extracts information from the page, but you do not see it in the screenshot, you can assume this information is there.
- **Penalize poor tool usage** - Wrong tools, inefficient approaches, ignoring available information.
- **ignore unexpected dates and times** - These agent traces are from varying dates, you can assume the dates the agent uses for search or filtering are correct.
- **IMPORTANT**: be very picky about the user's request - Have very high standard for the agent completing the task exactly to the user's request.
- **IMPORTANT**: be initially doubtful of the agent's self reported success, be sure to verify that its methods are valid and fulfill the user's desires to a tee.

</evaluation_framework>

<response_format>
Respond with EXACTLY this JSON structure (no additional text before or after):

{
    "reasoning": "Breakdown of user task into key points. Detailed analysis covering: what went well, what didn't work, trajectory quality assessment, tool usage evaluation, output quality review, and overall user satisfaction prediction.",
    "verdict": true or false,
    "failure_reason": "Max 5 sentences explanation of why the task was not completed successfully in case of failure. If verdict is true, use an empty string.",
    "impossible_task": true or false,
    "reached_captcha": true or false
}
</response_format>
"""

    url_trajectory_section = ""
    if url_trajectory_text:
        url_trajectory_section = f"""
<url_trajectory>
List of page URLs the browser landed on during the episode, in order,
one entry per validate() call (repeats are preserved so you can see how
long the agent dwelled on each page). Format: "<step_index>. <url>".
Use this as the authoritative record of which URLs the agent visited.
Absence of a URL here means the agent did not land on it at any step.
{url_trajectory_text}
</url_trajectory>
"""

    user_prompt = f"""
<task>
{task_truncated or 'No task provided'}
</task>

<agent_trajectory>
{steps_text_truncated or 'No agent trajectory provided'}
</agent_trajectory>
{url_trajectory_section}
<final_result>
{final_result_truncated or 'No final result provided'}
</final_result>

{len(selected)} screenshots from execution are attached.

Evaluate this agent execution given the criteria and respond with the exact JSON structure requested."""

    user_content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for img in selected:
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img}"},
            }
        )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def judge_trace(
    task: str,
    final_result: str,
    agent_steps: list[str],
    screenshots_b64: list[str],
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
    max_images: int = 10,
    url_trajectory: list[tuple[int, str]] | None = None,
    image_scale: float = 1.0,
) -> JudgementResult:
    """Run the screenshot-based judge against an agent trajectory.

    Uses the OpenAI SDK with the optional ``base_url``; when ``None``
    the SDK reads ``OPENAI_BASE_URL`` from the environment. An explicit
    JSON response format is requested. On any failure to parse the LLM
    output, returns a ``verdict=False`` result with the error captured
    in ``failure_reason``.

    On transient proxy/LLM errors (e.g. Cloudflare 1102 "Worker
    exceeded resource limits" from a private gateway), retries with
    ``max_images`` reduced by 2 each attempt until the call succeeds
    or the image budget is exhausted.
    """
    # Imported lazily so the eval subpackage stays importable even if the
    # openai wheel isn't installed (e.g. during the shop_guru-build path).
    from openai import OpenAI

    # Resize once upfront — downscaled images cut tokens across every
    # retry without re-doing the PIL work each attempt. Skip entirely
    # at scale=1 (or outside (0, 1)) so the default path avoids the
    # PIL decode/encode round-trip.
    if 0 < image_scale < 1:
        resized_screenshots = [_resize_b64_png(s, image_scale) for s in screenshots_b64]
    else:
        resized_screenshots = screenshots_b64

    client_kwargs: dict[str, Any] = {
        "api_key": api_key or os.environ.get("OPENAI_API_KEY"),
    }
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)

    current_max = max_images
    attempt = 0
    response = None
    redacted_messages: list[dict[str, Any]] = []

    while True:
        messages = _build_messages(
            task=task,
            final_result=final_result,
            agent_steps=agent_steps,
            screenshots_b64=resized_screenshots,
            max_images=current_max,
            url_trajectory=url_trajectory,
        )

        # Log the full prompt we're sending to the judge so failed verdicts
        # can be diagnosed from experiment.log without digging into pickles.
        # b64 image payloads are replaced with size markers to keep the log
        # human-readable. The same redacted copy is attached to the returned
        # JudgementResult so it persists to summary_info.json.
        redacted_messages = _redact_images(messages)
        logger.debug(
            "[shop_guru.judge] sending messages to judge model=%s base_url=%s "
            "attempt=%d max_images=%d payload=%s",
            model,
            base_url,
            attempt,
            current_max,
            json.dumps(redacted_messages, default=str),
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            break
        except Exception as exc:
            retriable = type(exc).__name__ in _RETRIABLE_EXC_NAMES
            if not retriable or current_max <= 0:
                logger.exception("judge LLM call failed")
                return JudgementResult(
                    verdict=False,
                    reasoning=None,
                    failure_reason=f"judge LLM call failed: {type(exc).__name__}: {exc}",
                    model_used=model,
                    error=f"{type(exc).__name__}: {exc}",
                    prompt_messages=redacted_messages,
                )
            next_max = max(0, current_max - 2)
            logger.warning(
                "judge LLM call failed (attempt=%d max_images=%d): %s: %s; "
                "retrying with max_images=%d",
                attempt,
                current_max,
                type(exc).__name__,
                exc,
                next_max,
            )
            current_max = next_max
            attempt += 1
            continue

    choice = response.choices[0]
    raw = choice.message.content or ""
    finish_reason = getattr(choice, "finish_reason", None)
    usage = None
    if response.usage is not None:
        try:
            usage = response.usage.model_dump()
        except Exception:
            usage = dict(response.usage) if hasattr(response.usage, "__iter__") else None

    common_meta: dict[str, Any] = {
        "raw_response": raw,
        "model_used": model,
        "finish_reason": finish_reason,
        "usage": usage,
        "prompt_messages": redacted_messages,
    }

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("judge returned non-JSON payload: %s", raw[:500])
        return JudgementResult(
            verdict=False,
            reasoning=None,
            failure_reason=f"judge returned non-JSON payload: {exc}",
            error=f"JSONDecodeError: {exc}",
            **common_meta,
        )

    try:
        result = JudgementResult.model_validate(payload)
    except Exception as exc:
        logger.warning("judge payload failed schema validation: %s", payload)
        return JudgementResult(
            verdict=False,
            reasoning=None,
            failure_reason=f"judge payload failed schema validation: {exc}",
            raw_payload=payload if isinstance(payload, dict) else None,
            error=f"{type(exc).__name__}: {exc}",
            **common_meta,
        )

    # Fill in the metadata fields that the LLM's JSON didn't carry.
    result.raw_response = raw
    result.raw_payload = payload if isinstance(payload, dict) else None
    result.model_used = model
    result.finish_reason = finish_reason
    result.usage = usage
    result.prompt_messages = redacted_messages
    return result
