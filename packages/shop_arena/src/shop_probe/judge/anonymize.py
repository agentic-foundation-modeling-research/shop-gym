"""Trajectory anonymization for the blinded pairwise judge (T4.4 — spec §5.5 step 3).

The axis-C judge sees ``(A, B)`` :class:`Trajectory` pairs and decides which is
real. For that pick to measure *structural* indistinguishability rather than
brand recognition, every brand-y signal must be stripped before the judge
prompt is built (spec §5.5 step 3):

* URLs (scheme + host) and theme identifiers — replaced with redacted
  placeholders.
* Brand strings (merchant names, taglines) — replaced with a fixed
  ``REDACTED`` token via case-insensitive whole-word match.
* Distinctive product titles — replaced with a stable
  ``product_<hash>`` token so the judge can still tell that "the same
  product is referenced twice" without learning *which* product.
* Catalog identifiers in URL paths (``/products/<handle>``,
  ``/collections/<handle>``, ``/pages/<handle>``, ``/policies/<handle>``,
  ``/blogs/<handle>``) — replaced with a stable hex hash of the handle.
* Free-form text on actions, observations, reasoning, and operator
  notes — same brand / domain / title rewrites applied via regex.

Hashes are deterministic (SHA-256 of ``salt::value``) so the same handle
produces the same placeholder across both members of a pair, which keeps
trajectory structure legible to the judge.

The module is import-safe — no I/O at import time. It operates purely on
the in-memory :class:`Trajectory` schema; on-disk
``screenshot`` / ``a11y_snapshot`` / ``har`` files are not rewritten by
this module (those are tracked as a separate v1.1 workstream — pixels
and HAR bodies need different tooling). The closed schema flips
``anonymized=True`` once this transform has run; the judge wiring (T4.6)
gates on that flag.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

from shop_probe.judge.trajectory import (
    Trajectory,
    TrajectoryAction,
    TrajectoryObservation,
    TrajectoryStep,
)
from shop_probe.targets import Target

REDACTED_HOST = "redacted.example"
"""Replacement host used for every rewritten URL (spec §5.5 step 3)."""

REDACTED_BRAND = "REDACTED"
"""Whole-word replacement for brand strings (spec §5.5 step 3)."""

REDACTED_THEME = "theme_REDACTED"
"""Replacement for theme identifiers (e.g. ``"dawn"`` → ``"theme_REDACTED"``)."""

_HASH_MIN_LENGTH = 4
"""Lower bound on the hex digest length accepted by :func:`hash_token`."""

_HASH_MAX_LENGTH = 64
"""Upper bound on the hex digest length (full SHA-256 width)."""

_HASH_LENGTH = 12
"""Default short-hash length; long enough for collision-free pair-level use."""

_DEFAULT_SALT = "shop_probe.v1"
"""Default deterministic salt for catalog-identifier hashes."""

# Path prefixes whose first segment is a Shopify-shaped catalog handle
# (spec §5.4 storefront routes). Anonymization replaces just the handle,
# leaving the route shape intact so the judge can still see "this is a PDP"
# without learning *which* PDP.
_HANDLE_PREFIXES: tuple[str, ...] = (
    "products",
    "collections",
    "pages",
    "policies",
    "blogs",
)


class AnonymizationPlan(BaseModel):
    """Inputs that drive :func:`anonymize_trajectory` (spec §5.5 step 3).

    A plan is built once per ``(sandbox, source)`` pair and reused for both
    members so the rewrites are symmetric — every rewrite rule that fires
    on the source must also fire on the sandbox, and vice versa, otherwise
    the judge could detect the asymmetry instead of the underlying
    storefront.

    Attributes:
        source_domains: Hosts to strip from URLs and free-form text. May
            include subdomains; matching is case-insensitive on host
            comparison and on substring replacement in text.
        brand_terms: Brand / merchant strings replaced with
            :data:`REDACTED_BRAND` via case-insensitive whole-word match.
        theme_identifiers: Theme handles (e.g. ``"dawn"``, ``"atelier"``)
            replaced with :data:`REDACTED_THEME`.
        product_titles: Distinctive product names replaced with stable
            ``product_<hash>`` tokens so the judge can still detect
            cross-step references without learning the title.
        salt: Salt mixed into every catalog-identifier and product-title
            hash. Stable across a pair so the same handle hashes to the
            same token on both sides.
        hash_length: Length of the hex digest used in placeholders. The
            default keeps placeholders short while remaining
            collision-free for typical pair sizes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_domains: tuple[str, ...] = ()
    brand_terms: tuple[str, ...] = ()
    theme_identifiers: tuple[str, ...] = ()
    product_titles: tuple[str, ...] = ()
    salt: str = Field(default=_DEFAULT_SALT, min_length=1)
    hash_length: int = Field(default=_HASH_LENGTH, ge=_HASH_MIN_LENGTH, le=_HASH_MAX_LENGTH)


