"""Agent configurations for ShopGuru benchmark runs.

Upstream AgentLab's :class:`OpenAIChatModel` doesn't expose
``client_args``, so its OpenAI client always lands on the SDK's
default ``base_url``. :class:`CustomAIChatModel` is a
:class:`ChatModel` subclass that takes an optional ``base_url`` as a
constructor argument and forwards it via ``client_args`` (same
pattern ``OpenRouterChatModel`` uses for openrouter.ai).
:class:`CustomAIModelArgs` is the dataclass that carries that
``base_url`` alongside the usual token budgets and plugs into
:class:`GenericAgentArgs` just like :class:`OpenAIModelArgs`.

:class:`CustomAnthropicChatModel` does the same job for Anthropic:
upstream :class:`AnthropicChatModel` hardcodes api.anthropic.com, so
the subclass rebuilds ``anthropic.Anthropic`` with an explicit
``base_url`` to route Claude traffic somewhere else.

When ``base_url`` is ``None`` (the default), the SDK reads
``OPENAI_BASE_URL`` / ``ANTHROPIC_BASE_URL`` from the environment.
Operators populate those via the project ``.env`` (see
:mod:`shop_guru._dotenv`) — the same convention
:mod:`shop_arena.probe.judge.client` follows.

``MODEL_CHOICES`` / ``DEFAULT_MODEL`` stay as plain strings so
``run.py`` can reference them at argparse time without triggering
any agentlab import — ``AGENTLAB_EXP_ROOT`` must still be set before
``agentlab.experiments.study`` loads, and :func:`build_agent` is the
deferred entry point that respects that ordering.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import anthropic
import openai
from agentlab.agents import dynamic_prompting as dp
from agentlab.agents.generic_agent.generic_agent import GenericAgentArgs
from agentlab.agents.generic_agent.tmlr_config import BASE_FLAGS
from agentlab.llm import tracking
from agentlab.llm.base_api import BaseModelArgs
from agentlab.llm.chat_api import (
    AnthropicChatModel,
    ChatModel,
    OpenRouterError,
    RetryError,
    handle_error,
)
from agentlab.llm.llm_utils import AIMessage
from bgym import HighLevelActionSetArgs
from openai import OpenAI

MODEL_CHOICES: tuple[str, ...] = (
    "gpt-5",
    "gpt-5-mini",
    "gemini-3-flash",
    "gemini-3-pro",
    "claude-haiku-4.5",
    "claude-sonnet-4.6",
)
DEFAULT_MODEL: str = "gpt-5-mini"


def _zero_pricing(model_name: str) -> dict[str, dict[str, float]]:
    # litellm's registry doesn't cover our internal model slugs (e.g.
    # googlevertexai-global:gemini-3-flash-preview), and upstream's
    # get_pricing_litellm lets None costs leak through, which blows up
    # the cost multiplication in ChatModel.__call__. Skip pricing entirely.
    return {model_name: {"prompt": 0.0, "completion": 0.0}}


class CustomAIChatModel(ChatModel):
    """OpenAI-compatible chat model with an optional ``base_url``.

    Upstream :class:`OpenAIChatModel` never exposes ``client_args``,
    so the only way to steer its client at a non-default endpoint is
    the ``OPENAI_BASE_URL`` env var. This subclass passes ``base_url``
    through ``client_args`` instead — mirroring the pattern
    :class:`OpenRouterChatModel` uses — so an explicit override can
    sit on the args object. When ``base_url`` is ``None`` no
    ``client_args`` are forwarded, and the OpenAI SDK falls back to
    its env-var defaults (``OPENAI_BASE_URL`` / ``OPENAI_API_KEY``).
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.5,
        max_tokens: int | None = 100,
        max_retry: int = 4,
        min_retry_wait_time: float = 60,
        log_probs: bool = False,
    ) -> None:
        if max_tokens is None:
            # Upstream OpenAIChatModel swaps None -> NOT_GIVEN here so
            # the SDK leaves the limit unset. Keep the same behavior.
            from openai import NOT_GIVEN  # noqa: PLC0415

            max_tokens = NOT_GIVEN
        super().__init__(
            model_name=model_name,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retry=max_retry,
            min_retry_wait_time=min_retry_wait_time,
            api_key_env_var="OPENAI_API_KEY",
            client_class=OpenAI,
            client_args={"base_url": base_url} if base_url else {},
            pricing_func=lambda: _zero_pricing(model_name),
            log_probs=log_probs,
        )

    def __call__(
        self,
        messages: list[dict],
        n_samples: int = 1,
        temperature: float | None = None,
    ) -> Any:
        # Copy of ChatModel.__call__ with a guard around the token->cost math:
        # the proxy sometimes returns None for prompt_tokens or
        # completion_tokens on gemini responses, which crashes the upstream
        # multiplication. Coerce to 0 before multiplying.
        self.retries = 0
        self.success = False
        self.error_types = []

        completion = None
        error_type = None
        for itr in range(self.max_retry):
            self.retries += 1
            temperature = temperature if temperature is not None else self.temperature
            try:
                completion = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    n=n_samples,
                    temperature=temperature,
                    max_completion_tokens=self.max_tokens,
                    logprobs=self.log_probs,
                )

                if completion.usage is None:
                    raise OpenRouterError(
                        "The completion object does not contain usage information. "
                        "This is likely a bug in the OpenRouter API."
                    )

                self.success = True
                break
            except openai.OpenAIError as e:
                error_type = handle_error(e, itr, self.min_retry_wait_time, self.max_retry)
                self.error_types.append(error_type)

        if not completion:
            raise RetryError(
                f"Failed to get a response from the API after {self.max_retry} retries\n"
                f"Last error: {error_type}"
            )

        input_tokens = completion.usage.prompt_tokens or 0
        output_tokens = completion.usage.completion_tokens or 0
        cost = input_tokens * self.input_cost + output_tokens * self.output_cost

        if hasattr(tracking.TRACKER, "instance") and isinstance(
            tracking.TRACKER.instance, tracking.LLMTracker
        ):
            tracking.TRACKER.instance(input_tokens, output_tokens, cost)

        # Gemini sometimes returns message.content=None (content filter, safety
        # block, or thinking-only response). Downstream parsers do re.findall
        # on this and crash; give them "" so they raise ParseError and let
        # upstream retry() handle it.
        if n_samples == 1:
            if completion.choices[0].message is None:
                res = AIMessage("")
            else:
                res = AIMessage(completion.choices[0].message.content or "")
            if self.log_probs:
                res["log_probs"] = completion.choices[0].log_probs
            return res
        return [AIMessage(c.message.content or "") for c in completion.choices]


