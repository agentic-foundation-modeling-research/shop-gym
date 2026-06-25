"""``data_in_use`` build-loop verifier (spec §5.5.3).

Diffs the GraphQL queries the agent authored under the hydrogen
``app/`` tree against the live ``shop_backend`` schema, surfaced via
introspection. Spec §5.5.3 describes the rule as "introspection
diff" — any root field referenced by an agent-authored query that is
not present on the corresponding root type fails the verifier and
feeds the diff into the next iteration's prompt.

The check operates on the operation root fields (top-level selections
on ``Query``/``Mutation``/``Subscription``). Nested-field validation
would require a full GraphQL parser + schema validator; v0.1 keeps the
dependency footprint minimal and ships a regex-driven extraction that
catches the most common failure mode — an agent inventing a top-level
query name that the backend does not expose. T5.4 explicitly carves out
the lighter check; deeper field-by-field validation is a v0.2
follow-up.

The schema is supplied through the :class:`SchemaIntrospection` seam:

* Production callers pass an introspector that POSTs the canonical
  introspection query against the live sidecar (T5.6 wires this up).
* Tests inject a :class:`SchemaIntrospection` literal containing the
  ``shop_backend`` root field set used by the cassette fixtures.

Applicability mirrors the spec table: every ``gen_*`` task. The
``visual_fix`` task is excluded — §5.5.4 lists its gating verifier
set and ``data_in_use`` is not on it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from harness.verifiers import Verdict, VerifierContext, VerifierResult

_NAME: Final[str] = "data_in_use"
"""Verifier name (filesystem-safe; matches the spec table)."""

_HYDROGEN_APP_DIR: Final[str] = "hydrogen/app"
"""Path of the hydrogen ``app/`` tree relative to ``VerifierContext.artifact_dir``."""

_SCAN_SUFFIXES: Final[frozenset[str]] = frozenset({".tsx", ".ts"})
"""Source-file extensions inspected for GraphQL operations."""

_CUSTOMER_ACCOUNT_GRAPHQL_PARTS: Final[tuple[str, str]] = ("graphql", "customer-account")
"""Template subtree containing Customer Account API queries, not Storefront API queries."""

# Match Hydrogen GraphQL template literals. The template accepts both
# ``graphql`...``` tagged blocks and the ```#graphql ...``` magic-comment
# form used by recent Hydrogen examples.
_GRAPHQL_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:graphql`(?P<tagged>[^`]*)`|`(?P<hash>\s*#graphql\b[^`]*)`)",
    re.DOTALL,
)

# Capture an operation header, e.g. `query Foo { ... }` or
# `mutation { ... }`. The verifier is lenient about anonymous
# operations — they're legal GraphQL.
_OPERATION_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(query|mutation|subscription)\b\s*([A-Za-z_][A-Za-z0-9_]*)?",
    re.IGNORECASE | re.MULTILINE,
)

# Capture the first identifier inside the operation's selection set.
# We deliberately match a single root field per extracted block and
# accept the simplification: the v0.1 check is "did the agent invent a
# top-level field?", not "did every nested field type-check?".
_ROOT_FIELD_RE: Final[re.Pattern[str]] = re.compile(
    r"\{\s*(?:#[^\n]*\n\s*)*(?:(?:[A-Za-z_][A-Za-z0-9_]*)\s*:\s*)?([A-Za-z_][A-Za-z0-9_]*)",
)

_OPERATION_TO_ROOT: Final[dict[str, str]] = {
    "query": "Query",
    "mutation": "Mutation",
    "subscription": "Subscription",
}


@dataclass(frozen=True, slots=True)
class SchemaIntrospection:
    """Subset of a GraphQL introspection result this verifier needs.

    Attributes:
        root_fields: Mapping from root type name (``"Query"``,
            ``"Mutation"``, ``"Subscription"``) to the frozen set of
            field names exposed at that root by the live schema.
    """

    root_fields: dict[str, frozenset[str]]

    def fields_for(self, root_type: str) -> frozenset[str]:
        """Return the field set for ``root_type`` or an empty frozen set.

        Args:
            root_type: Root type name (case-sensitive).

        Returns:
            The frozen set of field names; empty when the root type is
            absent from the introspection (e.g. a schema that does not
            expose mutations).
        """
        return self.root_fields.get(root_type, frozenset())


@runtime_checkable
class Introspector(Protocol):
    """Callable that returns a :class:`SchemaIntrospection` snapshot.

    Production callers pass an introspector that POSTs the canonical
    introspection query against the live sidecar. Tests inject a
    callable returning a literal :class:`SchemaIntrospection`.
    """

    def __call__(self) -> SchemaIntrospection:
        """Return the current schema's root-field index."""
        ...