def hash_token(value: str, *, salt: str = _DEFAULT_SALT, length: int = _HASH_LENGTH) -> str:
    """Return a deterministic short hex digest for ``value``.

    Used to map catalog identifiers (product handles, collection handles,
    distinctive titles) into stable opaque placeholders shared across both
    members of a judge pair (spec §5.5 step 3).

    Args:
        value: Text to hash. Hashed verbatim — callers normalize case if
            they want case-insensitive collisions.
        salt: Deterministic salt mixed in before hashing. Bumping the salt
            invalidates every previously-emitted placeholder.
        length: Number of leading hex chars to keep, ``4 <= length <= 64``.

    Returns:
        ``length`` lowercase hex characters from the SHA-256 digest of
        ``f"{salt}::{value}"``.

    Raises:
        ValueError: If ``length`` is outside ``[4, 64]``.
    """
    if not _HASH_MIN_LENGTH <= length <= _HASH_MAX_LENGTH:
        msg = f"hash_token length must be in [{_HASH_MIN_LENGTH}, {_HASH_MAX_LENGTH}], got {length}"
        raise ValueError(msg)
    digest = hashlib.sha256(f"{salt}::{value}".encode()).hexdigest()
    return digest[:length]


def anonymize_trajectory(trajectory: Trajectory, plan: AnonymizationPlan) -> Trajectory:
    """Return a brand-free copy of ``trajectory`` (spec §5.5 step 3).

    Rewrites the in-memory text fields of the trajectory schema (target
    label/url/notes, action descriptions and values, observation URLs and
    titles, step reasoning, top-level notes) according to ``plan`` and
    flips ``anonymized=True`` on the result. Evidence files referenced by
    :class:`shop_probe.report.EvidenceRef` rows are *not* rewritten here;
    pixel + HAR rewriting is a separate v1.1 workstream.

    Args:
        trajectory: A populated :class:`Trajectory`. Must validate against
            :mod:`shop_probe.judge.trajectory`.
        plan: Anonymization inputs (see :class:`AnonymizationPlan`).

    Returns:
        A new :class:`Trajectory` with brand-y text replaced and
        ``anonymized=True``.
    """
    rewriter = _Rewriter(plan)
    new_target = _anonymize_target(trajectory.target, rewriter)
    new_steps = tuple(_anonymize_step(step, rewriter) for step in trajectory.steps)
    return trajectory.model_copy(
        update={
            "target": new_target,
            "steps": new_steps,
            "anonymized": True,
            "notes": rewriter.rewrite_text(trajectory.notes),
        }
    )


# --------------------------------------------------------------------------- #
# Internal: per-trajectory rewriter
# --------------------------------------------------------------------------- #


