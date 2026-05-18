"""Stateful rule executor + LLM state-namer (spec §5.5.2, M5).

This module owns the M5 stateful pass of the transition layer: a rule
fires a single Playwright interaction, EnvEval computes a structural
diff against the pre-action axtree, and only on a true diff does the
state-namer LLM disambiguate the resulting state's name from a closed
enum (spec §5.5.2).

What lives here:

* :class:`StructuralFingerprint` + :func:`compute_structural_fingerprint`
  + :func:`fingerprints_differ` — the closed
  ``(node_count, role_histogram, set_of_bids)`` diff (impl-plan M0
  decision).  Same axtree shape both passes already use, no Playwright
  dependency, fully testable from a fixture.
* :func:`resolve_selector` — landmark-scoped axtree walk that returns
  the BrowserGym ``bid`` of the first node whose role + name match a
  :class:`~shop_arena.env_eval.transition.rules.Selector`.  Pure
  axtree, never reads the DOM.
* :data:`STATE_NAMES` + :data:`STATE_RESPONSE_SCHEMA` +
  :func:`load_state_prompt` — the closed v0.1 state-namer prompt
  contract; mirrors the rubric module's pattern.
* :class:`StateNameArtifact` + :func:`write_state_artifact` — pydantic
  v2 schema for the temporary state-namer JSON used while constructing a
  state node: prompt version, model, temperature, triggering rule/action,
  raw response, parsed state name, parse errors, pre/post screenshot paths,
  and pre/post axtree paths.
* :func:`name_state` — single vision call wrapper that forwards the
  pre + post screenshots and the rule context, then validates the
  response against :data:`STATE_RESPONSE_SCHEMA`.  Parse failures
  collapse to ``state="no_change"`` with non-empty ``parse_errors`` so
  the artifact is always schema-valid (mirrors the rubric module).
* :class:`RuleResult` + :func:`execute_rule` — the high-level
  entrypoint: re-load page, resolve selector, take pre-screenshot and
  pre-axtree, execute action, wait for ``networkidle``, take post-screenshot
  and post-axtree, structural diff, call state-namer only on diff. Skips
  silently when the rule needs a derived query and none is available
  (spec §5.5.2).

Pipeline glue (extending the transition graph with state nodes/edges,
appending lines to ``trace.jsonl``, recomputing
``metrics.transition``) lives in :mod:`shop_arena.env_eval.pipeline` and
re-uses this module's :class:`RuleResult` so the executor stays free of
filesystem state and graph mutation.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING, Any, Final, Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shop_arena.env_eval.observation.axtree_text import render_axtree_text
from shop_arena.env_eval.transition import node_artifacts as node_artifacts_mod
from shop_arena.env_eval.transition.rules import (
    RULE_STATE_NAMES,
    Rule,
    Selector,
)
from shop_arena.util._llm import (
    DEFAULT_RUBRIC_TEMPERATURE,
    LLMVisionClient,
    VisionResponse,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    import playwright.sync_api


__all__ = [
    "DEFAULT_AXTREE_MAX_WAIT_MS",
    "DEFAULT_AXTREE_MIN_WAIT_HOMEPAGE_MS",
    "DEFAULT_AXTREE_POLL_INTERVAL_MS",
    "DEFAULT_AXTREE_STABLE_MS",
    "DEFAULT_NETWORKIDLE_TIMEOUT_MS",
    "STATEFUL_PHASE",
    "STATE_NAMES",
    "STATE_PROMPT_VERSION",
    "STATE_RESPONSE_SCHEMA",
    "RuleOutcome",
    "RuleResult",
    "StateName",
    "StateNameArtifact",
    "StateResponse",
    "StatefulAttempt",
    "StructuralFingerprint",
    "build_state_prompt_payload",
    "compute_structural_fingerprint",
    "execute_rule",
    "fingerprints_differ",
    "load_state_prompt",
    "name_state",
    "resolve_selector",
    "run_stateful_pass",
    "state_node_id",
    "wait_for_axtree_settle",
    "write_state_artifact",
    "write_stateful_trace_lines",
]


#: Version of the state-namer prompt + response schema (spec §5.5.2,
#: impl-plan M5).  Bumped on any contract-affecting change (prompt body,
#: response enum, or call shape) and persisted in every state-node
#: ``transition/node/<node>/node.json`` so cohorts of artifacts can be
#: filtered by version. ``0.2`` forwarded both pre- and post-action
#: screenshots; ``0.3`` adds ``mega_menu`` to the closed state enum so
#: the new ``homepage_open_mega_menu`` rule (rules.py v0.3) has a
#: canonical name to map to.
STATE_PROMPT_VERSION: Final[str] = "0.3"

#: Closed enum of state names the state-namer may emit.  Strict superset
#: of :data:`shop_arena.env_eval.transition.rules.RULE_STATE_NAMES`: the
#: nine rule-emitted states plus the three LLM-only entries
#: (``popup_modal``, ``other``, ``no_change``).
StateName = Literal[
    "announcement_dismissed",
    "cart_drawer",
    "cart_qty_changed",
    "filter_panel_open",
    "mega_menu",
    "no_change",
    "other",
    "popup_modal",
    "predictive_panel",
    "search_overlay",
    "sort_menu_open",
    "variant_select_open",
]
STATE_NAMES: Final[tuple[StateName, ...]] = get_args(StateName)

#: JSON schema sent to the vision client.  Closed enum + closed object
#: shape; mirrors the rubric module's pattern.
STATE_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "state": {
            "type": "string",
            "enum": list(STATE_NAMES),
        },
    },
    "required": ["state"],
    "additionalProperties": False,
}

#: importlib package + filename the prompt body is loaded from.
_PROMPT_PACKAGE: Final[str] = "shop_arena.env_eval.transition"
_PROMPT_FILENAME: Final[str] = "state_prompt.md"

#: Divider that separates the documentation header from the prompt body.
_PROMPT_DIVIDER: Final[str] = "\n---\n"

#: Default ``page.wait_for_load_state("networkidle")`` timeout, in ms.
#: SandboxShops served from Cloud Run can take 1-2s for an XHR-driven
#: cart drawer to settle; ``5000`` is generous enough that a real diff
#: never gets clipped by the timeout but tight enough that an unresponsive
#: page does not stall the run.  Per-rule overrides flow through
#: :func:`execute_rule`.
DEFAULT_NETWORKIDLE_TIMEOUT_MS: Final[int] = 5_000

#: Default poll interval for :func:`wait_for_axtree_settle`, in ms.  Tight
#: enough to catch a fade-in animation, loose enough that the polling does
#: not dominate runtime on a stable page.
DEFAULT_AXTREE_POLL_INTERVAL_MS: Final[int] = 200

#: How long the axtree fingerprint must remain unchanged before
#: :func:`wait_for_axtree_settle` declares the page settled.  Empirically
#: tuned: 800ms covers typical CSS transition durations (200-500ms) plus a
#: safety margin for late JS-driven mutations (analytics widgets, lazy
#: chat launchers).
DEFAULT_AXTREE_STABLE_MS: Final[int] = 800

#: Hard cap on :func:`wait_for_axtree_settle`.  Pages that keep mutating
#: past this point (autoplaying carousels, infinite scroll observers,
#: long-running animations) are accepted as "unsettleable" and the caller
#: snapshots whatever is currently rendered rather than waiting forever.
#: Bumped from 5s to 8s in v0.3 to give the homepage popup-wait floor
#: (3.5s) at least 4.5s of stable-window headroom on top of it.
DEFAULT_AXTREE_MAX_WAIT_MS: Final[int] = 8_000

#: Minimum wait floor used when capturing the homepage URL node.  Email-
#: signup popups (Klaviyo, Privy, OptinMonster) typically fire on a 2-4s
#: ``setTimeout`` after the page becomes interactive.  Without a floor,
#: :func:`wait_for_axtree_settle` exits at ``stable_ms`` (800ms) because
#: the axtree fingerprint is already stable — hero animations are pure
#: CSS and don't mutate the DOM — and the popup never gets a chance to
#: re-arm the stability timer.  3.5s covers Klaviyo's default delay with
#: a 500ms safety margin; later mutations still re-arm the timer up to
#: ``DEFAULT_AXTREE_MAX_WAIT_MS``.  Other surfaces (collection / product /
#: cart) almost never trigger first-load popups, so this cost is paid
#: once per shop on the homepage capture only — see
#: ``shop_arena.env_eval.pipeline._capture_url_node_artifact``.
DEFAULT_AXTREE_MIN_WAIT_HOMEPAGE_MS: Final[int] = 3_500


# ---------------------------------------------------------------------------
# Structural fingerprint (impl-plan M0 decision).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StructuralFingerprint:
    """Snapshot of an axtree used to detect whether a rule changed the page.

    Spec §5.5.2 + impl-plan M0 decision: a rule "fires" when the
    pre/post axtree differ on at least one of three orthogonal axes.
    Capturing all three keeps the diff resilient to BrowserGym renumbering
    bids without a real DOM change (only the bid set differs) and to a
    cosmetic role flip (only the histogram differs).

    Attributes:
        node_count: ``len(axtree["nodes"])`` after dropping non-mapping
            entries.
        role_histogram: Frozen ``role -> count`` map; nodes without a
            role contribute nothing.  Stored as a regular ``dict`` so the
            equality check in :func:`fingerprints_differ` stays cheap and
            obvious; the dataclass is frozen so the dict is not mutated
            after construction.
        bids: Set of every BrowserGym ``bid`` present on the page.
            ``frozenset`` because two equal sets compare equal regardless
            of insertion order.
    """

    node_count: int
    role_histogram: Mapping[str, int]
    bids: frozenset[str]


def compute_structural_fingerprint(axtree: Mapping[str, Any]) -> StructuralFingerprint:
    """Return the :class:`StructuralFingerprint` for ``axtree``.

    Pure function — no Playwright, no DOM, no network.  Tolerates
    malformed nodes (missing role / missing bid / non-mapping entries)
    rather than raising so a partially-rendered page does not abort the
    stateful pass.

    Args:
        axtree: BrowserGym/CDP merged-axtree object.  ``axtree["nodes"]``
            is consulted; everything else is ignored.

    Returns:
        Frozen :class:`StructuralFingerprint`.

    Raises:
        TypeError: ``axtree`` is not a mapping or its ``nodes`` is not a
            list.  Per-node malformations are tolerated.
    """
    if not isinstance(axtree, Mapping):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(f"axtree must be a mapping, got {type(axtree).__name__}")
    raw_nodes: object = axtree.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raise TypeError(
            f"axtree['nodes'] must be a list, got {type(raw_nodes).__name__}",
        )

    role_counter: Counter[str] = Counter()
    bids: set[str] = set()
    node_count = 0
    for raw_node in cast("list[object]", raw_nodes):
        if not isinstance(raw_node, Mapping):
            continue
        node = cast("Mapping[str, Any]", raw_node)
        node_count += 1
        role = _node_role(node)
        if role:
            role_counter[role] += 1
        bid = _node_bid(node)
        if bid is not None:
            bids.add(bid)
    return StructuralFingerprint(
        node_count=node_count,
        role_histogram=dict(role_counter),
        bids=frozenset(bids),
    )


def fingerprints_differ(
    pre: StructuralFingerprint,
    post: StructuralFingerprint,
) -> bool:
    """Return ``True`` when ``pre`` and ``post`` differ on any of the three axes."""
    return (
        pre.node_count != post.node_count
        or pre.role_histogram != post.role_histogram
        or pre.bids != post.bids
    )


def wait_for_axtree_settle(
    *,
    axtree: Callable[[], Mapping[str, Any]],
    poll_interval_ms: int = DEFAULT_AXTREE_POLL_INTERVAL_MS,
    stable_ms: int = DEFAULT_AXTREE_STABLE_MS,
    min_wait_ms: int = 0,
    max_wait_ms: int = DEFAULT_AXTREE_MAX_WAIT_MS,
) -> None:
    """Block until the merged-axtree fingerprint stops changing.

    Polls ``axtree`` every ``poll_interval_ms`` and returns once both
    invariants hold:

    1. at least ``min_wait_ms`` has elapsed since polling started, **and**
    2. the fingerprint has been identical for at least ``stable_ms``
       consecutive milliseconds.

    Returns early if ``max_wait_ms`` is reached (hard cap).  Designed to
    catch JS-only DOM mutations that ``networkidle`` does not surface:
    ``setTimeout``-driven popups, hover-then-fade-in mega menus, exit-
    intent overlays, late-binding chat widgets.

    The ``min_wait_ms`` floor exists because some popup vendors (Klaviyo,
    Privy) fire on a 2-4s timer that never re-arms the stability counter:
    when the axtree is already stable (e.g. a hero whose cross-fade is
    pure CSS), settle would otherwise return at ``stable_ms`` (800ms),
    long before the popup mounts.  Callers that don't expect a delayed
    popup leave ``min_wait_ms=0`` and pay no extra latency.

    Callers are responsible for any ``page.wait_for_load_state`` /
    ``networkidle`` wait they want; this helper only consults the axtree.
    The polling loop runs under :func:`contextlib.suppress` so a transient
    failure inside ``axtree()`` (rare, but possible if the page navigates
    mid-poll) falls through to the caller's own snapshot path instead of
    aborting the run — settle is best-effort, not load-bearing.

    Args:
        axtree: Callable returning the merged-axtree dict.  Typically
            :meth:`shop_arena.env_eval.env.EnvEvalSession.axtree`.
        poll_interval_ms: Sleep between fingerprint polls.
        stable_ms: How long the fingerprint must remain identical before
            the page is declared settled.
        min_wait_ms: Floor on total time spent inside the function before
            settle is allowed to return.  Defaults to ``0`` (no floor).
            Surfaces that expect a ``setTimeout``-driven popup pass
            :data:`DEFAULT_AXTREE_MIN_WAIT_HOMEPAGE_MS` instead.
        max_wait_ms: Hard cap on total time spent inside the function.
            ``<= 0`` skips polling entirely, which is the documented seam
            tests use to keep their runtime tight.
    """
    if max_wait_ms <= 0:
        return
    with contextlib.suppress(Exception):
        started = time.monotonic()
        deadline = started + max_wait_ms / 1000.0
        last_fp = compute_structural_fingerprint(axtree())
        stable_since = started
        while time.monotonic() < deadline:
            time.sleep(poll_interval_ms / 1000.0)
            now = time.monotonic()
            fp = compute_structural_fingerprint(axtree())
            if fp == last_fp:
                stable_for_ms = (now - stable_since) * 1000
                elapsed_ms = (now - started) * 1000
                if stable_for_ms >= stable_ms and elapsed_ms >= min_wait_ms:
                    return
            else:
                last_fp = fp
                stable_since = now
# ---------------------------------------------------------------------------
# Selector resolution (axtree-only).
# ---------------------------------------------------------------------------


def resolve_selector(
    axtree: Mapping[str, Any],
    selector: Selector,
) -> str | None:
    """Return the BrowserGym ``bid`` of the first node matching ``selector``.

    Resolution rules (spec §5.5.2):

    1. Find the first axtree node whose role equals ``selector.landmark``
       (``banner`` or ``main``).  When the page has no such landmark,
       return ``None`` — the rule cannot fire.
    2. Walk the landmark's subtree in pre-order DFS (childIds order).
    3. Return the first descendant whose role is in ``selector.roles``
       and whose accessible name matches ``selector.name_pattern``.
       Roles are tried in tuple order; on themes that expose the same
       affordance under multiple roles (e.g. a header cart marked up
       as ``link`` on one theme and ``button`` on another), the first
       matching descendant wins.
    4. Skip nodes without a ``browsergym_id`` (the executor needs a bid
       to drive the action via Playwright); keep walking until a
       matchable node turns up.

    The walk is iterative + cycle-guarded so a malformed axtree cannot
    hang the run.

    Args:
        axtree: BrowserGym/CDP merged-axtree object.
        selector: Compiled rule selector.

    Returns:
        The matched node's ``browsergym_id`` string, or ``None`` when no
        landmark/role/name combination matches.
    """
    nodes_by_id, root_children = _index_axtree(axtree)
    landmark_id = _find_landmark_id(nodes_by_id, root_children, selector.landmark)
    if landmark_id is None:
        return None

    visited: set[str] = set()
    stack: list[str] = [landmark_id]
    while stack:
        node_id = stack.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        node = nodes_by_id.get(node_id)
        if node is None:
            continue
        # The landmark itself never matches the rule's role (rules never
        # target ``banner``/``main`` directly).
        # The landmark itself never matches the rule's role (rules never
        # target ``banner``/``main`` directly).
        if (
            node_id != landmark_id
            and _node_role(node) in selector.roles
            and selector.name_pattern.search(_node_name(node))
        ):
            bid = _node_bid(node)
            if bid is not None:
                return bid
        # Push children in reverse so iterative DFS visits them
        # left-to-right (matching the document order BrowserGym emits).
        for child_id in reversed(_node_child_ids(node)):
            if child_id not in visited:
                stack.append(child_id)
    return None


# ---------------------------------------------------------------------------
# State-namer prompt + LLM glue.
# ---------------------------------------------------------------------------


def load_state_prompt() -> str:
    """Return the state-namer prompt body (text after the first ``---``).

    Mirrors :func:`shop_arena.env_eval.observation.rubric.load_rubric_prompt`:
    the on-disk asset is a Markdown file with a documentation header,
    a single ``---`` divider, and the verbatim prompt body the model
    sees.

    Returns:
        Prompt body as a UTF-8 string with a single trailing newline.

    Raises:
        RuntimeError: ``state_prompt.md`` is missing the ``---`` divider.
    """
    text = resources.files(_PROMPT_PACKAGE).joinpath(_PROMPT_FILENAME).read_text(encoding="utf-8")
    if _PROMPT_DIVIDER not in text:
        raise RuntimeError(
            f"{_PROMPT_FILENAME} is missing the required '---' divider between "
            "the documentation header and the prompt body",
        )
    body = text.split(_PROMPT_DIVIDER, 1)[1]
    return body.strip() + "\n"


def build_state_prompt_payload(rule: Rule, base_prompt: str | None = None) -> str:
    """Return the prompt body augmented with the triggering-rule context.

    The state-namer needs three pieces of caller-supplied context to
    name a state confidently:

    * which rule fired (so an "open cart drawer" prompt does not get
      confused with "add to cart"),
    * which Playwright verb the rule used,
    * what the rule guessed the resulting state would be.

    All three are appended below the canonical prompt body in a fixed
    one-line format so the schema can stay unchanged across the rule
    table's evolution.

    Args:
        rule: Triggering :class:`Rule`.
        base_prompt: Override for the bundled prompt body.  Defaults to
            :func:`load_state_prompt`.

    Returns:
        ``"<base_prompt>\\nTriggering rule: ...\\nAction: ...\\nExpected state: ..."``
    """
    body = base_prompt if base_prompt is not None else load_state_prompt()
    suffix = (
        f"Triggering rule: {rule.id}\n"
        f"Action: {rule.action}\n"
        f"Expected state: {rule.expected_state}\n"
    )
    return body.rstrip() + "\n\n" + suffix


class StateResponse(BaseModel):
    """Closed schema for the state-namer's parsed response.

    Mirrors :data:`STATE_RESPONSE_SCHEMA` exactly so the same closed
    contract is enforced both at the wire boundary (provider's strict
    JSON schema) and in Python (pydantic validation of the parsed
    mapping).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: StateName


