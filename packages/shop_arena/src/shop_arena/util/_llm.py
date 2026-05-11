"""Provider-agnostic vision LLM client shared across shop_arena CLIs.

Callers need exactly one LLM behaviour: send a PNG plus a short prompt and
get back a JSON object that conforms to a closed schema. The first consumer
is EnvEval's screenshot rubric
(:mod:`shop_arena.env_eval.observation.rubric`), which validates the parsed
mapping against a pydantic model and persists the raw response for audit.
A text-only sibling (:meth:`LLMVisionClient.call_text`) issues the same
structured-output request without image inputs; it backs
:mod:`shop_arena.env_eval.transition.pages_classifier`, which classifies
``/pages/<slug>`` URLs from path strings alone.

This module only owns:

* :class:`LLMVisionClient` — the narrow Protocol callers depend on.
* :class:`VisionResponse` — the parsed-or-not return shape (raw text +
  parsed mapping + structured parse errors).
* :class:`_AnthropicVisionClient` — Claude implementation; uses the
  ``messages`` tool-use API with ``tool_choice={"type": "tool", "name": ...}``
  to force the model to emit a single tool call whose ``input`` matches the
  supplied schema.  The tool input is the parsed mapping; a JSON encoding of
  the same dict is the raw response.
* :class:`_OpenAIVisionClient` — OpenAI implementation; uses the chat
  completions API in ``response_format={"type": "json_schema", ...}`` mode so
  the assistant message is JSON we can parse directly.
* :func:`build_default_client` — dispatcher that maps a model id to a
  provider implementation by prefix (impl-plan M0):
  ``claude-*`` → Anthropic, ``gpt-*`` / ``o1*`` / ``o3*`` / ``o4*`` →
  OpenAI.  The dispatcher fails loudly when credentials are missing or when
  a chosen model is on the closed text-only deny list.

Both implementations defer SDK construction until the first :meth:`call`.
That keeps ``build_default_client()`` cheap, lets tests inject a fake
``client_factory``, and avoids touching the network at import time.

This module is intentionally thin: no streaming, no token accounting —
those concerns belong to the call-site (the rubric caches the artifact
on disk so a successful run is the only retry budget that matters). The
single concession is :func:`_retry_on_rate_limit`, which layers explicit
multi-second waits on top of the SDKs' default backoff so a vision burst
across a cohort of shops can survive the proxy's per-minute window
without manual re-runs.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from base64 import b64encode
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = [
    "DEFAULT_RUBRIC_TEMPERATURE",
    "LLMConfigError",
    "LLMVisionClient",
    "VisionResponse",
    "build_default_client",
]

#: Environment variable holding the Anthropic API key (mirrors the SDK).
_ANTHROPIC_API_KEY_ENV: Final[str] = "ANTHROPIC_API_KEY"

#: Environment variable holding the OpenAI API key (mirrors the SDK).
_OPENAI_API_KEY_ENV: Final[str] = "OPENAI_API_KEY"
#: Default sampling temperature for the screenshot rubric (spec §5.3 — "Calls
#: use temperature ``0`` where the provider supports it").  Exposed as a
#: module-level constant so the rubric layer (M2) and tests share a single
#: source of truth; provider-side fixed-temperature models (see
#: :data:`_OPENAI_FIXED_TEMPERATURE_RE`) silently drop the kwarg instead of
#: erroring at the API boundary.
DEFAULT_RUBRIC_TEMPERATURE: Final[float] = 0.0

#: Hardcoded JSON tool name used by :class:`_AnthropicVisionClient`.  Anthropic
#: requires every tool to have a name; the rubric never branches on it, so
#: keeping a constant makes the wire payload byte-stable across runs.
_ANTHROPIC_TOOL_NAME: Final[str] = "emit_rubric"

#: Closed deny list of model ids the dispatcher refuses to use because they
#: do not support image inputs. The list is intentionally explicit (no regex) so a
#: typo in a CLI flag fails loudly at dispatch time rather than silently
#: degrading at the API boundary.  Newer Claude/OpenAI models support vision
#: by default and need no entry here.
_NON_VISION_MODELS: Final[frozenset[str]] = frozenset(
    {
        # OpenAI text-only.
        "gpt-3.5-turbo",
        "gpt-3.5-turbo-16k",
        "gpt-4",
        "gpt-4-0314",
        "gpt-4-0613",
        "gpt-4-32k",
        "gpt-4-32k-0314",
        "gpt-4-32k-0613",
        "o1-mini",
        "o1-mini-2024-09-12",
        "o3-mini",
        "o3-mini-2025-01-31",
        # Anthropic text-only (claude-1 / claude-2 / instant).
        "claude-1",
        "claude-2",
        "claude-2.0",
        "claude-2.1",
        "claude-instant-1",
        "claude-instant-1.2",
    }
)

#: Anthropic prefix dispatched to :class:`_AnthropicVisionClient`.
_ANTHROPIC_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"^claude[-.]")

#: OpenAI prefixes dispatched to :class:`_OpenAIVisionClient`.  Reasoning
#: models (``o1``/``o3``/``o4``) share the chat completions surface used by
#: ``gpt-*`` so they route to the same client.
_OPENAI_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"^(gpt-|o1[-.]?|o3[-.]?|o4[-.]?|chatgpt-)")

#: OpenAI model ids that only accept the *default* sampling temperature and
#: reject explicit ``temperature`` values (including ``0``) at the API
#: boundary.  EnvEval drops the ``temperature`` kwarg for these models so
#: spec §5.3's "temperature ``0`` where supported" rule does not turn into a
#: 400 against the reasoning families.  The pattern is intentionally a closed
#: regex (no per-version entries) so newly minted ``o4-…`` / ``gpt-5-…``
#: snapshots inherit the same handling.
_OPENAI_FIXED_TEMPERATURE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(o1[-.]?|o3[-.]?|o4[-.]?|gpt-5)",
)


class LLMConfigError(RuntimeError):
    """Raised when an LLM client cannot be configured for the requested model.

    Triggers:

    * Provider cannot be inferred from the model id prefix.
    * Selected model is on the closed text-only deny list.
    * The provider's API key is missing from both the call argument and the
      process environment.

    Inherits from :class:`RuntimeError` rather than any package-specific base
    so this util module stays import-safe across the shop_arena CLIs.
    Callers that need to surface the failure with their own error vocabulary
    should catch ``LLMConfigError`` at the boundary.
    """


@dataclass(frozen=True)
class VisionResponse:
    """Result of a single vision call.

    Attributes:
        parsed: Parsed JSON object the model emitted (the rubric layer
            validates it against the closed pydantic schema).  ``None``
            when the model's response could not be decoded as JSON; in
            that case ``parse_errors`` describes why.
        raw_response: Provider-agnostic textual record of the response.
            For Anthropic this is ``json.dumps`` of the tool-use input
            block; for OpenAI it is the raw assistant message content.
            Persisted verbatim into the rubric artifact for audit.
        parse_errors: Tuple of human-readable parse errors.  Empty when
            ``parsed`` is populated.
    """

    parsed: Mapping[str, Any] | None
    raw_response: str
    parse_errors: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class LLMVisionClient(Protocol):
    """Narrow vision-call interface consumed by the rubric layer.

    Implementations must be safe to construct without network access and
    must defer credential checks until :meth:`call` so dispatch-time
    failures stay deterministic.
    """

    @property
    def model(self) -> str:
        """Model id this client targets (e.g. ``"claude-sonnet-4-6"``)."""
        ...

    def call(
        self,
        *,
        prompt: str,
        images: Sequence[bytes],
        schema: Mapping[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        """Send ``prompt`` + ``images`` to the model and return its parsed JSON.

        Args:
            prompt: Plain-text instructions for the model.
            images: PNG-encoded image bytes, in the order the model should
                see them.  Forwarded as image parts before the text prompt
                in the user message.  Single-image callers (the screenshot
                rubric) pass a 1-tuple; the state-namer (spec §5.5.2)
                passes ``(pre_png, post_png)`` so the model can actually
                compare pre/post the way ``state_prompt.md`` instructs.
                Must be non-empty.
            schema: JSON schema describing the expected response object.
                Anthropic forwards it as the tool ``input_schema``; OpenAI
                wraps it in a ``response_format={"type": "json_schema", …}``.
            temperature: Sampling temperature.  Defaults to
                :data:`DEFAULT_RUBRIC_TEMPERATURE` (``0.0``).  Provider-side
                fixed-temperature models (the OpenAI ``o1``/``o3``/``o4`` and
                ``gpt-5`` families) silently omit the kwarg at the API
                boundary instead of erroring; spec §5.3 calls this out as
                "temperature ``0`` where the provider supports it".

        Returns:
            :class:`VisionResponse` with parsed mapping when the response
            decodes successfully, otherwise a ``parse_errors``-only record.

        Raises:
            LLMConfigError: API credentials are missing at call time.
            ValueError: ``images`` is empty.
        """
        ...

    def call_text(
        self,
        *,
        prompt: str,
        schema: Mapping[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        """Issue the same structured-output call as :meth:`call` but text-only.

        Identical wire contract to :meth:`call` — closed JSON schema,
        provider-specific structured-output mechanism (Anthropic forced
        tool-use, OpenAI ``response_format={"type": "json_schema", ...}``),
        same retry-on-rate-limit and same fixed-temperature handling — with
        no image content blocks attached to the user message.  Used by the
        :mod:`shop_arena.env_eval.transition.pages_classifier` module, where
        the input is a list of URL paths plus a base URL and there is no
        screenshot to forward.

        Args:
            prompt: Plain-text instructions for the model.
            schema: JSON schema describing the expected response object.
                Same conventions as :meth:`call`.
            temperature: Sampling temperature.  Defaults to ``0.0``;
                provider-side fixed-temperature models drop the kwarg at
                the API boundary, mirroring :meth:`call`.

        Returns:
            :class:`VisionResponse` with parsed mapping when the response
            decodes successfully, otherwise a ``parse_errors``-only record.

        Raises:
            LLMConfigError: API credentials are missing at call time.
        """
        ...


logger = logging.getLogger(__name__)

#: Backoff schedule (seconds) layered on top of the SDKs' built-in 2-retry
#: window for vision rate-limit errors.  Some compatible gateways enforce a
#: per-minute token bucket that the SDK's default ~1.5 s of waits cannot
#: outlast when a cohort run fires bursts of rubric calls; explicit waits
#: of (5, 15, 30, 45, 60) s give the bucket time to refill before failing
#: the run.  ``len(_RATE_LIMIT_DELAYS_S) + 1`` total attempts (the final
#: attempt re-raises on rate-limit failure).
_RATE_LIMIT_DELAYS_S: Final[tuple[float, ...]] = (5.0, 15.0, 30.0, 45.0, 60.0)


def _retry_on_rate_limit[T](provider: str, fn: Callable[[], T]) -> T:
    """Call ``fn`` and retry on the SDK's ``RateLimitError`` with explicit waits.

    Args:
        provider: ``"anthropic"`` or ``"openai"`` — selects which SDK
            ``RateLimitError`` class to catch.  Other exceptions propagate
            unchanged.
        fn: Zero-arg thunk wrapping the SDK call (e.g.
            ``lambda: client.messages.create(...)``).

    Returns:
        The thunk's return value on the first successful attempt.

    Raises:
        RuntimeError: ``provider`` is not a known LLM provider key.
        anthropic.RateLimitError / openai.RateLimitError: The proxy's
            per-minute window did not clear within the full backoff
            schedule.  Propagates from the final attempt.
    """
    if provider == "anthropic":
        from anthropic import RateLimitError as _RateLimitError  # noqa: PLC0415
    elif provider == "openai":
        from openai import RateLimitError as _RateLimitError  # noqa: PLC0415
    else:
        raise RuntimeError(f"unknown LLM provider for retry wrapper: {provider!r}")

    for delay in _RATE_LIMIT_DELAYS_S:
        try:
            return fn()
        except _RateLimitError:
            logger.warning(
                "%s rate limit hit; sleeping %.1fs before retry",
                provider,
                delay,
            )
            time.sleep(delay)
    return fn()


# ---------------------------------------------------------------------------
# Anthropic implementation.
# ---------------------------------------------------------------------------


class _AnthropicVisionClient:
    """Claude vision client backed by ``anthropic.Anthropic.messages.create``.

    Forces structured output via the tool-use API: a single tool with
    ``input_schema=<schema>`` and ``tool_choice={"type": "tool", …}`` so the
    model has no other path than to emit a tool-use block whose ``input``
    matches ``schema``.  The tool's ``input`` mapping is returned as
    :attr:`VisionResponse.parsed`.
    """

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client_factory: Callable[..., Any] | None = None,
        max_tokens: int = 4096,
    ) -> None:
        """Capture the routing config without touching the network.

        Args:
            model: Anthropic model id (e.g. ``"claude-sonnet-4-6"``).
            api_key: Override for ``ANTHROPIC_API_KEY`` env var.  Looked up
                lazily so a missing key only fails when :meth:`call` runs.
            base_url: Optional ``ANTHROPIC_BASE_URL`` override for compatible
                API gateways or Bedrock / Vertex local relays.
            client_factory: Test seam — replaces ``anthropic.Anthropic`` so
                unit tests can inject a stub without monkey-patching.
            max_tokens: Upper bound on response tokens.  Rubric responses
                are tiny (a few JSON keys); ``4096`` leaves slack without
                inflating the cost.
        """
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._client_factory = client_factory
        self._max_tokens = max_tokens
        self._client: Any | None = None

    @property
    def model(self) -> str:
        """Model id this client targets."""
        return self._model

    def _ensure_client(self) -> Any:
        """Build and cache the SDK client, validating credentials."""
        if self._client is not None:
            return self._client
        api_key = self._api_key or os.environ.get(_ANTHROPIC_API_KEY_ENV)
        if not api_key:
            raise LLMConfigError(
                f"missing {_ANTHROPIC_API_KEY_ENV} for model {self._model!r}; "
                "set it in the environment or pass api_key=...",
            )
        if self._client_factory is not None:
            factory = self._client_factory
        else:
            from anthropic import Anthropic  # noqa: PLC0415 — lazy to avoid import-time deps

            factory = Anthropic
        kwargs: dict[str, Any] = {"api_key": api_key}
        if self._base_url is not None:
            kwargs["base_url"] = self._base_url
        self._client = factory(**kwargs)
        return self._client

    def call(
        self,
        *,
        prompt: str,
        images: Sequence[bytes],
        schema: Mapping[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        """Issue one ``messages.create`` call with forced tool-use JSON output."""
        if not images:
            raise ValueError("images must contain at least one PNG")
        content: list[dict[str, Any]] = [_anthropic_image_block(img) for img in images]
        content.append({"type": "text", "text": prompt})
        return self._dispatch(content=content, schema=schema, temperature=temperature)

    def call_text(
        self,
        *,
        prompt: str,
        schema: Mapping[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        """Issue one ``messages.create`` call with no image inputs."""
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        return self._dispatch(content=content, schema=schema, temperature=temperature)

    def _dispatch(
        self,
        *,
        content: list[dict[str, Any]],
        schema: Mapping[str, Any],
        temperature: float,
    ) -> VisionResponse:
        """Issue ``messages.create`` with the given pre-built user content."""
        client = self._ensure_client()
        tool_def = {
            "name": _ANTHROPIC_TOOL_NAME,
            "description": "Emit the rubric counts as a JSON object.",
            "input_schema": dict(schema),
        }
        message = _retry_on_rate_limit(
            "anthropic",
            lambda: client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=temperature,
                tools=[tool_def],
                tool_choice={"type": "tool", "name": _ANTHROPIC_TOOL_NAME},
                messages=[{"role": "user", "content": content}],
            ),
        )
        return _parse_anthropic_message(message)


def _anthropic_image_block(image_png: bytes) -> dict[str, Any]:
    """Return the Anthropic ``content`` entry for one base64-encoded PNG."""
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": b64encode(image_png).decode("ascii"),
        },
    }


def _parse_anthropic_message(message: Any) -> VisionResponse:
    """Extract the tool-use ``input`` block from an Anthropic ``Message``."""
    blocks = list(getattr(message, "content", []) or [])
    errors: list[str] = []
    for block in blocks:
        block_type = getattr(block, "type", None)
        if block_type != "tool_use":
            continue
        if getattr(block, "name", None) != _ANTHROPIC_TOOL_NAME:
            continue
        payload = getattr(block, "input", None)
        if not isinstance(payload, dict):
            errors.append(
                f"anthropic tool_use input has type {type(payload).__name__}, expected dict",
            )
            continue
        parsed: dict[str, Any] = cast("dict[str, Any]", payload)
        raw = json.dumps(parsed, sort_keys=True)
        return VisionResponse(parsed=parsed, raw_response=raw)
    if not errors:
        errors.append("anthropic response contained no tool_use block")
    raw_dump = _safe_json_dump([_block_to_jsonable(b) for b in blocks])
    return VisionResponse(parsed=None, raw_response=raw_dump, parse_errors=tuple(errors))


def _block_to_jsonable(block: Any) -> Any:
    """Best-effort JSON-friendly view of an Anthropic content block (for ``raw``)."""
    to_dict = getattr(block, "model_dump", None)
    if callable(to_dict):
        return to_dict()
    return {"type": getattr(block, "type", "unknown"), "repr": repr(block)}


# ---------------------------------------------------------------------------
# OpenAI implementation.
# ---------------------------------------------------------------------------


class _OpenAIVisionClient:
    """OpenAI vision client backed by ``chat.completions.create``.

    Uses ``response_format={"type": "json_schema", "json_schema": {...,
    "strict": True, "schema": <schema>}}`` so the assistant message is a
    JSON document already conforming to ``schema`` — no tool-call decoding
    layer like Anthropic's.
    """

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client_factory: Callable[..., Any] | None = None,
        max_tokens: int = 4096,
        schema_name: str = "rubric_response",
    ) -> None:
        """Capture the routing config without touching the network.

        Args:
            model: OpenAI model id (e.g. ``"gpt-4o"``, ``"gpt-5-mini"``).
            api_key: Override for ``OPENAI_API_KEY`` env var.
            base_url: Optional ``OPENAI_BASE_URL`` override.
            client_factory: Test seam — replaces ``openai.OpenAI``.
            max_tokens: Upper bound on response tokens (passed as
                ``max_completion_tokens`` to align with the GPT-5 family).
            schema_name: Identifier surfaced to the model under
                ``json_schema.name``.  Constant by default so the wire
                payload is byte-stable across runs.
        """
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._client_factory = client_factory
        self._max_tokens = max_tokens
        self._schema_name = schema_name
        self._client: Any | None = None

    @property
    def model(self) -> str:
        """Model id this client targets."""
        return self._model

    def _ensure_client(self) -> Any:
        """Build and cache the SDK client, validating credentials."""
        if self._client is not None:
            return self._client
        api_key = self._api_key or os.environ.get(_OPENAI_API_KEY_ENV)
        if not api_key:
            raise LLMConfigError(
                f"missing {_OPENAI_API_KEY_ENV} for model {self._model!r}; "
                "set it in the environment or pass api_key=...",
            )
        if self._client_factory is not None:
            factory = self._client_factory
        else:
            from openai import OpenAI  # noqa: PLC0415 — lazy to avoid import-time deps

            factory = OpenAI
        kwargs: dict[str, Any] = {"api_key": api_key}
        if self._base_url is not None:
            kwargs["base_url"] = self._base_url
        self._client = factory(**kwargs)
        return self._client

    def call(
        self,
        *,
        prompt: str,
        images: Sequence[bytes],
        schema: Mapping[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        """Issue one ``chat.completions.create`` call in json_schema mode."""
        if not images:
            raise ValueError("images must contain at least one PNG")
        content: list[dict[str, Any]] = [_openai_image_block(img) for img in images]
        content.append({"type": "text", "text": prompt})
        return self._dispatch(content=content, schema=schema, temperature=temperature)

    def call_text(
        self,
        *,
        prompt: str,
        schema: Mapping[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        """Issue one ``chat.completions.create`` call with no image inputs."""
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        return self._dispatch(content=content, schema=schema, temperature=temperature)

    def _dispatch(
        self,
        *,
        content: list[dict[str, Any]],
        schema: Mapping[str, Any],
        temperature: float,
    ) -> VisionResponse:
        """Issue ``chat.completions.create`` with the given pre-built user content."""
        client = self._ensure_client()
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": self._schema_name,
                "strict": True,
                "schema": dict(schema),
            },
        }
        api_kwargs: dict[str, Any] = {
            "model": self._model,
            "max_completion_tokens": self._max_tokens,
            "response_format": response_format,
            "messages": [{"role": "user", "content": content}],
        }
        # Reasoning families (``o1``/``o3``/``o4``) and the ``gpt-5`` family
        # only accept the provider-default temperature; sending an explicit
        # value (including ``0``) returns a 400.  Drop the kwarg silently for
        # those models so spec §5.3's "temperature ``0`` where supported" rule
        # degrades gracefully (artifact reuse, not model determinism, is the
        # reproducibility boundary).
        if not _OPENAI_FIXED_TEMPERATURE_RE.match(self._model):
            api_kwargs["temperature"] = temperature
        completion = _retry_on_rate_limit(
            "openai",
            lambda: client.chat.completions.create(**api_kwargs),
        )
        return _parse_openai_completion(completion)


def _openai_image_block(image_png: bytes) -> dict[str, Any]:
    """Return the OpenAI ``content`` entry for one base64-encoded PNG."""
    encoded = b64encode(image_png).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{encoded}"},
    }


def _parse_openai_completion(completion: Any) -> VisionResponse:
    """Extract + JSON-decode the assistant message from a chat completion."""
    choices = list(getattr(completion, "choices", []) or [])
    if not choices:
        return VisionResponse(
            parsed=None,
            raw_response="",
            parse_errors=("openai completion contained no choices",),
        )
    message = getattr(choices[0], "message", None)
    raw = getattr(message, "content", None) if message is not None else None
    raw_text = raw if isinstance(raw, str) else ""
    if not raw_text:
        return VisionResponse(
            parsed=None,
            raw_response="",
            parse_errors=("openai completion had empty assistant content",),
        )
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return VisionResponse(
            parsed=None,
            raw_response=raw_text,
            parse_errors=(f"openai response is not valid JSON: {exc}",),
        )
    if not isinstance(parsed, dict):
        return VisionResponse(
            parsed=None,
            raw_response=raw_text,
            parse_errors=(f"openai response root is {type(parsed).__name__}, expected object",),
        )
    return VisionResponse(parsed=cast("dict[str, Any]", parsed), raw_response=raw_text)


# ---------------------------------------------------------------------------
# Dispatcher.
# ---------------------------------------------------------------------------


def build_default_client(
    model: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> LLMVisionClient:
    """Return a vision client for ``model`` based on its provider prefix.

    Routing rules (impl-plan M0 decisions):

    * ``claude-*`` → :class:`_AnthropicVisionClient`.
    * ``gpt-*``, ``o1*``, ``o3*``, ``o4*``, ``chatgpt-*`` →
      :class:`_OpenAIVisionClient`.
    * Anything else raises :class:`LLMConfigError`.

    The model id is also validated against :data:`_NON_VISION_MODELS`; the
    rubric requires image inputs, so a text-only model is a hard error
    rather than a silent downgrade.

    Args:
        model: Provider-prefixed model id.
        api_key: Override for the provider env var.
        base_url: Optional provider-specific base URL override.
        client_factory: Test seam forwarded to the provider client.  Useful
            for unit tests that need to inject a fake SDK without
            monkey-patching the provider package.

    Returns:
        A concrete :class:`LLMVisionClient`.

    Raises:
        LLMConfigError: When the provider cannot be inferred from
            ``model`` or when ``model`` is on the text-only deny list.
    """
    if not model:
        raise LLMConfigError("model id must be a non-empty string")
    if model in _NON_VISION_MODELS:
        raise LLMConfigError(
            f"model {model!r} does not support vision input; "
            "use a vision-capable model (e.g. claude-sonnet-4-6, gpt-4o, gpt-5)",
        )
    if _ANTHROPIC_PREFIX_RE.match(model):
        return _AnthropicVisionClient(
            model,
            api_key=api_key,
            base_url=base_url,
            client_factory=client_factory,
        )
    if _OPENAI_PREFIX_RE.match(model):
        return _OpenAIVisionClient(
            model,
            api_key=api_key,
            base_url=base_url,
            client_factory=client_factory,
        )
    raise LLMConfigError(
        f"cannot infer provider for model {model!r}; "
        "expected claude-*, gpt-*, o1*, o3*, o4*, or chatgpt-*",
    )


def _safe_json_dump(value: Any) -> str:
    """Return ``json.dumps(value)`` with a fallback to ``repr`` on failure."""
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return repr(value)