class _Rewriter:
    """Stateless rewriter built once per anonymization call.

    Pre-compiles regex patterns so a long trajectory does not re-scan the
    plan for every rewrite. Domain matching is split into "host" (URL
    netloc) and "free-text occurrence" (substring inside descriptions /
    reasoning) because both leak the brand and both must be redacted.
    """

    def __init__(self, plan: AnonymizationPlan) -> None:
        self._plan = plan
        self._domains_lower: tuple[str, ...] = tuple(d.lower() for d in plan.source_domains)
        # Domains as substring patterns (with optional scheme), longest-first
        # to avoid partial-match shadowing (e.g. "example.com" before
        # "shop.example.com" would leak the parent domain).
        domain_alternatives = sorted(
            {d.strip() for d in plan.source_domains if d.strip()},
            key=len,
            reverse=True,
        )
        if domain_alternatives:
            scheme = r"(?:https?://)?"
            joined = "|".join(re.escape(d) for d in domain_alternatives)
            self._domain_re: re.Pattern[str] | None = re.compile(
                rf"{scheme}(?:{joined})", flags=re.IGNORECASE
            )
        else:
            self._domain_re = None

        brand_alternatives = sorted(
            {b.strip() for b in plan.brand_terms if b.strip()},
            key=len,
            reverse=True,
        )
        if brand_alternatives:
            joined = "|".join(re.escape(b) for b in brand_alternatives)
            self._brand_re: re.Pattern[str] | None = re.compile(
                rf"\b(?:{joined})\b", flags=re.IGNORECASE
            )
        else:
            self._brand_re = None

        theme_alternatives = sorted(
            {t.strip() for t in plan.theme_identifiers if t.strip()},
            key=len,
            reverse=True,
        )
        if theme_alternatives:
            joined = "|".join(re.escape(t) for t in theme_alternatives)
            self._theme_re: re.Pattern[str] | None = re.compile(
                rf"\b(?:{joined})\b", flags=re.IGNORECASE
            )
        else:
            self._theme_re = None

        # Product titles: longest-first so "Premium Widget Pro" is matched
        # before its prefix "Premium Widget".
        self._title_pairs: tuple[tuple[re.Pattern[str], str], ...] = tuple(
            (
                re.compile(re.escape(title), flags=re.IGNORECASE),
                f"product_{hash_token(title.lower(), salt=plan.salt, length=plan.hash_length)}",
            )
            for title in sorted(
                {t.strip() for t in plan.product_titles if t.strip()},
                key=len,
                reverse=True,
            )
        )

        # Catalog handles embedded in free text (e.g. inside HTML attribute
        # selectors like ``a[href="/products/premium-snowboard-pro"]``). The
        # path-rewriter only sees parsed URLs; this regex catches the same
        # handles when they appear in selectors or descriptions.
        prefixes = "|".join(re.escape(p) for p in _HANDLE_PREFIXES)
        self._handle_re: re.Pattern[str] = re.compile(
            rf"/({prefixes})/([A-Za-z0-9][A-Za-z0-9_\-.]*)"
        )

    # ------------------------------------------------------------------ #
    # Public rewrite entry points
    # ------------------------------------------------------------------ #

    def rewrite_text(self, value: str | None) -> str | None:
        """Return ``value`` with every brand / domain / title rewrite applied.

        ``None`` is returned unchanged so optional fields (e.g. ``notes``)
        keep their semantics across the transform.
        """
        if value is None:
            return None
        out = value
        # Order matters: domain first (so we don't strip a brand term that
        # happens to be a substring of the host), then product titles
        # (longest-first via pattern construction), then brand terms,
        # then theme identifiers.
        if self._domain_re is not None:
            out = self._domain_re.sub(REDACTED_HOST, out)
        out = self._handle_re.sub(self._handle_sub, out)
        for pattern, replacement in self._title_pairs:
            out = pattern.sub(replacement, out)
        if self._brand_re is not None:
            out = self._brand_re.sub(REDACTED_BRAND, out)
        if self._theme_re is not None:
            out = self._theme_re.sub(REDACTED_THEME, out)
        return out

    def _handle_sub(self, match: re.Match[str]) -> str:
        """Replace ``/<prefix>/<handle>`` with ``/<prefix>/<hash>``."""
        prefix = match.group(1)
        handle = match.group(2)
        hashed = hash_token(handle.lower(), salt=self._plan.salt, length=self._plan.hash_length)
        return f"/{prefix}/{hashed}"

    def rewrite_url(self, value: str | None) -> str | None:
        """Return ``value`` rewritten as a brand-free URL or ``None``.

        Hosts that match :attr:`AnonymizationPlan.source_domains` are
        replaced with :data:`REDACTED_HOST`; catalog identifiers in the
        path (after ``/products/`` etc.) are replaced with stable hashes.
        Hosts that do not match any plan domain are still rewritten to
        :data:`REDACTED_HOST` because the judge must not see *any* live
        host — the only host signal that survives anonymization is "some
        host" (spec §5.5 step 3).

        A non-URL string (no scheme, no path that starts with ``/``) is
        passed through :meth:`rewrite_text` so action ``value`` fields
        that hold a typed query rather than a URL are still cleaned.
        """
        if value is None:
            return None
        if not _looks_like_url(value):
            return self.rewrite_text(value)
        parts = urlsplit(value)
        scheme = parts.scheme or "https"
        netloc = REDACTED_HOST if parts.netloc or parts.scheme else parts.netloc
        path = self._rewrite_url_path(parts.path)
        # The query / fragment may carry brand-y values (e.g. ``?utm_source=Hardware``).
        # Run them through the text rewriter for a best-effort scrub.
        query = self.rewrite_text(parts.query) or ""
        fragment = self.rewrite_text(parts.fragment) or ""
        # If the input had no scheme but did start with "/", emit a
        # path-only URL so relative observation.url values stay relative.
        if not parts.scheme and not parts.netloc:
            return urlunsplit(("", "", path, query, fragment))
        return urlunsplit((scheme, netloc, path, query, fragment))

    def hash_name(self, name: str) -> str:
        """Return the redacted ``Target.name`` placeholder for ``name``."""
        return f"target_{hash_token(name, salt=self._plan.salt, length=self._plan.hash_length)}"

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _rewrite_url_path(self, path: str) -> str:
        """Hash catalog handles in a Shopify-shaped URL path.

        Only the segment that follows a recognized prefix
        (``/products/``, ``/collections/``, etc.) is hashed; trailing
        segments (e.g. ``/products/foo/variants/bar``) are also hashed
        using the same salt so structurally-meaningful identifiers do not
        leak through deeper paths.
        """
        if not path:
            return path
        segments = path.split("/")
        out: list[str] = []
        i = 0
        while i < len(segments):
            seg = segments[i]
            out.append(seg)
            if seg in _HANDLE_PREFIXES and i + 1 < len(segments):
                # Hash the handle and any trailing structural segments.
                for j in range(i + 1, len(segments)):
                    handle = segments[j]
                    if handle == "":
                        out.append(handle)
                    else:
                        out.append(
                            hash_token(
                                handle.lower(),
                                salt=self._plan.salt,
                                length=self._plan.hash_length,
                            )
                        )
                i = len(segments)
                continue
            i += 1
        return "/".join(out)