@dataclass(frozen=True, slots=True)
class GraphQLOperationRef:
    """Pointer to one extracted GraphQL operation.

    Attributes:
        path: Run-relative path of the source file the block came from.
        operation_type: One of ``"Query"`` / ``"Mutation"`` /
            ``"Subscription"``. Always already canonicalised
            (PascalCase).
        operation_name: Optional operation name. ``None`` for
            anonymous operations.
        root_field: First top-level field name in the selection set, or
            ``None`` when extraction failed (the caller treats
            extraction failure as a parse-shape problem, separate from
            the schema diff).
    """

    path: Path
    operation_type: str
    operation_name: str | None
    root_field: str | None


@dataclass(frozen=True, slots=True)
class GraphQLOperationError:
    """One mismatch surfaced by :meth:`DataInUseVerifier.run`.

    Attributes:
        ref: Pointer to the offending operation.
        reason: Short human-readable explanation rendered into the
            feedback markdown. Either ``"unknown_root_field"`` for
            schema misses, or ``"unparseable_operation"`` for blocks
            the regex could not break down.
    """

    ref: GraphQLOperationRef
    reason: str


class DataInUseVerifier:
    """Diffs hydrogen GraphQL operations against the live ``shop_backend`` schema.

    Attributes:
        name: ``"data_in_use"`` — used as the per-verifier telemetry
            filename and the markdown section heading in
            ``feedback.md``.
    """

    name: str = _NAME

    def __init__(
        self,
        *,
        introspect: Introspector,
        app_dir: Path = Path(_HYDROGEN_APP_DIR),
    ) -> None:
        """Build the verifier with an introspection seam.

        Args:
            introspect: Callable that returns the current schema's
                root-field index. See :class:`Introspector`.
            app_dir: Storefront ``app/`` directory relative to
                ``VerifierContext.artifact_dir``. Defaults to
                ``hydrogen/app`` for backward compatibility.
        """
        self._introspect = introspect
        self._app_dir = app_dir

    def applies_to(self, task_id: str) -> bool:
        """Match every ``gen_*`` task (spec §5.5.3).

        Args:
            task_id: Selected task id.

        Returns:
            ``True`` when the verifier should run for ``task_id``.
        """
        return task_id.startswith("gen_")

    def run(self, ctx: VerifierContext) -> VerifierResult:
        """Extract every GraphQL operation, diff against the schema.

        Args:
            ctx: Verifier context. Reads ``ctx.artifact_dir`` to locate
                the hydrogen ``app/`` tree; ``ctx.runtime`` is unused.

        Returns:
            ``PASS`` when every extracted operation references a known
            root field. ``FAIL`` with the diff embedded in the
            feedback markdown otherwise.

            A missing hydrogen tree returns ``FAIL`` with explanatory
            feedback. An introspector that raises is converted into a
            ``FAIL`` with the exception type/message rather than
            propagated — verifier dispatch should never deadlock the
            loop.
        """
        app_dir = ctx.artifact_dir / self._app_dir
        if not app_dir.is_dir():
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    "data_in_use could not find the hydrogen app tree "
                    f"at `{self._app_dir.as_posix()}/`. Did `clone_template` "
                    "run?"
                ),
                details={"app_dir": str(app_dir), "exists": False},
            )

        try:
            schema = self._introspect()
        except Exception as exc:
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"data_in_use could not introspect the live schema: {type(exc).__name__}: {exc}"
                ),
                details={"phase": "introspect", "error": str(exc)},
            )

        operations = list(_extract_operations(app_dir))
        if not operations:
            # No agent-authored GraphQL yet; the verifier has nothing
            # to gate. Return PASS so early `gen_theme`-style tasks do
            # not flap.
            return VerifierResult(
                verdict=Verdict.PASS,
                details={"operations": 0},
            )

        errors: list[GraphQLOperationError] = []
        for ref in operations:
            error = _diff(ref, schema)
            if error is not None:
                errors.append(error)

        if not errors:
            return VerifierResult(
                verdict=Verdict.PASS,
                details={"operations": len(operations), "mismatches": 0},
            )
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback=_render_failure_markdown(
                errors=errors,
                schema=schema,
                total_operations=len(operations),
            ),
            details={
                "operations": len(operations),
                "mismatches": len(errors),
                "first_path": str(errors[0].ref.path),
                "first_reason": errors[0].reason,
            },
        )


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _extract_operations(app_dir: Path) -> Iterable[GraphQLOperationRef]:
    """Yield one ref per operation-bearing Hydrogen GraphQL block."""
    for path in sorted(app_dir.rglob("*")):
        if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
            continue
        app_rel_path = path.relative_to(app_dir)
        if app_rel_path.parts[:2] == _CUSTOMER_ACCOUNT_GRAPHQL_PARTS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for block in _GRAPHQL_BLOCK_RE.finditer(text):
            body = block.group("tagged") or block.group("hash") or ""
            ref = _parse_operation(
                rel_path=path.relative_to(app_dir.parent.parent),
                body=_strip_hash_graphql_marker(body),
            )
            if ref is not None:
                yield ref


