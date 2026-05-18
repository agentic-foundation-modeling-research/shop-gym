"""Closed-schema ``Metrics`` pydantic v2 model (``metrics.json`` v0.2).

This module owns the **published** ``metrics.json`` document defined in
spec §5.8. Every model below is frozen and closed
(``model_config = ConfigDict(frozen=True, extra="forbid")``), so any drift
— a typo, a stray key, an unknown rubric category — fails loudly at parse
time. Schema changes must update this model and the matching spec example so
producers and consumers agree on the exact published shape (spec §5.8).

Layout mirrors the spec example exactly:

* :class:`Metrics` — top-level document (``version``, ``shop``, ``pages``,
  ``observation``, ``action``, ``transition``, ``artifacts``).
* :class:`Shop` — input URL + derived domain + package version.
* :class:`Pages` + the discriminated ``PageEntry`` / ``SearchPageEntry``
  unions — five-bucket discovery output.  Unavailable samples use an
  explicit ``{"status": "not_found", "reason": ...}`` object instead of
  zeroed data, per the impl-plan M1 task list.
* :class:`Observation`, :class:`AxtreeStats`, :class:`Rubric` — aggregate
  perception metrics over all transition graph nodes. Per-node screenshots,
  axtrees, and rubric artifacts stay in ``observation/`` rather than being
  duplicated in ``metrics.json``.
* :class:`Action` — aggregate raw action affordance counts over all transition
  graph nodes plus semantic counts derived from transition graph edges. The
  richer per-element artifacts stay in ``action/``; see spec §5.4.
* :class:`Transition` — graph metrics from the BFS + stateful pass.
* :class:`Artifacts` — relative paths to companion files in the run dir.

The closed rubric enum (§5.3) and the action vocabulary enum (§5.4 / 5.8
example) are encoded as explicit fields with defaults of ``0`` rather
than open ``dict[str, int]`` mappings.  That choice is what makes
``extra="forbid"`` enforce the closed enum at the data layer rather than
relying on a Literal key validator.

Errors raised by :func:`load_metrics` are wrapped in
:class:`shop_arena.env_eval.errors.MetricsValidationError` so the public
surface stays decoupled from pydantic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shop_arena.env_eval import _version
from shop_arena.env_eval.errors import MetricsValidationError

__all__ = [
    "METRICS_SCHEMA_VERSION",
    "RUBRIC_CATEGORIES",
    "ActionCounts",
    "ActionNodeEntry",
    "ActionNodeOk",
    "ActionSemanticCounts",
    "Artifacts",
    "AxtreeStats",
    "CartAndSearch",
    "MeasuredNode",
    "Metrics",
    "NodeKind",
    "NodeNotFound",
    "NotFound",
    "Observation",
    "ObservationNodeEntry",
    "ObservationNodeOk",
    "PageEntry",
    "PageOk",
    "Pages",
    "Rubric",
    "SearchPageEntry",
    "SearchPageOk",
    "Shop",
    "Transition",
    "dump_metrics",
    "load_metrics",
]

#: Version of the ``metrics.json`` schema itself (spec §5.8 / impl-plan M0).
#: Bumped only when the document shape changes.  Distinct from
#: :data:`shop_arena.env_eval._version.__version__`, which is the package
#: version recorded inside ``Shop.eval_version``.
METRICS_SCHEMA_VERSION: Literal["0.3"] = "0.3"

#: Closed enum of rubric categories (spec §5.3).  Kept as a tuple so
#: callers can introspect the enum (e.g. tests, prompt rendering) without
#: parsing the model schema.
RUBRIC_CATEGORIES: tuple[str, ...] = (
    "nav",
    "mega_menu",
    "announcement_bar",
    "hero",
    "product_card",
    "product_image",
    "product_variant",
    "cta_button",
    "secondary_button",
    "form_input",
    "filter_chip",
    "breadcrumb",
    "text_block",
    "footer",
    "popup_modal",
    "cart_drawer",
    "search_bar",
    "chat_widget",
    "other",
)


class _Closed(BaseModel):
    """Base class enforcing frozen + ``extra="forbid"`` on every model."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Status objects for unavailable samples (spec §5.8).
