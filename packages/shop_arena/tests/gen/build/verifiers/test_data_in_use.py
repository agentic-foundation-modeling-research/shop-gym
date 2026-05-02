"""Unit tests for :class:`shop_arena.gen.build.verifiers.data_in_use.DataInUseVerifier`.

Covers T5.4 + spec §5.5.3: extract every ``graphql\\`...\\``` block from
``hydrogen/app/**/*.{tsx,ts}`` and diff its top-level field against an
injected schema introspection. Tests cover passing, failing, multi-op,
and missing-tree paths plus the introspector-error fallback.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from harness.verifiers import Verdict, VerifierContext
from shop_arena.gen.build.verifiers.data_in_use import (
    DataInUseVerifier,
    SchemaIntrospection,
)


def _shop_backend_schema() -> SchemaIntrospection:
    """Return a representative subset of the live ``shop_backend`` schema."""
    return SchemaIntrospection(
        root_fields={
            "Query": frozenset(
                {
                    "shop",
                    "products",
                    "product",
                    "collections",
                    "collection",
                    "cart",
                    "search",
                    "page",
                    "menu",
                },
            ),
            "Mutation": frozenset(
                {
                    "cartCreate",
                    "cartLinesAdd",
                    "cartLinesUpdate",
                    "cartLinesRemove",
                },
            ),
        },
    )


def _introspector(
    schema: SchemaIntrospection | None = None,
    *,
    raises: BaseException | None = None,
) -> Callable[[], SchemaIntrospection]:
    """Build a stub introspector returning ``schema`` (or raising ``raises``)."""

    def _call() -> SchemaIntrospection:
        if raises is not None:
            raise raises
        return schema if schema is not None else _shop_backend_schema()

    return _call


def test_name_and_applicability() -> None:
    verifier = DataInUseVerifier(introspect=_introspector())
    assert verifier.name == "data_in_use"
    assert verifier.applies_to("gen_homepage") is True
    # Spec §5.5.4 lists the visual_fix gating set explicitly; data_in_use
    # is not on it.
    assert verifier.applies_to("visual_fix") is False
    assert verifier.applies_to("plan") is False


def test_passes_when_no_graphql_blocks_found(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """Early tasks (e.g. ``gen_theme``) emit CSS only — verifier should not flap."""
    write_app_file("styles/tokens.tsx", "export const palette = {};\n")
    verifier = DataInUseVerifier(introspect=_introspector())
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.PASS
    assert result.details == {"operations": 0}


def test_passes_when_all_root_fields_in_schema(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    write_app_file(
        "routes/_index.tsx",
        """
        import {graphql} from '@shopify/hydrogen';

        export const HOMEPAGE_QUERY = graphql`
          query Homepage {
            shop { name }
            products(first: 4) { nodes { id } }
          }
        `;
        """,
    )
    write_app_file(
        "routes/cart.tsx",
        """
        const ADD = graphql`
          mutation AddLines($id: ID!) {
            cartLinesAdd(cartId: $id, lines: []) { cart { id } }
          }
        `;
        """,
    )
    verifier = DataInUseVerifier(introspect=_introspector())
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.PASS
    assert result.details == {"operations": 2, "mismatches": 0}


def test_fails_on_unknown_root_field(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    write_app_file(
        "routes/_index.tsx",
        """
        const QUERY = graphql`
          query Imagined {
            blogPosts { nodes { id } }
          }
        `;
        """,
    )
    verifier = DataInUseVerifier(introspect=_introspector())
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert result.details["mismatches"] == 1
    assert "blogPosts" in result.feedback
    assert "unknown root field" in result.feedback
    # Schema's known root fields are listed in the markdown so the
    # next iteration can pick a valid one.
    assert "`shop`" in result.feedback or "shop" in result.feedback


def test_fails_on_unknown_mutation_root_field(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    write_app_file(
        "routes/checkout.tsx",
        """
        const M = graphql`
          mutation StartCheckout($id: ID!) {
            checkoutBegin(cartId: $id) { ok }
          }
        `;
        """,
    )
    verifier = DataInUseVerifier(introspect=_introspector())
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert "checkoutBegin" in result.feedback
    assert "Mutation" in result.feedback


def test_partial_mismatch_only_reports_unknown_ops(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    write_app_file(
        "routes/_index.tsx",
        """
        const Q1 = graphql`
          query KnownOne {
            shop { name }
          }
        `;
        const Q2 = graphql`
          query UnknownOne {
            blogPosts { nodes { id } }
          }
        `;
        """,
    )
    verifier = DataInUseVerifier(introspect=_introspector())
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert result.details["operations"] == 2  # noqa: PLR2004
    assert result.details["mismatches"] == 1
    assert "blogPosts" in result.feedback


def test_anonymous_operation_treated_as_query(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """An anonymous shorthand should still be checked against ``Query``."""
    write_app_file(
        "routes/_index.tsx",
        "const Q = graphql`{ shop { name } }`;\n",
    )
    verifier = DataInUseVerifier(introspect=_introspector())
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.PASS


def test_fails_when_hydrogen_tree_missing(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
) -> None:
    app_dir = artifact_dir / "hydrogen" / "app"
    app_dir.rmdir()
    (artifact_dir / "hydrogen").rmdir()

    verifier = DataInUseVerifier(introspect=_introspector())
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert "could not find the hydrogen app tree" in result.feedback


def test_introspector_error_does_not_propagate(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    write_app_file("routes/_index.tsx", "const Q = graphql`{ shop { name } }`;\n")
    verifier = DataInUseVerifier(
        introspect=_introspector(raises=ConnectionError("sidecar dead")),
    )
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert "could not introspect" in result.feedback
    assert "ConnectionError" in result.feedback


def test_unparseable_block_reports_distinct_reason(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """A graphql block whose body has no selection set is flagged distinctly."""
    write_app_file(
        "routes/broken.tsx",
        "const Q = graphql`query Empty `;\n",
    )
    verifier = DataInUseVerifier(introspect=_introspector())
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert "could not be" in result.feedback


def test_skips_non_ts_extensions(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """A graphql block hidden in a `.json` file should not be picked up."""
    write_app_file(
        "data/queries.json",
        '{"q": "graphql`query { blogPosts { id } }`"}',
    )
    verifier = DataInUseVerifier(introspect=_introspector())
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.PASS
    assert result.details == {"operations": 0}
