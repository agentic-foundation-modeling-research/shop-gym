"""Thin GenericAgent subclass that persists memory + plan per step.

AgentLab's :class:`~agentlab.agents.generic_agent.GenericAgent` keeps
``self.memories``, ``self.plan``, and ``self.plan_step`` as instance
state but does NOT put them on ``AgentInfo``. The ShopGuru judge wants
them per step, so we override ``get_action`` to copy the current
values into ``AgentInfo.extra_info``. StepInfo pickles ``agent_info``
as-is, so those fields ride along for free — no module-level buffer,
no runtime class patching.

:class:`ShopGuruGenericAgentArgs` is the ``AgentArgs`` analogue.
``run.py`` rebuilds the model config picked from
:mod:`shop_guru.eval.models` into one of these before handing it to
``Study``, so workers unpickle our subclass even under joblib.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentlab.agents.generic_agent.generic_agent import GenericAgent, GenericAgentArgs


class ShopGuruGenericAgent(GenericAgent):
    """``GenericAgent`` that exposes memory + plan via ``AgentInfo.extra_info``."""

    def get_action(self, obs):  # type: ignore[override]
        action, info = super().get_action(obs)
        # ``extra_info`` is populated by the base class with
        # ``{"chat_model_args": ...}``; augment rather than replace so
        # that existing consumers see the same keys they always have.
        extra = dict(info.extra_info or {})
        extra["memory"] = self.memories[-1] if self.memories else None
        extra["plan"] = self.plan
        extra["plan_step"] = self.plan_step
        info.extra_info = extra
        return action, info


@dataclass
class ShopGuruGenericAgentArgs(GenericAgentArgs):
    """``GenericAgentArgs`` that builds a :class:`ShopGuruGenericAgent`."""

    def make_agent(self):  # type: ignore[override]
        return ShopGuruGenericAgent(
            chat_model_args=self.chat_model_args,
            flags=self.flags,
            max_retry=self.max_retry,
        )


__all__ = ["ShopGuruGenericAgent", "ShopGuruGenericAgentArgs"]