# ---------------------------------------------------------------------------


class NotFound(_Closed):
    """Closed status object for an unavailable sample bucket.

    Attributes:
        status: Discriminator literal — always ``"not_found"``.
        reason: Short machine-readable reason
            (e.g. ``"no_product_link"``, ``"http_404"``,
            ``"no_search_query"``).
    """

    status: Literal["not_found"] = "not_found"
    reason: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Pages block (spec §5.2 + §5.8).
# ---------------------------------------------------------------------------

#: Closed enum of selection rules recorded per page bucket.  The richer
#: fallback chain is captured in ``pages.json`` (impl-plan M1); only the
#: terminal rule appears in ``metrics.json``.
SelectedBy = Literal[
    "input",
    "first_href",
    "fallback_path",
    "convention",
    "product_title",
    "product_slug",
    "collection_title",
    "collection_slug",
    "nav_label",
]


class PageOk(_Closed):
    """An ``ok`` URL-only page entry under :class:`Pages`.

    Attributes:
        status: Discriminator literal — always ``"ok"``.
        url: Concrete URL EnvEval visited.  Relative to the shop root
            (e.g. ``"/collections/men"``) or absolute when the storefront
            link points off the canonical host.
        canonical_url: Templated id used as the transition graph node
            (e.g. ``"/collections/<*>"``).  ``None`` for buckets whose
            canonical id equals their URL (homepage, ``/cart``).
        selected_by: Rule that picked this URL during discovery (§5.2).
    """

    status: Literal["ok"] = "ok"
    url: str = Field(min_length=1)
    canonical_url: str | None = None
    selected_by: SelectedBy


class SearchPageOk(_Closed):
    """An ``ok`` search-subpage entry under :class:`CartAndSearch`.

    Attributes:
        status: Discriminator literal — always ``"ok"``.
        url: ``/search?q=<query>`` URL with the query value preserved
            (search is the one bucket that keeps its query string per §5.2).
        query: The deterministic, page-derived search query
            (lowercase one-to-three tokens; spec §5.2).
        selected_by: Source rule that produced ``query``.
    """

    status: Literal["ok"] = "ok"
    url: str = Field(min_length=1)
    query: str = Field(min_length=1)
    selected_by: SelectedBy


PageEntry = Annotated[PageOk | NotFound, Field(discriminator="status")]
SearchPageEntry = Annotated[SearchPageOk | NotFound, Field(discriminator="status")]


class CartAndSearch(_Closed):
    """The merged ``cart_and_search`` bucket (spec §5.2).

    Attributes:
        cart: ``/cart`` page entry.
        search: Inferred ``/search?q=...`` page entry; ``not_found`` when
            no deterministic query could be derived.
    """

    cart: PageEntry
    search: SearchPageEntry


class Pages(_Closed):
    """Five-bucket page-discovery summary (spec §5.2 + §5.8).

    Attributes:
        homepage: Required ``ok`` entry (the run aborts before reaching
            this point if the homepage is unreachable).
        collection: ``ok`` or ``not_found`` (see §5.2 fallback chain).
        product: ``ok`` or ``not_found``.
        policy: ``ok`` or ``not_found``.
        cart_and_search: Pair of ``/cart`` and ``/search`` entries.
    """

    homepage: PageEntry
    collection: PageEntry
    product: PageEntry
    policy: PageEntry
    cart_and_search: CartAndSearch


# ---------------------------------------------------------------------------
# Shop block (spec §5.8).
# ---------------------------------------------------------------------------


class Shop(_Closed):
    """Identifying metadata for the shop under measurement.

    Attributes:
        url: Normalised input storefront URL
            (scheme + host + trailing slash; spec §5.2).
        domain: Hostname extracted from ``url``; used as
            ``<shop_name>`` when no override is supplied
            (impl-plan M0).
        eval_version: Package version of ``shop_arena.env_eval`` that
            produced the run (mirrors ``__version__`` in §5.8).
    """

    url: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    eval_version: str = Field(default=_version.__version__, min_length=1)


# ---------------------------------------------------------------------------
# Observation layer (spec §5.3 + §5.8).
# ---------------------------------------------------------------------------


