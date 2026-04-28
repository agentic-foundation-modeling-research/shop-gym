"""Runtime adapters for the plan + exec harness.

Each adapter implements the `AgentRuntime` Protocol from
`harness.runtimes.base` and is selected by name via a small registry.
Runtime modules are imported lazily on first lookup so that registering
a name does not pull in heavy CLI-specific dependencies (or modules
that have not yet been written).
"""

from __future__ import annotations

import importlib
from typing import Any

from harness.runtimes.base import AgentRuntime, LLMCompleter, RuntimeIterationResult

__all__ = [
    "AgentRuntime",
    "LLMCompleter",
    "RuntimeIterationResult",
    "get_runtime",
    "validate_model_grammar",
]

# Maps a public runtime name to a `"module:attr"` import target. The
# attribute must be a callable returning an `AgentRuntime` (typically
# the runtime class itself).
_REGISTRY: dict[str, str] = {
    "replay": "harness.runtimes.replay:ReplayRuntime",
    "claude_code": "harness.runtimes.claude_code:ClaudeCodeRuntime",
    "pi": "harness.runtimes.pi:PiRuntime",
}


def get_runtime(name: str, **kwargs: Any) -> AgentRuntime:
    """Resolve a registered runtime by name.

    Args:
        name: Registered runtime name (e.g. ``"replay"``).
        **kwargs: Forwarded to the runtime constructor.

    Returns:
        A runtime instance satisfying the `AgentRuntime` Protocol.

    Raises:
        ValueError: If ``name`` is not registered.
    """
    try:
        target = _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "<none>"
        raise ValueError(f"Unknown runtime {name!r}; known runtimes: {known}") from None
    module_name, _, attr = target.partition(":")
    module = importlib.import_module(module_name)
    factory = getattr(module, attr)
    return factory(**kwargs)  # type: ignore[no-any-return]


def validate_model_grammar(model: str | None, runtime: str) -> None:
    """Validate that ``model`` matches ``runtime``'s expected grammar.

    Each runtime adapter forwards ``model`` to its underlying CLI as
    ``--model``; the CLIs use different grammars (`pi` accepts patterns
    like ``sonnet:high`` and provider-prefixed IDs like
    ``anthropic/claude-opus-4-7``; ``claude_code`` accepts only bare
    aliases like ``opus`` or pinned IDs like ``claude-opus-4-5``).
    Mixing the two leads to a far-downstream subprocess error, so this
    helper enforces the boundary at config-construction time.

    Args:
        model: Model identifier or ``None`` ("let the runtime use its
            own default", which always validates).
        runtime: Registered runtime name (a key of :data:`_REGISTRY`).

    Raises:
        ValueError: If ``model`` is in another runtime's grammar.
    """
    if model is None:
        return
    if runtime == "claude_code" and "/" in model:
        # The `claude` CLI rejects provider-prefixed IDs (`anthropic/foo`);
        # that grammar belongs to `pi`. Strip the prefix or switch runtime.
        bare = model.split("/", 1)[1]
        raise ValueError(
            f"runtime={runtime!r} model={model!r}: the `claude` CLI does not "
            f"accept provider-prefixed IDs. Drop the prefix (e.g. {bare!r}) "
            f"or use --runtime pi for this grammar."
        )
    # `pi`'s grammar is a superset of `claude_code`'s bare names: a `claude`-
    # style alias like 'opus' is a valid bare model name for `pi` too, so
    # there is no shape we can confidently reject for runtime='pi'.
