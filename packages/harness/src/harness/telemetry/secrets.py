"""Conservative secret scrubber for `run.json`'s `config_snapshot`.

`scrub_secrets` walks an arbitrary JSON-shaped value and redacts any
mapping value whose key looks secret-shaped. The matcher is
substring-based on purpose: it errs on the side of redacting a
false-positive key like ``authorize`` rather than letting a real token
leak into telemetry.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final, cast

_REDACTED: Final[str] = "***REDACTED***"

# Conservative regex matched against dict keys (case-insensitive). Any
# match means the entire value at that key is replaced with the
# redaction sentinel, regardless of nesting.
_SECRET_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"secret|token|password|passwd|api[_-]?key|access[_-]?key|auth|credential",
    re.IGNORECASE,
)


def scrub_secrets(value: Any) -> Any:
    """Return a deep copy of `value` with secret-shaped dict keys redacted.

    Recurses into mappings and sequences. Any mapping value whose key
    matches `_SECRET_KEY_RE` is replaced with the literal sentinel
    ``"***REDACTED***"``, regardless of the original value's type. All
    other scalars are passed through unchanged.

    The redaction is conservative: it errs on the side of dropping
    plausible secrets rather than letting them leak into `run.json`.
    """
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        out: dict[str, Any] = {}
        for raw_key, sub in mapping.items():
            key = str(raw_key)
            if _SECRET_KEY_RE.search(key):
                out[key] = _REDACTED
            else:
                out[key] = scrub_secrets(sub)
        return out
    if isinstance(value, (list, tuple)):
        seq = cast("list[object] | tuple[object, ...]", value)
        return [scrub_secrets(item) for item in seq]
    return value