class AxtreeStats(_Closed):
    """Deterministic, role-counted statistics from one BrowserGym axtree.

    Attributes:
        node_count: Total nodes in the simplified accessibility tree.
        interactive_count: Nodes whose role is interactive (button, link,
            textbox, combobox, checkbox, radio, menuitem, …).
        link_count: ``link`` role nodes.
        button_count: ``button`` role nodes.
        textbox_count: ``textbox`` (and ``searchbox``) role nodes.
        image_count: ``image`` role nodes.
        heading_count: ``heading`` role nodes.
        landmark_count: Landmark role nodes (``main``, ``navigation``, …).
        max_depth: Deepest path in the raw tree.
        semantic_max_depth: Deepest path after collapsing presentational/text
            wrapper roles.
        content_character_count: Character count of visible text content.
    """

    node_count: int = Field(ge=0)
    interactive_count: int = Field(ge=0)
    link_count: int = Field(ge=0)
    button_count: int = Field(ge=0)
    textbox_count: int = Field(ge=0)
    image_count: int = Field(ge=0)
    heading_count: int = Field(ge=0)
    landmark_count: int = Field(ge=0)
    max_depth: int = Field(ge=0)
    semantic_max_depth: int = Field(ge=0)
    content_character_count: int = Field(ge=0)


class Rubric(_Closed):
    """LLM screenshot-rubric counts over the closed §5.3 category enum.

    Each field defaults to ``0`` so a zero-rubric document still serializes
    every category explicitly; ``extra="forbid"`` rejects any unknown
    category supplied by the model (which would surface as ``other``).
    """

    nav: int = Field(default=0, ge=0)
    mega_menu: int = Field(default=0, ge=0)
    announcement_bar: int = Field(default=0, ge=0)
    hero: int = Field(default=0, ge=0)
    product_card: int = Field(default=0, ge=0)
    product_image: int = Field(default=0, ge=0)
    product_variant: int = Field(default=0, ge=0)
    cta_button: int = Field(default=0, ge=0)
    secondary_button: int = Field(default=0, ge=0)
    form_input: int = Field(default=0, ge=0)
    filter_chip: int = Field(default=0, ge=0)
    breadcrumb: int = Field(default=0, ge=0)
    text_block: int = Field(default=0, ge=0)
    footer: int = Field(default=0, ge=0)
    popup_modal: int = Field(default=0, ge=0)
    cart_drawer: int = Field(default=0, ge=0)
    search_bar: int = Field(default=0, ge=0)
    chat_widget: int = Field(default=0, ge=0)
    other: int = Field(default=0, ge=0)


NodeKind = Literal["url", "state"]
"""Closed transition-node discriminator mirrored from ``transition/graph.json``."""


class MeasuredNode(_Closed):
    """Transition graph node identity attached to node-level measurements.

    Attributes:
        canonical_id: Canonical transition-graph node id (e.g. ``"/"``,
            ``"/products/<*>"``, or ``"state:/:cart_drawer"``).
        folder: Folder name under ``transition/node/`` and filename stem used
            by node-level observation/action artifacts.
        kind: ``"url"`` for structural graph nodes, ``"state"`` for
            stateful post-action nodes.
        representative_url: Concrete URL associated with the graph node.
        state_name: Closed state name for state nodes; ``None`` for URL nodes.
    """

    canonical_id: str = Field(min_length=1)
    folder: str = Field(min_length=1)
    kind: NodeKind
    representative_url: str = Field(min_length=1)
    state_name: str | None = None


class NodeNotFound(_Closed):
    """Closed status object for a graph node whose browser state is unavailable."""

    status: Literal["not_found"] = "not_found"
    node: MeasuredNode
    reason: str = Field(min_length=1)


class ObservationNodeOk(_Closed):
    """Observation metrics for one transition graph node."""

    status: Literal["ok"] = "ok"
    node: MeasuredNode
    axtree: AxtreeStats
    rubric: Rubric


ObservationNodeEntry = Annotated[
    ObservationNodeOk | NodeNotFound,
    Field(discriminator="status"),
]