@dataclass
class CustomAIModelArgs(BaseModelArgs):
    """:class:`OpenAIModelArgs` analogue that carries an optional ``base_url``.

    Dataclass fields inherited from :class:`BaseModelArgs`: ``model_name``,
    ``max_total_tokens``, ``max_input_tokens``, ``max_new_tokens``,
    ``temperature``, ``vision_support``, ``log_probs``. Plus ``base_url``.
    """

    base_url: str | None = None

    def make_model(self) -> CustomAIChatModel:
        return CustomAIChatModel(
            model_name=self.model_name,
            base_url=self.base_url,
            temperature=self.temperature,
            max_tokens=self.max_new_tokens,
            log_probs=self.log_probs,
        )


class CustomAnthropicChatModel(AnthropicChatModel):
    """Anthropic chat model pointed at an optional ``base_url``.

    Upstream :class:`AnthropicChatModel` builds its client as
    ``anthropic.Anthropic(api_key=...)`` with no ``base_url`` hook, so
    requests always land on api.anthropic.com. Override ``__init__`` to
    forward ``base_url`` through to :class:`anthropic.Anthropic`,
    mirroring what :class:`CustomAIChatModel` does for the OpenAI
    client. When ``base_url`` is ``None`` the SDK reads
    ``ANTHROPIC_BASE_URL`` from the environment. ``__call__``
    (OpenAI→Anthropic message reshape, retries, tracking) is inherited
    unchanged.
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.5,
        max_tokens: int | None = 4096,
        max_retry: int = 4,
    ) -> None:
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retry = max_retry
        # Same stance as CustomAIChatModel: skip pricing. Proxy-prefixed
        # slugs aren't in litellm's registry, and zero cost keeps the
        # tracker math safe against None usage fields.
        self.input_cost = 0.0
        self.output_cost = 0.0
        client_kwargs: dict[str, Any] = {
            "api_key": api_key or os.getenv("ANTHROPIC_API_KEY"),
        }
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**client_kwargs)


@dataclass
class CustomAnthropicModelArgs(BaseModelArgs):
    """:class:`AnthropicModelArgs` analogue that carries an optional ``base_url``."""

    base_url: str | None = None

    def make_model(self) -> CustomAnthropicChatModel:
        return CustomAnthropicChatModel(
            model_name=self.model_name,
            base_url=self.base_url,
            temperature=self.temperature,
            max_tokens=self.max_new_tokens,
        )


def build_agent(model: str, base_url: str | None = None) -> Any:
    """Return a :class:`GenericAgentArgs` for a single model.

    ``base_url`` overrides the SDK endpoint; when ``None`` the OpenAI
    / Anthropic SDKs read ``OPENAI_BASE_URL`` / ``ANTHROPIC_BASE_URL``
    from the environment (populated from the project ``.env``).
    Deferred so agentlab imports don't fire before
    ``AGENTLAB_EXP_ROOT`` is set.
    """

    # BASE_FLAGS.action is a plain string ("bid") upstream, but
    # _configure_shopguru_agent mutates action.action_set.subsets to
    # swap in our terminal-aware subset list — which requires the
    # dataclass form. Matches the shape AgentLab uses for its
    # AGENT_GPT5_MINI sample config.
    flags = BASE_FLAGS.copy()
    flags.action = dp.ActionFlags(
        action_set=HighLevelActionSetArgs(subsets=["bid"], multiaction=False)
    )

    match model:
        case "gpt-5":
            chat_model_args = CustomAIModelArgs(
                model_name="gpt-5",
                base_url=base_url,
                max_total_tokens=400_000,
                max_input_tokens=400_000 - 8_192,
                max_new_tokens=8_192,
                temperature=1,  # gpt-5 family rejects other values
                vision_support=True,
            )
        case "gpt-5-mini":
            chat_model_args = CustomAIModelArgs(
                model_name="gpt-5-mini-2025-08-07",
                base_url=base_url,
                max_total_tokens=400_000,
                max_input_tokens=400_000 - 4_000,
                max_new_tokens=4_000,
                temperature=1,  # gpt-5 family rejects other values
                vision_support=True,
            )
        case "gemini-3-flash":
            chat_model_args = CustomAIModelArgs(
                model_name="googlevertexai-global:gemini-3-flash-preview",
                base_url=base_url,
                max_total_tokens=1_000_000,
                max_input_tokens=1_000_000 - 8_192,
                max_new_tokens=8_192,
                vision_support=True,
            )
        case "gemini-3-pro":
            chat_model_args = CustomAIModelArgs(
                model_name="gemini-3-pro",
                base_url=base_url,
                max_total_tokens=1_000_000,
                max_input_tokens=1_000_000 - 8_192,
                max_new_tokens=8_192,
                vision_support=True,
            )
        case "claude-haiku-4.5":
            chat_model_args = CustomAnthropicModelArgs(
                model_name="anthropic:claude-haiku-4-5-20251001",
                base_url=base_url,
                max_total_tokens=200_000,
                max_input_tokens=200_000 - 8_192,
                max_new_tokens=8_192,
                vision_support=True,
            )
        case "claude-sonnet-4.6":
            chat_model_args = CustomAnthropicModelArgs(
                model_name="anthropic:claude-sonnet-4-6",
                base_url=base_url,
                max_total_tokens=200_000,
                max_input_tokens=200_000 - 8_192,
                max_new_tokens=8_192,
                vision_support=True,
            )
        case _:
            raise ValueError(f"Unknown model {model!r}. Expected one of {MODEL_CHOICES}.")

    return GenericAgentArgs(chat_model_args=chat_model_args, flags=flags)


__all__ = [
    "DEFAULT_MODEL",
    "MODEL_CHOICES",
    "CustomAIChatModel",
    "CustomAIModelArgs",
    "CustomAnthropicChatModel",
    "CustomAnthropicModelArgs",
    "build_agent",
]
