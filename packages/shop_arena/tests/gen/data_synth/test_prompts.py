"""Lint-only tests for the Phase 2 data-synthesis prompt templates.

T3.12 from ``docs/impl/shop_gen_implementation.md`` requires every
data-synth prompt to embed the fake-brand allowlist + safe-noun rules
from ``packages/shop_arena/src/shop_arena/gen/brands/fake_brands.json`` (spec
§5.6). The check is "lint-only; allowlist-membership grep over each
prompt": for each prompt template, at least one current allowlist
brand token and at least one safe-noun must appear in the rendered
body, and no stale brand-shaped capitalized token may be claimed as
allowlisted.

These tests are pure I/O over the in-repo prompt files; they never
spawn an LLM client and never load runtime config.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

import pytest

from shop_arena.gen.brands.allowlist import load_allowlist
from shop_arena.gen.data_synth.prompts import (
    load_synth_alt_text_template,
    load_synth_collections_template,
    load_synth_identity_template,
    load_synth_navigation_template,
    load_synth_pages_template,
    load_synth_policies_template,
    load_synth_product_details_template,
    load_synth_product_skeletons_template,
    load_synth_store_template,
)

# Every loader registered for Phase 2. Keep this list in lockstep with
# ``shop_arena.gen.data_synth.prompts.__all__`` — the M3 acceptance criterion
# (T3.12) requires *each* prompt to embed the allowlist.
_LOADERS: Final[dict[str, Callable[[], str]]] = {
    "synth_identity": load_synth_identity_template,
    "synth_store": load_synth_store_template,
    "synth_collections": load_synth_collections_template,
    "synth_product_skeletons": load_synth_product_skeletons_template,
    "synth_product_details": load_synth_product_details_template,
    "synth_alt_text": load_synth_alt_text_template,
    "synth_navigation": load_synth_navigation_template,
    "synth_pages": load_synth_pages_template,
    "synth_policies": load_synth_policies_template,
}


@pytest.mark.parametrize("step_id", sorted(_LOADERS))
def test_prompt_embeds_at_least_one_allowlist_brand(step_id: str) -> None:
    """Every prompt body must mention at least one current allowlist token."""
    body = _LOADERS[step_id]()
    allowlist = load_allowlist()
    matches = sorted(token for token in allowlist.brands if token in body)
    assert matches, (
        f"{step_id}: prompt body does not mention any current allowlist "
        f"brand token (spec §5.6). Expected at least one of "
        f"{sorted(allowlist.brands)} to appear after rendering."
    )


@pytest.mark.parametrize("step_id", sorted(_LOADERS))
def test_prompt_embeds_at_least_one_safe_noun(step_id: str) -> None:
    """Every prompt body must mention at least one safe-noun token."""
    body = _LOADERS[step_id]()
    allowlist = load_allowlist()
    matches = sorted(token for token in allowlist.safe_nouns if token in body)
    assert matches, (
        f"{step_id}: prompt body does not mention any safe-noun token "
        f"(spec §5.6). The brand-safety reference must enumerate the "
        f"capitalized common nouns the post-pass scanner treats as safe."
    )


@pytest.mark.parametrize("step_id", sorted(_LOADERS))
def test_prompt_brand_safety_placeholder_is_substituted(step_id: str) -> None:
    """The loader must inline ``{brand_safety}`` so step ``.format()`` calls do not see it.

    The brand-safety block is rendered from ``fake_brands.json`` at
    template-load time. Leaving the placeholder un-substituted would
    crash the step's ``str.format(...)`` call (or, worse, silently
    leak the literal token into the LLM prompt).
    """
    body = _LOADERS[step_id]()
    assert "{brand_safety}" not in body, (
        f"{step_id}: ``{{brand_safety}}`` placeholder survived the loader. "
        f"Check ``shop_arena.gen.data_synth.prompts._read_template_body``."
    )


@pytest.mark.parametrize("step_id", sorted(_LOADERS))
def test_prompt_lists_brand_safety_reference_header(step_id: str) -> None:
    """The rendered block must surface a recognizable ``Brand-safety reference`` header.

    A future refactor that drops the block would silently fail the
    "embeds the allowlist" requirement; this test gives that failure
    a name.
    """
    body = _LOADERS[step_id]()
    assert "Brand-safety reference" in body, (
        f"{step_id}: rendered prompt is missing the brand-safety reference "
        f"header. Add a ``{{brand_safety}}`` placeholder to the template."
    )