class StateNameArtifact(BaseModel):
    """Closed schema for the temporary state-namer attempt JSON.

    Records every input + output of one rule attempt before that data is
    folded into the corresponding ``transition/node/<node>/node.json``.

    Attributes:
        prompt_version: :data:`STATE_PROMPT_VERSION` at write time.
        model: Vision-client model id (e.g. ``"claude-sonnet-4-6"``).
        temperature: Requested sampling temperature (provider-side
            fixed-temperature models still record the request).
        rule_id: Triggering rule's :attr:`Rule.id`.
        action: Triggering rule's :attr:`Rule.action`.
        expected_state: Triggering rule's :attr:`Rule.expected_state`.
        state: Parsed state name.  ``"no_change"`` when the response
            could not be validated; see ``parse_errors``.
        raw_response: Provider-agnostic textual record of the response,
            persisted verbatim.
        parse_errors: Tuple of human-readable parse errors.  Empty on a
            clean call.
        pre_screenshot: Temporary-workspace path to the pre-action screenshot.
        post_screenshot: Temporary-workspace path to the post-action screenshot.
        pre_axtree: Run-relative POSIX path to the pre-action axtree JSON.
        pre_axtree_text: Run-relative POSIX path to the pre-action text axtree.
        post_axtree: Run-relative POSIX path to the post-action axtree JSON.
        post_axtree_text: Run-relative POSIX path to the post-action text axtree.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_version: str = Field(min_length=1)
    model: str = Field(min_length=1)
    temperature: float = Field(ge=0.0)
    rule_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    expected_state: str = Field(min_length=1)
    state: StateName
    raw_response: str
    parse_errors: tuple[str, ...] = ()
    pre_screenshot: str = Field(min_length=1)
    post_screenshot: str = Field(min_length=1)
    pre_axtree: str | None = None
    pre_axtree_text: str | None = None
    post_axtree: str | None = None
    post_axtree_text: str | None = None


def name_state(
    client: LLMVisionClient,
    *,
    rule: Rule,
    pre_png: bytes,
    post_png: bytes,
    temperature: float = DEFAULT_RUBRIC_TEMPERATURE,
    prompt: str | None = None,
) -> tuple[StateName, str, tuple[str, ...]]:
    """Run the state-namer against ``client`` and return its decision.

    The function never raises on a malformed response: parse failures
    collapse to ``state="no_change"`` plus non-empty ``parse_errors`` so
    the artifact is always schema-valid (mirrors the rubric module).
    Configuration errors (missing API keys, text-only model dispatch)
    still bubble up from the client because they are caller bugs.

    Args:
        client: Any concrete :class:`LLMVisionClient`.  Tests inject a fake.
        rule: Triggering rule (passed verbatim into the prompt suffix and
            stored in the artifact).
        pre_png: PNG-encoded pre-action screenshot bytes.  Forwarded as
            the first image so ``state_prompt.md``'s "first taken
            immediately before" wording matches the wire ordering.
        post_png: PNG-encoded post-action screenshot bytes.  Forwarded as
            the second image so the model can actually compare pre/post
            the way the prompt instructs.
        temperature: Sampling temperature forwarded to the client.
        prompt: Override for the prompt body.

    Returns:
        ``(state, raw_response, parse_errors)``.
    """
    body = build_state_prompt_payload(rule, prompt)
    response = client.call(
        prompt=body,
        images=(pre_png, post_png),
        schema=STATE_RESPONSE_SCHEMA,
        temperature=temperature,
    )
    state, parse_errors = _validate_state_response(response)
    return state, response.raw_response, parse_errors


def write_state_artifact(artifact: StateNameArtifact, path: Path) -> Path:
    """Serialise ``artifact`` to ``path`` as deterministic JSON.

    Output format mirrors the other run-directory artifacts: two-space
    indent, sorted top-level keys, trailing newline.
    """
    payload = artifact.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Rule executor.
# ---------------------------------------------------------------------------


#: Closed outcome enum recorded in :class:`RuleResult`.
#:
#: * ``"fired"`` — selector resolved, action executed, structural diff
#:   detected, state-namer was called.
#: * ``"no_diff"`` — selector resolved, action executed, but the
#:   structural fingerprint did not change; LLM was not called.
#: * ``"no_target"`` — selector did not resolve (no landmark, no
#:   matching role+name pair).  Action was not executed.
#: * ``"skipped_no_query"`` — rule needs a derived query and none is
#:   available (spec §5.5.2).  Nothing executed; no LLM call.
#: * ``"exec_error"`` — selector resolved but Playwright raised while
#:   executing the action (timeout, detached element, …).
#: * ``"load_error"`` — re-loading the page failed before the rule
#:   could be evaluated.
RuleOutcome = Literal[
    "fired",
    "no_diff",
    "no_target",
    "skipped_no_query",
    "exec_error",
    "load_error",
]


@dataclass(frozen=True, slots=True)
class RuleResult:
    """Outcome of one :func:`execute_rule` call.

    The pipeline (M5 wiring) consumes this to decide whether to extend
    the transition graph with a new state node + edge and to append a
    line to ``trace.jsonl``. Artifact paths are :class:`Path` objects so
    callers can either copy files or normalise them to run-relative strings.

    Attributes:
        rule_id: Rule's :attr:`Rule.id`.
        page_class: Rule's :attr:`Rule.page_class`.
        page_url: Concrete URL the rule ran on (the page-class entry
            from ``pages.json``).
        outcome: One of :data:`RuleOutcome`.
        bid: BrowserGym id of the resolved target, or ``None``.
        state: Parsed state name when ``outcome == "fired"``, else ``None``.
        artifact_path: Path to the state-namer JSON artifact when
            ``outcome == "fired"``, else ``None``.
        pre_screenshot_path: Path to the pre-action screenshot, or
            ``None`` when no screenshot was taken.
        post_screenshot_path: Path to the post-action screenshot, or
            ``None`` when no screenshot was taken.
        pre_axtree_path: Path to the pre-action axtree JSON, or ``None``.
        pre_axtree_text_path: Path to the pre-action text axtree, or ``None``.
        post_axtree_path: Path to the post-action axtree JSON, or ``None``.
        post_axtree_text_path: Path to the post-action text axtree, or ``None``.
        parse_errors: Forwarded from :func:`name_state`; empty unless
            ``outcome == "fired"`` *and* the LLM response was malformed.
        error: Human-readable error message when ``outcome`` is
            ``"exec_error"`` or ``"load_error"``, else ``None``.
    """

    rule_id: str
    page_class: str
    page_url: str
    outcome: RuleOutcome
    bid: str | None = None
    state: StateName | None = None
    artifact_path: Path | None = None
    pre_screenshot_path: Path | None = None
    post_screenshot_path: Path | None = None
    pre_axtree_path: Path | None = None
    pre_axtree_text_path: Path | None = None
    post_axtree_path: Path | None = None
    post_axtree_text_path: Path | None = None
    parse_errors: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _ExecutionDeps:
    """Bundle of injectable dependencies driven by :func:`execute_rule`.

    Centralising them in a frozen dataclass keeps the executor's
    signature short and makes it trivial for tests to substitute fakes
    without monkey-patching module-level functions.
    """

    goto: Callable[[str], object]
    axtree: Callable[[], Mapping[str, Any]]
    screenshot_png: Callable[[], bytes]
    page: playwright.sync_api.Page | None


def execute_rule(
    rule: Rule,
    *,
    page_url: str,
    derived_query: str | None,
    states_dir: Path,
    state_id: str,
    llm_client: LLMVisionClient | None,
    goto: Callable[[str], object],
    axtree: Callable[[], Mapping[str, Any]],
    screenshot_png: Callable[[], bytes],
    page: playwright.sync_api.Page | None,
    networkidle_timeout_ms: int = DEFAULT_NETWORKIDLE_TIMEOUT_MS,
    temperature: float = DEFAULT_RUBRIC_TEMPERATURE,
) -> RuleResult:
    """Run one :class:`Rule` end-to-end and return its :class:`RuleResult`.

    The executor:

    1. Skips the rule when ``rule.needs_derived_query`` is ``True`` and
       ``derived_query`` is ``None``/empty (spec §5.5.2).
    2. Re-loads ``page_url`` so each rule starts from a clean state
       (the previous rule may have left a drawer open).
    3. Captures the pre-action axtree + screenshot.
    4. Resolves :attr:`Rule.selector` against the axtree; bails as
       ``"no_target"`` when no landmark/role/name combination matches.
    5. Executes the action via the BrowserGym ``get_elem_by_bid``
       locator (``click`` / ``fill <derived_query>``).
    6. Waits for ``networkidle`` (or :data:`DEFAULT_NETWORKIDLE_TIMEOUT_MS`).
    7. Captures the post-action axtree + screenshot.
    8. Computes the structural diff; bails as ``"no_diff"`` when the
       fingerprint did not change.
    9. Calls the state-namer LLM and writes temporary per-attempt JSON plus
       pre/post PNG and axtree files. The caller folds those into the final
       state-node folder under ``transition/node/``.

    Args:
        rule: Rule to attempt.
        page_url: Concrete URL of the page the rule fires on.
        derived_query: Search query inferred by page selection (spec §5.2).
            Required when ``rule.needs_derived_query`` is ``True``.
        states_dir: Temporary workspace directory for the per-attempt artifacts.
            Must already exist. Production callers delete it after the state-node
            folders have been written.
        state_id: Identifier for this attempt's artifacts
            (``<state_id>.{pre,post}.*`` + ``<state_id>.json``). Caller is
            responsible for uniqueness.
        llm_client: Vision client to call when the diff fires.  Required
            unless the executor short-circuits before the LLM call (any
            ``"no_diff"``/``"no_target"``/``"skipped_no_query"``/
            ``"exec_error"``/``"load_error"`` path).
        goto: Callable used to (re)navigate to ``page_url``.  Wraps
            :class:`shop_arena.env_eval.env.EnvEvalSession.goto` in
            production; tests inject a stub.
        axtree: Callable returning the live merged-axtree dict.
        screenshot_png: Callable returning PNG-encoded screenshot bytes
            for the active page.
        page: Live Playwright page used to resolve the bid + dispatch the
            action.  ``None`` is accepted only for ``"skipped_no_query"``
            paths (tests that do not exercise the executor's Playwright
            branch).
        networkidle_timeout_ms: Override for the post-action
            ``wait_for_load_state("networkidle")`` timeout, in ms.
        temperature: Sampling temperature forwarded to ``llm_client``.

    Returns:
        Populated :class:`RuleResult`.
    """
    if rule.needs_derived_query and not derived_query:
        return RuleResult(
            rule_id=rule.id,
            page_class=rule.page_class,
            page_url=page_url,
            outcome="skipped_no_query",
        )

    deps = _ExecutionDeps(
        goto=goto,
        axtree=axtree,
        screenshot_png=screenshot_png,
        page=page,
    )

    try:
        deps.goto(page_url)
    except Exception as exc:
        return RuleResult(
            rule_id=rule.id,
            page_class=rule.page_class,
            page_url=page_url,
            outcome="load_error",
            error=f"goto({page_url!r}) raised: {exc!r}",
        )

    pre_axtree = deps.axtree()
    bid = resolve_selector(pre_axtree, rule.selector)
    if bid is None:
        return RuleResult(
            rule_id=rule.id,
            page_class=rule.page_class,
            page_url=page_url,
            outcome="no_target",
        )

    pre_png = deps.screenshot_png()
    pre_path = states_dir / f"{state_id}.pre.png"
    pre_path.write_bytes(pre_png)
    pre_axtree_path = states_dir / f"{state_id}.pre.axtree.json"
    pre_axtree_text_path = states_dir / f"{state_id}.pre.axtree.txt"
    _write_axtree_artifacts(pre_axtree, pre_axtree_path, pre_axtree_text_path)
    pre_fp = compute_structural_fingerprint(pre_axtree)

    try:
        _execute_action(
            page=deps.page,
            rule=rule,
            bid=bid,
            derived_query=derived_query,
            networkidle_timeout_ms=networkidle_timeout_ms,
        )
    except Exception as exc:
        return RuleResult(
            rule_id=rule.id,
            page_class=rule.page_class,
            page_url=page_url,
            outcome="exec_error",
            bid=bid,
            pre_screenshot_path=pre_path,
            pre_axtree_path=pre_axtree_path,
            pre_axtree_text_path=pre_axtree_text_path,
            error=f"{rule.action}({bid!r}) raised: {exc!r}",
        )

    # Wait for delayed DOM mutations (setTimeout-driven popups, fade-in
    # animations on the freshly-opened panel, late-binding chat widgets)
    # before snapshotting; ``networkidle`` alone misses JS-only changes.
    wait_for_axtree_settle(axtree=deps.axtree)

    post_axtree = deps.axtree()
    post_png = deps.screenshot_png()
    post_path = states_dir / f"{state_id}.post.png"
    post_path.write_bytes(post_png)
    post_axtree_path = states_dir / f"{state_id}.post.axtree.json"
    post_axtree_text_path = states_dir / f"{state_id}.post.axtree.txt"
    _write_axtree_artifacts(post_axtree, post_axtree_path, post_axtree_text_path)
    post_fp = compute_structural_fingerprint(post_axtree)

    if not fingerprints_differ(pre_fp, post_fp):
        return RuleResult(
            rule_id=rule.id,
            page_class=rule.page_class,
            page_url=page_url,
            outcome="no_diff",
            bid=bid,
            pre_screenshot_path=pre_path,
            post_screenshot_path=post_path,
            pre_axtree_path=pre_axtree_path,
            pre_axtree_text_path=pre_axtree_text_path,
            post_axtree_path=post_axtree_path,
            post_axtree_text_path=post_axtree_text_path,
        )

    if llm_client is None:
        raise RuntimeError(
            "execute_rule reached the state-namer step with llm_client=None; "
            "callers must supply a vision client when they want stateful diffs to "
            "be named (use rule.expected_state directly otherwise).",
        )

    state, raw_response, parse_errors = name_state(
        llm_client,
        rule=rule,
        pre_png=pre_png,
        post_png=post_png,
        temperature=temperature,
    )
    artifact = StateNameArtifact(
        prompt_version=STATE_PROMPT_VERSION,
        model=llm_client.model,
        temperature=temperature,
        rule_id=rule.id,
        action=rule.action,
        expected_state=rule.expected_state,
        state=state,
        raw_response=raw_response,
        parse_errors=parse_errors,
        pre_screenshot=pre_path.name,
        post_screenshot=post_path.name,
        pre_axtree=pre_axtree_path.name,
        pre_axtree_text=pre_axtree_text_path.name,
        post_axtree=post_axtree_path.name,
        post_axtree_text=post_axtree_text_path.name,
    )
    artifact_path = states_dir / f"{state_id}.json"
    write_state_artifact(artifact, artifact_path)

    return RuleResult(
        rule_id=rule.id,
        page_class=rule.page_class,
        page_url=page_url,
        outcome="fired",
        bid=bid,
        state=state,
        artifact_path=artifact_path,
        pre_screenshot_path=pre_path,
        post_screenshot_path=post_path,
        pre_axtree_path=pre_axtree_path,
        pre_axtree_text_path=pre_axtree_text_path,
        post_axtree_path=post_axtree_path,
        post_axtree_text_path=post_axtree_text_path,
        parse_errors=parse_errors,
    )


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------


def _write_axtree_artifacts(
    axtree: Mapping[str, Any],
    json_path: Path,
    text_path: Path,
) -> None:
    """Write a stateful pre/post axtree as JSON plus deterministic text."""
    json_path.write_text(
        json.dumps(axtree, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    text = render_axtree_text(axtree)
    text_path.write_text(text + "\n" if text else "", encoding="utf-8")


def _json_default(value: object) -> object:
    """Best-effort JSON encoder for axtree payloads with numpy / set values."""
    if isinstance(value, (set, frozenset)):
        return sorted(cast("set[Any] | frozenset[Any]", value))
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return cast("Any", tolist)()
    raise TypeError(f"axtree contains non-JSON value of type {type(value).__name__}")


def _execute_action(
    *,
    page: playwright.sync_api.Page | None,
    rule: Rule,
    bid: str,
    derived_query: str | None,
    networkidle_timeout_ms: int,
) -> None:
    """Execute the rule's Playwright action against the resolved ``bid``.

    Uses BrowserGym's ``get_elem_by_bid`` so the locator follows the
    same nested-frame resolution rules the agent will use at evaluation
    time (see :mod:`browsergym.core.action.utils`).
    """
    if page is None:
        raise RuntimeError(
            f"execute_rule for {rule.id!r} resolved bid={bid!r} but received page=None; "
            "callers must supply a live Playwright page when the rule actually fires.",
        )
    # Lazy import: keeps ``stateful`` import-safe for tests that never
    # touch a real browser (``test_transition_stateful_*`` only needs
    # ``compute_structural_fingerprint`` / ``resolve_selector``).
    from browsergym.core.action.utils import get_elem_by_bid  # noqa: PLC0415

    elem = get_elem_by_bid(page, bid)
    if rule.action == "click":
        elem.click()
    elif rule.action == "fill":
        if derived_query is None:
            raise RuntimeError(
                f"rule {rule.id!r} reached _execute_action without a derived_query; "
                "needs_derived_query gating in execute_rule failed",
            )
        elem.fill(derived_query)
    elif rule.action == "hover":
        elem.hover()
    else:  # pragma: no cover — guarded by Rule.action's Literal at construction time
        raise RuntimeError(f"unsupported rule action: {rule.action!r}")
    # ``networkidle`` may legitimately not arrive (long-polling shop chat,
    # third-party trackers).  The diff against the pre-fingerprint is the
    # ground truth, so a missed networkidle does not turn a real diff into
    # a false negative.  Fall through.
    with contextlib.suppress(Exception):
        page.wait_for_load_state("networkidle", timeout=networkidle_timeout_ms)


def _validate_state_response(response: VisionResponse) -> tuple[StateName, tuple[str, ...]]:
    """Validate ``response.parsed`` against :class:`StateResponse`.

    Three failure modes collapse to ``state="no_change"`` plus non-empty
    ``parse_errors``:

    * the client could not parse a response at all,
    * the closed pydantic schema rejected the response,
    * the JSON root was not an object.

    Returns:
        ``(state, parse_errors)`` — ``state`` is the validated name on
        success and ``"no_change"`` on any failure.
    """
    if response.parsed is None:
        return "no_change", response.parse_errors
    try:
        validated = StateResponse.model_validate(dict(response.parsed))
    except ValidationError as exc:
        return "no_change", tuple(_combine_errors(response.parse_errors, exc))
    return validated.state, response.parse_errors


def _combine_errors(
    upstream: Sequence[str],
    exc: ValidationError,
) -> list[str]:
    """Append schema-validation errors to ``upstream`` in human-readable form."""
    out = list(upstream)
    for err in exc.errors():
        loc_parts = [str(part) for part in err["loc"]]
        loc = ".".join(loc_parts) if loc_parts else "<root>"
        out.append(f"state-namer schema validation: {loc}: {err['msg']}")
    return out


def _node_role(node: Mapping[str, Any]) -> str:
    """Return the node's role string, or ``""`` when missing/malformed."""
    role: object = node.get("role")
    if not isinstance(role, Mapping):
        return ""
    value = cast("Mapping[str, object]", role).get("value")
    return value if isinstance(value, str) else ""


