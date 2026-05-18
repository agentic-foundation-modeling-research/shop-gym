"""Public error types raised by ``shop_arena.env_eval``.

The four classes defined here form the entire failure vocabulary EnvEval
exposes to callers (spec §8.1). They are intentionally narrow and named
after the pipeline phase that raises them so a downstream catch can be
specific without depending on internal implementation details.

All errors derive from a private base class so consumers may also catch
"any EnvEval failure" via :class:`EnvEvalError` if they need a coarse
guard, while continuing to use the specific subclasses elsewhere.
"""

from __future__ import annotations

__all__ = [
    "EnvEvalError",
    "MetricsValidationError",
    "PageDiscoveryError",
    "PagesClassifierError",
    "ResumeError",
    "ShopUnreachableError",
]


class EnvEvalError(RuntimeError):
    """Base class for every error raised by ``shop_arena.env_eval``.

    Not part of the documented public surface in spec §8.1 but exported
    so callers that want a single ``except`` clause for the package can
    use it without depending on Python's :class:`RuntimeError` hierarchy.
    """


class ShopUnreachableError(EnvEvalError):
    """Raised when the shop's homepage cannot be loaded.

    Page selection (spec §5.2) treats homepage navigation as mandatory:
    if ``goto(url)`` returns a non-2xx status, times out, or the browser
    raises a navigation error, the entire run aborts with this error
    rather than producing partial metrics.
    """


class PageDiscoveryError(EnvEvalError):
    """Raised when page selection cannot proceed past the homepage.

    Reserved for catastrophic discovery failures that are not covered by
    the per-bucket ``not_found`` status (spec §5.2). Individual missing
    buckets (e.g. no product link, no policy page) are recorded as
    ``not_found`` in ``pages.json`` and do not raise.
    """


class MetricsValidationError(EnvEvalError):
    """Raised when a ``metrics.json`` payload fails its closed schema.

    Wraps :class:`pydantic.ValidationError` so the public surface stays
    decoupled from pydantic. Used when EnvEval writes a new
    ``metrics.json`` (defense in depth) and when downstream tools load
    a ``metrics.json`` produced elsewhere.
    """


class ResumeError(EnvEvalError):
    """Raised when an existing ``--out`` directory is incompatible with resume.

    Triggered by the M6 resume layer when ``run_dir`` exists but cannot
    be safely reused — for example a config-snapshot mismatch, a corrupt
    artifact, or a partial write detected by ``can_skip``.
    """


class PagesClassifierError(EnvEvalError):
    """Raised when the ``/pages/<slug>`` classifier cannot produce a valid result.

    Triggered by :mod:`shop_arena.env_eval.transition.pages_classifier`
    when the LLM response fails closed-schema validation, when
    ``pages_classification.json`` is missing or malformed on read, or
    when the response shape does not match the model contract. BFS
    canonicalization depends on the classifier output, so failures are
    surfaced loudly rather than silently degraded; the pipeline can
    decide at the call site whether to fall back to ``stub_classification``
    or abort.
    """