class Observation(_Closed):
    """Aggregate observation metrics over all captured transition nodes.

    Detailed per-node screenshots, axtrees, and rubric artifacts live under
    ``observation/``. ``metrics.json`` keeps only the website-level summary to
    avoid duplicating every node measurement.
    """

    node_count: int = Field(ge=0)
    interactive_count: int = Field(ge=0)
    distinct_node_count: int = Field(ge=0)
    max_depth: int = Field(ge=0)
    semantic_max_depth: int = Field(ge=0)
    content_character_count: int = Field(ge=0)
    rubric: Rubric = Field(default_factory=Rubric)


# ---------------------------------------------------------------------------
# Action layer (spec §5.4 + §5.8).
# ---------------------------------------------------------------------------


class ActionCounts(_Closed):
    """Raw action vocabulary counts plus target-category counts.

    The richer per-element artifact lives next to the run as
    ``action/<node_folder>.action_space.json`` (spec §5.4).

    Attributes:
        click: Number of click-target elements.
        fill: Number of text-input fill targets.
        hover: Number of hoverable elements.
        select_option: Number of combobox/listbox options.
        scroll: ``1`` when the page is scrollable, ``0`` otherwise.
        choice_target_count: Number of visible discrete choice targets
            (radio/checkbox/options/select controls and sort/filter/variant
            controls). This is not a BrowserGym action verb.
    """

    click: int = Field(default=0, ge=0)
    fill: int = Field(default=0, ge=0)
    hover: int = Field(default=0, ge=0)
    select_option: int = Field(default=0, ge=0)
    scroll: int = Field(default=0, ge=0)
    choice_target_count: int = Field(default=0, ge=0)


class ActionNodeOk(_Closed):
    """Action-space counts for one transition graph node."""

    status: Literal["ok"] = "ok"
    node: MeasuredNode
    click: int = Field(default=0, ge=0)
    fill: int = Field(default=0, ge=0)
    hover: int = Field(default=0, ge=0)
    select_option: int = Field(default=0, ge=0)
    scroll: int = Field(default=0, ge=0)
    choice_target_count: int = Field(default=0, ge=0)


ActionNodeEntry = Annotated[
    ActionNodeOk | NodeNotFound,
    Field(discriminator="status"),
]


class ActionSemanticCounts(_Closed):
    """Mutually exclusive transition-edge semantic action counts.

    Boundary rules are edge-target based: ``search`` covers search URL targets
    plus search overlay / predictive-panel states; ``filter`` covers filter-
    and sort-menu states; ``goto_*`` covers transition edges to URL page
    classes; ``open_cart`` covers cart-drawer state transitions; ``explore``
    covers remaining internal navigation/state edges not classified above.
    """

    search: int = Field(default=0, ge=0)
    filter: int = Field(default=0, ge=0)
    goto_home: int = Field(default=0, ge=0)
    goto_collection: int = Field(default=0, ge=0)
    goto_product: int = Field(default=0, ge=0)
    goto_policy: int = Field(default=0, ge=0)
    goto_cart: int = Field(default=0, ge=0)
    open_cart: int = Field(default=0, ge=0)
    explore: int = Field(default=0, ge=0)


class Action(_Closed):
    """Aggregate raw node action counts plus edge-derived semantic counts."""

    click: int = Field(default=0, ge=0)
    fill: int = Field(default=0, ge=0)
    hover: int = Field(default=0, ge=0)
    select_option: int = Field(default=0, ge=0)
    scroll: int = Field(default=0, ge=0)
    choice_target_count: int = Field(default=0, ge=0)
    semantic: ActionSemanticCounts = Field(default_factory=ActionSemanticCounts)


# ---------------------------------------------------------------------------
# Transition layer (spec §5.5 + §5.8).
# ---------------------------------------------------------------------------