def _strip_hash_graphql_marker(body: str) -> str:
    """Remove a leading ``#graphql`` marker from a template body.

    Args:
        body: Raw template literal body.

    Returns:
        Body with the optional first-line marker removed.
    """
    return re.sub(r"^\s*#graphql[^\n]*(?:\n|$)", "", body, count=1)


def _parse_operation(*, rel_path: Path, body: str) -> GraphQLOperationRef | None:
    """Parse one GraphQL template body into a :class:`GraphQLOperationRef`.

    The parser is intentionally regex-driven; spec §5.5.3 does not
    mandate a full GraphQL parser and the v0.1 check is satisfied by
    extracting the operation type + first root field.
    """
    op_match = _OPERATION_RE.search(body)
    if op_match is None:
        if not body.lstrip().startswith("{"):
            # Fragment-only blocks and interpolation-only blocks are not
            # executable operations, so there is no root field to diff.
            return None
        # Anonymous shorthand (``graphql`{ ... }```) — treat as a query.
        operation_type = "Query"
        operation_name: str | None = None
        selection_body = body
    else:
        operation_type = _OPERATION_TO_ROOT[op_match.group(1).lower()]
        raw_name = op_match.group(2)
        operation_name = raw_name if raw_name else None
        selection_body = body[op_match.end() :]

    root_field_match = _ROOT_FIELD_RE.search(selection_body)
    root_field = root_field_match.group(1) if root_field_match is not None else None
    return GraphQLOperationRef(
        path=rel_path,
        operation_type=operation_type,
        operation_name=operation_name,
        root_field=root_field,
    )


def _diff(
    ref: GraphQLOperationRef,
    schema: SchemaIntrospection,
) -> GraphQLOperationError | None:
    """Return an error when ``ref``'s root field is not in the live schema."""
    if ref.root_field is None:
        return GraphQLOperationError(ref=ref, reason="unparseable_operation")
    valid_fields = schema.fields_for(ref.operation_type)
    if ref.root_field in valid_fields:
        return None
    return GraphQLOperationError(ref=ref, reason="unknown_root_field")


def _render_failure_markdown(
    *,
    errors: list[GraphQLOperationError],
    schema: SchemaIntrospection,
    total_operations: int,
) -> str:
    """Render the failure feedback body."""
    lines = [
        f"`data_in_use` failed: {len(errors)} of {total_operations} GraphQL "
        "operation(s) do not match the `shop_backend` schema.",
        "",
        "Use only fields exposed by the introspection result; remove any "
        "operation whose top-level selection is unknown.",
    ]
    query_fields = sorted(schema.fields_for("Query"))
    if query_fields:
        lines.extend(
            (
                "",
                "Schema `Query` root fields:",
                ", ".join(f"`{name}`" for name in query_fields),
            ),
        )
    mutation_fields = sorted(schema.fields_for("Mutation"))
    if mutation_fields:
        lines.extend(
            (
                "",
                "Schema `Mutation` root fields:",
                ", ".join(f"`{name}`" for name in mutation_fields),
            ),
        )
    lines.extend(("", "Mismatches:"))
    for error in errors:
        ref = error.ref
        op_name = ref.operation_name or "<anonymous>"
        if error.reason == "unknown_root_field":
            lines.append(
                f"- `{ref.path}`: {ref.operation_type} `{op_name}` references "
                f"unknown root field `{ref.root_field}`.",
            )
        else:
            lines.append(
                f"- `{ref.path}`: {ref.operation_type} `{op_name}` could not be "
                "parsed (no top-level field).",
            )
    return "\n".join(lines)


__all__ = [
    "DataInUseVerifier",
    "GraphQLOperationError",
    "GraphQLOperationRef",
    "Introspector",
    "SchemaIntrospection",
]