def _node_name(node: Mapping[str, Any]) -> str:
    """Return the node's accessible-name string, or ``""`` when absent."""
    name: object = node.get("name")
    if not isinstance(name, Mapping):
        return ""
    value = cast("Mapping[str, object]", name).get("value")
    return value if isinstance(value, str) else ""


def _node_bid(node: Mapping[str, Any]) -> str | None:
    """Return the BrowserGym ``browsergym_id`` of ``node``, or ``None``."""
    raw: object = node.get("browsergym_id")
    return raw if isinstance(raw, str) and raw else None


def _node_child_ids(node: Mapping[str, Any]) -> list[str]:
    """Return the node's child id list (str-typed), tolerating bad data."""
    raw: object = node.get("childIds")
    if not isinstance(raw, list):
        return []
    return [c for c in cast("list[object]", raw) if isinstance(c, str)]


def _index_axtree(
    axtree: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    """Return ``(by_id, root_children)`` indices over ``axtree``.

    ``root_children`` is the in-order list of the root's child ids; we
    fall back to ``[first-node-id]`` when the root has no ``childIds``
    so :func:`_find_landmark_id` still has a starting point.
    """
    if not isinstance(axtree, Mapping):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(f"axtree must be a mapping, got {type(axtree).__name__}")
    raw_nodes: object = axtree.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raise TypeError(
            f"axtree['nodes'] must be a list, got {type(raw_nodes).__name__}",
        )
    nodes: list[Mapping[str, Any]] = [
        cast("Mapping[str, Any]", n)
        for n in cast("list[object]", raw_nodes)
        if isinstance(n, Mapping)
    ]
    by_id: dict[str, Mapping[str, Any]] = {}
    for node in nodes:
        node_id = node.get("nodeId")
        if isinstance(node_id, str):
            by_id[node_id] = node
    if not nodes:
        return by_id, []
    root_id_raw = nodes[0].get("nodeId")
    root_id = root_id_raw if isinstance(root_id_raw, str) else None
    if root_id is None:
        return by_id, []
    root_children = _node_child_ids(nodes[0])
    return by_id, root_children or [root_id]


def _find_landmark_id(
    by_id: Mapping[str, Mapping[str, Any]],
    root_children: list[str],
    landmark: str,
) -> str | None:
    """Return the id of the first axtree node whose role equals ``landmark``.

    The walk starts from the root's children (so the document root —
    which BrowserGym labels ``RootWebArea`` — is excluded) and continues
    in pre-order DFS.  Cycle-guarded to tolerate malformed trees.
    """
    visited: set[str] = set()
    stack: list[str] = list(reversed(root_children))
    while stack:
        node_id = stack.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        node = by_id.get(node_id)
        if node is None:
            continue
        if _node_role(node) == landmark:
            return node_id
        for child_id in reversed(_node_child_ids(node)):
            if child_id not in visited:
                stack.append(child_id)
    return None


# Sanity check: ``STATE_NAMES`` covers every rule-emitted state plus the
# three LLM-only entries.  Done at import time so a typo here is caught
# by ``pytest --collect-only``, not by a smoke run.
_LLM_ONLY_STATES: Final[frozenset[str]] = frozenset({"popup_modal", "other", "no_change"})
assert frozenset(STATE_NAMES) == frozenset(RULE_STATE_NAMES) | _LLM_ONLY_STATES, (
    "STATE_NAMES must be RULE_STATE_NAMES union {popup_modal, other, no_change}"
)


# ---------------------------------------------------------------------------
# Stateful pass orchestration (impl-plan M5 wiring).
# ---------------------------------------------------------------------------


#: ``trace.jsonl`` phase tag for stateful-pass attempts.  Mirrors
#: :data:`shop_arena.env_eval.transition.bfs.BFS_PHASE`; readers must dispatch
#: on ``phase`` before parsing the rest of the line because the schemas differ.
STATEFUL_PHASE: Final[str] = "stateful"


@dataclass(frozen=True, slots=True)
class StatefulAttempt:
    """One rule attempt persisted to ``trace.jsonl`` (spec §5.6).

    Mirrors :class:`shop_arena.env_eval.transition.bfs.BfsAttempt` but for the
    M5 stateful pass: every popped rule produces exactly one line, regardless
    of whether it fired, was skipped, or errored out.

    Attributes:
        rule_id: Triggering rule's :attr:`Rule.id`.
        page_class: Triggering rule's :attr:`Rule.page_class`.
        page_url: Concrete URL the rule ran on.
        outcome: One of :data:`RuleOutcome`.
        bid: BrowserGym id of the resolved target, or ``None``.
        state: Parsed state name when ``outcome == "fired"``, else ``None``.
        state_node: Canonical id of the state node added to the graph when
            ``outcome == "fired"``, else ``None``.
        artifact: Run-relative POSIX path to the per-attempt JSON artifact
            when ``outcome == "fired"``, else ``None``.
        error: Human-readable error message when ``outcome`` is
            ``"exec_error"`` or ``"load_error"``, else ``None``.
    """

    rule_id: str
    page_class: str
    page_url: str
    outcome: RuleOutcome
    bid: str | None = None
    state: StateName | None = None
    state_node: str | None = None
    artifact: str | None = None
    error: str | None = None


def state_node_id(page_canonical_id: str, state_name: str) -> str:
    """Return the canonical id used for a state node in the transition graph.

    Spec §5.5.2 + impl-plan M0 decision: state nodes collapse on
    ``(page, state_name)`` so two rules that produce the same state name on
    the same page (e.g. ``homepage_open_cart_drawer`` + a future homepage
    cart-icon button rule both yielding ``cart_drawer``) land on a single
    node.  The opaque ``state:`` prefix prevents any collision with URL nodes
    (URL nodes always start with ``/``).
    """
    return f"state:{page_canonical_id}:{state_name}"


def write_stateful_trace_lines(
    attempts: Sequence[StatefulAttempt],
    path: Path,
    *,
    mode: Literal["w", "a"] = "a",
) -> Path:
    """Append (or write) stateful trace lines to ``trace.jsonl``.

    The on-disk schema for one stateful attempt:

    ```jsonc
    {
      "phase": "stateful",
      "rule_id": "homepage_open_cart_drawer",
      "page_class": "homepage",
      "page_url": "https://shop/",
      "outcome": "fired",         // one of RuleOutcome
      "bid": "a47",                // null when no_target / skipped / load_error
      "state": "cart_drawer",      // null unless outcome == "fired"
      "state_node": "state:/:cart_drawer",  // null unless outcome == "fired"
      "artifact": "transition/node/state__home__cart_drawer/node.json",
      "error": null                // populated for exec_error / load_error
    }
    ```

    Output is byte-stable for fixed input: keys are emitted in insertion
    order with no whitespace inside each line, and every line is terminated
    with ``\n``.

    Args:
        attempts: Stateful attempts in the order they should appear on disk.
        path: Destination ``trace.jsonl`` path.  Parent directory must exist.
        mode: ``"a"`` to append after the structural-pass lines (the M5
            pipeline default) or ``"w"`` to start a new file (used by tests
            and the M6 reuse path).

    Returns:
        The resolved :class:`pathlib.Path` written to disk.
    """
    with path.open(mode, encoding="utf-8") as fh:
        for attempt in attempts:
            line: dict[str, Any] = {
                "phase": STATEFUL_PHASE,
                "rule_id": attempt.rule_id,
                "page_class": attempt.page_class,
                "page_url": attempt.page_url,
                "outcome": attempt.outcome,
                "bid": attempt.bid,
                "state": attempt.state,
                "state_node": attempt.state_node,
                "artifact": attempt.artifact,
                "error": attempt.error,
            }
            fh.write(json.dumps(line, separators=(",", ":")))
            fh.write("\n")
    return path


def run_stateful_pass(
    *,
    rules: Sequence[Rule],
    page_targets: Mapping[str, str],
    derived_query: str | None,
    graph: TransitionGraph,
    states_dir: Path,
    node_root: Path | None = None,
    llm_client: LLMVisionClient,
    goto: Callable[[str], object],
    axtree: Callable[[], Mapping[str, Any]],
    screenshot_png: Callable[[], bytes],
    page: playwright.sync_api.Page | None,
    networkidle_timeout_ms: int = DEFAULT_NETWORKIDLE_TIMEOUT_MS,
    temperature: float = DEFAULT_RUBRIC_TEMPERATURE,
    canonical_id_for_url: Callable[[str], str],
    run_dir: Path,
    rule_filter: Callable[[Rule], bool] | None = None,
) -> tuple[list[StatefulAttempt], int]:
    """Iterate ``rules`` and apply each one against its page-class target.

    Mutates ``graph`` in place: every fired rule adds a state node (collapsed
    on ``(page, state_name)``) and a directed edge from the page's URL node
    to that state node.  Rules whose page class has no measurable URL target
    (the bucket was ``not_found``) are silently skipped — they are surfaced
    in :class:`StatefulAttempt` records with ``outcome="no_target"`` would be
    misleading because the executor never ran.

    Args:
        rules: Closed rule list (typically
            :data:`shop_arena.env_eval.transition.rules.RULES`).
        page_targets: ``{page_class: page_url}`` map covering every page-class
            that has a measurable URL.  Missing keys are silently skipped.
        derived_query: Search query inferred by page selection (spec §5.2).
            Forwarded to :func:`execute_rule`; rules that need a query are
            skipped when this is ``None``.
        graph: Combined transition graph to extend in place.  Edge sources
            must already exist as URL nodes (BFS guarantees this for every
            measurable seed).
        states_dir: Destination directory for per-attempt artifacts; created
            on first fired rule.
        node_root: Optional ``transition/node`` directory. When supplied, fired
            state rules also write a graph-node folder containing pre/post
            screenshots, pre/post axtrees, and state-namer metadata.
        llm_client: Vision client used by the state-namer.  Required because
            a fired rule must produce a named state.
        goto / axtree / screenshot_png / page: Forwarded to
            :func:`execute_rule`.
        networkidle_timeout_ms: Forwarded to :func:`execute_rule`.
        temperature: Forwarded to :func:`execute_rule`.
        canonical_id_for_url: Function mapping a concrete URL to its
            canonical graph id.  Injected so this module does not import
            from :mod:`shop_arena.env_eval.transition.canonicalize` at the
            top level (keeps the import graph acyclic).
        run_dir: Run directory used to render run-relative artifact paths
            for trace lines.
        rule_filter: Optional predicate invoked per rule; ``False`` skips
            the rule entirely (no goto, no trace line).  Defaults to
            "keep all rules".

    Returns:
        ``(attempts, llm_calls)`` — ``attempts`` is one entry per executed
        rule (in input order) suitable for :func:`write_stateful_trace_lines`;
        ``llm_calls`` is the number of state-namer vision calls actually
        issued (zero when no rule fires).
    """
    attempts: list[StatefulAttempt] = []
    llm_calls = 0
    for rule in rules:
        if rule_filter is not None and not rule_filter(rule):
            continue
        page_url = page_targets.get(rule.page_class)
        if page_url is None:
            # Page class has no measurable URL (bucket was ``not_found``);
            # skip silently — the rule never had a chance to run.
            continue
        if rule.action == "fill" and rule.needs_derived_query and not derived_query:
            # Spec §5.5.2: skip silently when no query is available; record
            # a trace line for auditability but do nothing else.
            attempts.append(
                StatefulAttempt(
                    rule_id=rule.id,
                    page_class=rule.page_class,
                    page_url=page_url,
                    outcome="skipped_no_query",
                ),
            )
            continue

        # On the first rule that may actually fire we materialise the temporary
        # per-attempt workspace. Cheap to call repeatedly.
        states_dir.mkdir(parents=True, exist_ok=True)

        result = execute_rule(
            rule,
            page_url=page_url,
            derived_query=derived_query if rule.needs_derived_query else None,
            states_dir=states_dir,
            state_id=rule.id,
            llm_client=llm_client,
            goto=goto,
            axtree=axtree,
            screenshot_png=screenshot_png,
            page=page,
            networkidle_timeout_ms=networkidle_timeout_ms,
            temperature=temperature,
        )
        if result.outcome == "fired":
            llm_calls += 1

        state_node = None
        artifact_rel = None
        if result.outcome == "fired" and result.state is not None:
            page_canonical = canonical_id_for_url(page_url)
            node_id = state_node_id(page_canonical, result.state)
            graph.add_state_node(
                canonical_id=node_id,
                representative_url=page_url,
                state_name=result.state,
            )
            # Source must exist; BFS seeds every measurable bucket.  Defensive
            # check keeps a missing seed from corrupting graph.json.
            if page_canonical in graph.nodes:
                graph.add_edge(
                    source=page_canonical,
                    target=node_id,
                    label=f"{rule.action}({rule.id})",
                    action=rule.action,
                )
            state_node = node_id
            node_artifact_path = (
                node_artifacts_mod.node_json_path(node_root, node_id)
                if node_root is not None
                else None
            )
            if (
                node_artifact_path is not None
                and result.artifact_path is not None
                and result.pre_screenshot_path is not None
                and result.post_screenshot_path is not None
                and result.pre_axtree_path is not None
                and result.pre_axtree_text_path is not None
                and result.post_axtree_path is not None
                and result.post_axtree_text_path is not None
                and not node_artifact_path.is_file()
            ):
                assert node_root is not None
                node_artifacts_mod.write_state_node_artifact(
                    node_root=node_root,
                    canonical_id=node_id,
                    representative_url=page_url,
                    state_name=result.state,
                    state_artifact_path=result.artifact_path,
                    pre_screenshot_path=result.pre_screenshot_path,
                    post_screenshot_path=result.post_screenshot_path,
                    pre_axtree_json_path=result.pre_axtree_path,
                    pre_axtree_text_path=result.pre_axtree_text_path,
                    post_axtree_json_path=result.post_axtree_path,
                    post_axtree_text_path=result.post_axtree_text_path,
                )
            if node_artifact_path is not None and node_artifact_path.is_file():
                artifact_rel = node_artifact_path.relative_to(run_dir).as_posix()
            elif result.artifact_path is not None and result.artifact_path.is_relative_to(run_dir):
                artifact_rel = result.artifact_path.relative_to(run_dir).as_posix()

        attempts.append(
            StatefulAttempt(
                rule_id=rule.id,
                page_class=rule.page_class,
                page_url=page_url,
                outcome=result.outcome,
                bid=result.bid,
                state=result.state,
                state_node=state_node,
                artifact=artifact_rel,
                error=result.error,
            ),
        )
    return attempts, llm_calls


if TYPE_CHECKING:
    from shop_arena.env_eval.transition.graph import TransitionGraph