def _anonymize_target(target: Target, rewriter: _Rewriter) -> Target:
    """Return ``target`` with name / base_url / notes redacted."""
    redacted_url = rewriter.rewrite_url(target.base_url) or f"https://{REDACTED_HOST}/"
    return target.model_copy(
        update={
            "name": rewriter.hash_name(target.name),
            "base_url": redacted_url,
            "notes": rewriter.rewrite_text(target.notes),
        }
    )


def _anonymize_action(action: TrajectoryAction, rewriter: _Rewriter) -> TrajectoryAction:
    """Return ``action`` with text fields redacted."""
    return action.model_copy(
        update={
            "selector": rewriter.rewrite_text(action.selector),
            "value": rewriter.rewrite_url(action.value),
            "description": rewriter.rewrite_text(action.description) or action.description,
        }
    )


def _anonymize_observation(
    observation: TrajectoryObservation, rewriter: _Rewriter
) -> TrajectoryObservation:
    """Return ``observation`` with URL + title redacted."""
    return observation.model_copy(
        update={
            "url": rewriter.rewrite_url(observation.url),
            "title": rewriter.rewrite_text(observation.title),
        }
    )


def _anonymize_step(step: TrajectoryStep, rewriter: _Rewriter) -> TrajectoryStep:
    """Return ``step`` with action / observation / reasoning redacted."""
    return step.model_copy(
        update={
            "action": _anonymize_action(step.action, rewriter),
            "observation": _anonymize_observation(step.observation, rewriter),
            "reasoning": rewriter.rewrite_text(step.reasoning) or "",
        }
    )


def _looks_like_url(value: str) -> bool:
    """Return True when ``value`` should be treated as a URL by the rewriter.

    A best-effort heuristic: anything with an explicit ``http(s)://`` scheme
    or a leading ``/`` is treated as a URL; everything else (free-form
    queries, search input, etc.) is rewritten as plain text.
    """
    if value.startswith(("http://", "https://")):
        return True
    return value.startswith("/")
