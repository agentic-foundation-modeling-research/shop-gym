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

from harness.runtimes.base import AgentRuntime, RuntimeIterationResult

__all__ = ["AgentRuntime", "RuntimeIterationResult", "get_runtime"]

# Maps a public runtime name to a `"module:attr"` import target. The
# attribute must be a callable returning an `AgentRuntime` (typically
# the runtime class itself).
_REGISTRY: dict[str, str] = {
    "replay": "harness.runtimes.replay:ReplayRuntime",
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
        raise ValueError(
            f"Unknown runtime {name!r}; known runtimes: {known}"
        ) from None
    module_name, _, attr = target.partition(":")
    module = importlib.import_module(module_name)
    factory = getattr(module, attr)
    return factory(**kwargs)  # type: ignore[no-any-return]