class Transition(_Closed):
    """Aggregate metrics over the combined transition graph.

    Computed deterministically from ``transition/graph.json`` (spec
    §5.5.3).  ``diameter`` is ``None`` when the graph has fewer than two
    reachable nodes; ``homepage_to_cart_min_clicks`` is ``None`` when no
    cart/cart_drawer node is reachable from the homepage.

    Attributes:
        node_count: ``|V|`` over URL nodes + state nodes.
        edge_count: ``|E|`` directed edges.
        state_node_count: Count of named state nodes
            (``cart_drawer``, ``search_overlay``, …).
        avg_out_degree: Mean out-degree across nodes (0.0 when ``|V|=0``).
        max_out_degree: Maximum out-degree across nodes.
        dead_end_count: Nodes with ``out_degree == 0``.
        diameter: Longest shortest-path within any reachable component;
            ``None`` if undefined.
        reachable_pct_from_homepage: ``|reachable(homepage)| / |V|``
            in ``[0.0, 1.0]``.
        homepage_to_cart_min_clicks: Shortest path length from the
            homepage to ``/cart`` or the ``cart_drawer`` state node;
            ``None`` if neither is reachable.
    """

    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    state_node_count: int = Field(ge=0)
    avg_out_degree: float = Field(ge=0.0)
    max_out_degree: int = Field(ge=0)
    dead_end_count: int = Field(ge=0)
    diameter: int | None = Field(default=None, ge=0)
    reachable_pct_from_homepage: float = Field(ge=0.0, le=1.0)
    homepage_to_cart_min_clicks: int | None = Field(default=None, ge=0)


# ---------------------------------------------------------------------------
# Artifacts block (spec §5.6 + §5.8).
# ---------------------------------------------------------------------------


class Artifacts(_Closed):
    """Run-relative paths to companion files (spec §5.8 example).

    These pointers let downstream tooling (``compare``, ``aggregate``,
    debugging notebooks) locate the per-layer artifacts without
    hard-coding the layout.
    """

    observation_dir: str = Field(default="observation/", min_length=1)
    action_dir: str = Field(default="action/", min_length=1)
    transition_graph: str = Field(default="transition/graph.json", min_length=1)


# ---------------------------------------------------------------------------
# Top-level document.
# ---------------------------------------------------------------------------


class Metrics(_Closed):
    """The published ``metrics.json`` document for one EnvEval run.

    See spec §5.8 for the canonical example.  All nested models are
    closed and frozen, so ``Metrics.model_validate(payload)`` rejects any
    document with extra keys or with the wrong status discriminator.

    Attributes:
        version: Schema version of the document
            (``METRICS_SCHEMA_VERSION``).  Bumped on shape changes.
        shop: Shop identity + package version.
        pages: Five-bucket page discovery output.
        observation: Website-level perception aggregate.
        action: Website-level raw and semantic action aggregates.
        transition: Aggregate transition-graph metrics.
        artifacts: Run-relative paths to companion files.
    """

    version: Literal["0.3"] = METRICS_SCHEMA_VERSION
    shop: Shop
    pages: Pages
    observation: Observation
    action: Action
    transition: Transition
    artifacts: Artifacts = Field(default_factory=Artifacts)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def load_metrics(path: Path | str) -> Metrics:
    """Load + validate a ``metrics.json`` document.

    Args:
        path: Filesystem path to ``metrics.json``.

    Returns:
        Parsed :class:`Metrics`.

    Raises:
        MetricsValidationError: If the file is missing, not valid JSON,
            or fails the closed pydantic schema (extra keys, wrong types,
            wrong discriminator).
    """
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise MetricsValidationError(f"cannot read {p}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MetricsValidationError(f"{p} is not valid JSON: {exc}") from exc
    try:
        return Metrics.model_validate(payload)
    except ValidationError as exc:
        raise MetricsValidationError(f"{p} failed schema validation: {exc}") from exc


def dump_metrics(metrics: Metrics, path: Path | str) -> Path:
    """Serialize a :class:`Metrics` document to disk.

    Writes deterministic JSON (sorted by model field order, two-space
    indent, trailing newline) so byte-stable output is preserved
    across reruns and across operating systems (spec §5 SC5 trail).

    Args:
        metrics: Validated :class:`Metrics` to serialize.
        path: Destination path (parent directories must exist).

    Returns:
        The resolved :class:`pathlib.Path` written to disk.
    """
    p = Path(path)
    payload = metrics.model_dump(mode="json")
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p
