"""Closed ``Metrics`` schema (spec §5.8) — fixture round-trip and rejection tests.

Lands with the first metrics-schema task in M1.  Covers:

* every nested model is closed (``extra="forbid"``) and frozen,
* a representative full document round-trips byte-stably through
  :func:`shop_arena.env_eval.schema.metrics.dump_metrics` /
  :func:`shop_arena.env_eval.schema.metrics.load_metrics`,
* unknown top-level and nested keys are rejected,
* unavailable samples use explicit closed status objects rather than
  zeroed metrics,
* ``MetricsValidationError`` wraps schema failures (the public failure
  vocabulary stays decoupled from pydantic).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from shop_arena.env_eval.errors import MetricsValidationError
from shop_arena.env_eval.schema import metrics as metrics_mod
from shop_arena.env_eval.schema.metrics import (
    METRICS_SCHEMA_VERSION,
    RUBRIC_CATEGORIES,
    Action,
    ActionSemanticCounts,
    Artifacts,
    CartAndSearch,
    Metrics,
    NotFound,
    Observation,
    PageOk,
    Pages,
    Rubric,
    SearchPageOk,
    Shop,
    Transition,
    dump_metrics,
    load_metrics,
)


def _fixture_metrics() -> Metrics:
    """Build the spec §5.8 example as a typed ``Metrics`` value."""
    return Metrics(
        shop=Shop(
            url="https://example-shop.com/",
            domain="example-shop.com",
        ),
        pages=Pages(
            homepage=PageOk(url="/", selected_by="input"),
            collection=PageOk(
                url="/collections/men",
                canonical_url="/collections/<*>",
                selected_by="first_href",
            ),
            product=PageOk(
                url="/products/linen-shirt",
                canonical_url="/products/<*>",
                selected_by="first_href",
            ),
            policy=PageOk(
                url="/policies/privacy-policy",
                canonical_url="/policies/<*>",
                selected_by="convention",
            ),
            cart_and_search=CartAndSearch(
                cart=PageOk(url="/cart", selected_by="convention"),
                search=SearchPageOk(
                    url="/search?q=linen%20shirt",
                    query="linen shirt",
                    selected_by="product_title",
                ),
            ),
        ),
        observation=Observation(
            node_count=2432,
            interactive_count=380,
            distinct_node_count=861,
            max_depth=15,
            semantic_max_depth=9,
            content_character_count=8124,
            rubric=Rubric(nav=5, hero=2, product_card=24, cta_button=9, footer=5),
        ),
        action=Action(
            click=156,
            fill=5,
            hover=20,
            select_option=2,
            scroll=5,
            choice_target_count=7,
            semantic=ActionSemanticCounts(
                search=4,
                filter=6,
                goto_collection=3,
                goto_product=8,
                goto_policy=1,
                goto_cart=2,
                open_cart=1,
                explore=10,
            ),
        ),
        transition=Transition(
            node_count=14,
            edge_count=22,
            state_node_count=4,
            avg_out_degree=1.57,
            max_out_degree=6,
            dead_end_count=2,
            diameter=4,
            reachable_pct_from_homepage=0.93,
            homepage_to_cart_min_clicks=2,
        ),
        artifacts=Artifacts(),
    )


# ---------------------------------------------------------------------------
# Module / version sanity.
# ---------------------------------------------------------------------------


def test_metrics_module_is_importable() -> None:
    """M0 layout marker preserved: ``metrics`` module imports."""
    assert metrics_mod.__name__ == "shop_arena.env_eval.schema.metrics"


def test_metrics_schema_version_is_v0_3() -> None:
    """Schema version is the v0.3 published constant."""
    assert METRICS_SCHEMA_VERSION == "0.3"
    assert Metrics.model_fields["version"].default == "0.3"


def test_rubric_enum_matches_spec() -> None:
    """Rubric category enum is the closed §5.3 list — order preserved."""
    assert RUBRIC_CATEGORIES == (
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
    # Every enum value is a Rubric field with default 0.
    for cat in RUBRIC_CATEGORIES:
        assert cat in Rubric.model_fields
        assert Rubric.model_fields[cat].default == 0


# ---------------------------------------------------------------------------
# Round-trip + closed-schema enforcement.
# ---------------------------------------------------------------------------


def test_full_fixture_round_trips_through_validate() -> None:
    """A full Metrics instance survives ``model_dump`` → ``model_validate``."""
    src = _fixture_metrics()
    payload = src.model_dump(mode="json")
    rt = Metrics.model_validate(payload)
    assert rt == src


def test_dump_and_load_round_trip(tmp_path: Path) -> None:
    """``dump_metrics`` + ``load_metrics`` round-trip without loss."""
    src = _fixture_metrics()
    p = dump_metrics(src, tmp_path / "metrics.json")
    assert p.exists()
    assert p.read_text(encoding="utf-8").endswith("\n")
    rt = load_metrics(p)
    assert rt == src


def test_dump_metrics_is_byte_stable(tmp_path: Path) -> None:
    """Two dumps of the same Metrics produce byte-identical files (SC5 trail)."""
    src = _fixture_metrics()
    a = dump_metrics(src, tmp_path / "a.json").read_bytes()
    b = dump_metrics(src, tmp_path / "b.json").read_bytes()
    assert a == b


def test_top_level_unknown_key_is_rejected() -> None:
    """Unknown top-level keys fail loudly (closed schema / SC2)."""
    payload = _fixture_metrics().model_dump(mode="json")
    payload["mystery"] = 1
    with pytest.raises(ValidationError):
        Metrics.model_validate(payload)


def test_nested_unknown_key_is_rejected_in_observation() -> None:
    """A stray observation statistic is rejected (closed aggregate schema)."""
    payload = _fixture_metrics().model_dump(mode="json")
    payload["observation"]["table_count"] = 3
    with pytest.raises(ValidationError):
        Metrics.model_validate(payload)


def test_nested_unknown_key_is_rejected_in_rubric() -> None:
    """A non-enum rubric category is rejected (must surface as ``other``)."""
    payload = _fixture_metrics().model_dump(mode="json")
    payload["observation"]["rubric"]["sticker"] = 1
    with pytest.raises(ValidationError):
        Metrics.model_validate(payload)


def test_unknown_action_key_is_rejected() -> None:
    """The raw action vocabulary in metrics.json is closed."""
    payload = _fixture_metrics().model_dump(mode="json")
    payload["action"]["dblclick"] = 0
    with pytest.raises(ValidationError):
        Metrics.model_validate(payload)


# ---------------------------------------------------------------------------
# Unavailable status objects (impl-plan M1).
# ---------------------------------------------------------------------------


def test_not_found_page_entry_round_trips() -> None:
    """A ``not_found`` page bucket round-trips and rejects extra keys."""
    nf = NotFound(reason="no_product_link")
    assert nf.model_dump() == {"status": "not_found", "reason": "no_product_link"}
    with pytest.raises(ValidationError):
        NotFound.model_validate({"status": "not_found", "reason": "x", "extra": 1})


def test_not_found_must_use_closed_status_object() -> None:
    """Pages discriminator rejects zeroed-shaped data without ``status``."""
    payload = _fixture_metrics().model_dump(mode="json")
    payload["pages"]["product"] = {"url": "", "selected_by": "first_href"}
    with pytest.raises(ValidationError):
        Metrics.model_validate(payload)


def test_observation_rejects_legacy_page_bucket() -> None:
    """The aggregate observation block no longer accepts page buckets."""
    payload = _fixture_metrics().model_dump(mode="json")
    payload["observation"]["product"] = {
        "status": "not_found",
        "reason": "no_product_link",
    }
    with pytest.raises(ValidationError):
        Metrics.model_validate(payload)


def test_action_rejects_legacy_page_bucket() -> None:
    """The aggregate action block no longer accepts page buckets."""
    payload = _fixture_metrics().model_dump(mode="json")
    payload["action"]["policy"] = {"status": "not_found", "reason": "http_404"}
    with pytest.raises(ValidationError):
        Metrics.model_validate(payload)


def test_search_query_required_when_ok() -> None:
    """An ``ok`` search subpage must carry a non-empty query."""
    payload = _fixture_metrics().model_dump(mode="json")
    payload["pages"]["cart_and_search"]["search"] = {
        "status": "ok",
        "url": "/search?q=",
        "query": "",
        "selected_by": "product_title",
    }
    with pytest.raises(ValidationError):
        Metrics.model_validate(payload)


def test_search_not_found_is_accepted() -> None:
    """The search subpage may be ``not_found`` when no query was inferable."""
    payload = _fixture_metrics().model_dump(mode="json")
    payload["pages"]["cart_and_search"]["search"] = {
        "status": "not_found",
        "reason": "no_search_query",
    }
    rt = Metrics.model_validate(payload)
    assert isinstance(rt.pages.cart_and_search.search, NotFound)


# ---------------------------------------------------------------------------
# Frozen-model invariant.
# ---------------------------------------------------------------------------


def test_models_are_frozen() -> None:
    """Top-level and nested models forbid mutation post-construction."""
    m = _fixture_metrics()
    with pytest.raises(ValidationError):
        m.shop.url = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        m.transition.node_count = 0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Helper-level validation.
# ---------------------------------------------------------------------------


def test_load_metrics_wraps_parse_errors(tmp_path: Path) -> None:
    """Invalid JSON triggers ``MetricsValidationError`` (not bare ValueError)."""
    p = tmp_path / "metrics.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(MetricsValidationError):
        load_metrics(p)


def test_load_metrics_wraps_schema_errors(tmp_path: Path) -> None:
    """A schema-invalid file raises ``MetricsValidationError``."""
    p = tmp_path / "metrics.json"
    payload = _fixture_metrics().model_dump(mode="json")
    payload["mystery"] = 1
    p.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MetricsValidationError):
        load_metrics(p)


def test_load_metrics_wraps_missing_file(tmp_path: Path) -> None:
    """Missing file raises ``MetricsValidationError``."""
    with pytest.raises(MetricsValidationError):
        load_metrics(tmp_path / "missing.json")


def test_transition_optional_fields_default_to_none() -> None:
    """``diameter`` and ``homepage_to_cart_min_clicks`` are optional."""
    t = Transition(
        node_count=0,
        edge_count=0,
        state_node_count=0,
        avg_out_degree=0.0,
        max_out_degree=0,
        dead_end_count=0,
        reachable_pct_from_homepage=0.0,
    )
    assert t.diameter is None
    assert t.homepage_to_cart_min_clicks is None


def test_transition_reachable_pct_bounded() -> None:
    """``reachable_pct_from_homepage`` is bounded to ``[0, 1]``."""
    with pytest.raises(ValidationError):
        Transition(
            node_count=1,
            edge_count=0,
            state_node_count=0,
            avg_out_degree=0.0,
            max_out_degree=0,
            dead_end_count=1,
            reachable_pct_from_homepage=1.5,
        )
