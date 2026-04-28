"""``validate_hosting`` — Phase 3 hosting check (spec §5.4).

Second and final step of the data-validation sub-DAG. Boots the
``shop-backend`` CLI against the published ``data/`` directory on a
free localhost port, drives the canonical Storefront-API query suite
listed in ``docs/specs/shop_arena/shop_gen.md`` §5.4 over real HTTP,
and writes the structured verdict to
``<out_dir>/data_validation.json``.

The check is in-process orchestration only — the GraphQL surface, the
SandboxShop loader, and the static-image route all live in
``packages/shop_backend/`` (Node + graphql-yoga). ``shop_gen`` owns
the lifecycle: it picks a free port, spawns the CLI, polls
``/health`` until ready, runs the queries, and tears the subprocess
down on completion or failure (including signals).

Spec §5.4 query suite:

1. ``Query.shop`` — name, currency, primaryDomain non-empty.
2. ``Query.products(first: 50)`` — count >= 0.8 * on-disk target.
3. ``Query.collections(first: 50)`` — count equals on-disk target.
4. ``Query.collection(handle)`` — resolves with non-empty products.
5. ``Query.product(handle)`` — resolves with a non-null variant
   (``selectedOrFirstAvailableVariant``) + image (``featuredImage``).
6. Cart lifecycle:
   ``cartCreate`` → ``cartLinesAdd`` → ``cartLinesUpdate(quantity:0)``
   → ``cartLinesRemove`` (each step asserts the response shape).
7. ``Query.search(query: <title token>)`` — >= 1 hit.
8. ``GET /images/<sample>`` — 200 + ``image/*`` content-type.

A failure raises :class:`HostingValidationError` so the runner records
the step ``FAILED``; spec §5.4 instructs the user to re-run with
``--from assemble_data`` (auto-retry is a v0.2 follow-up). The verdict
file (``data_validation.json``) is **not** written on failure — the
runner's existence-of-output check would otherwise mask the failure
on the next invocation.

Step contract (spec §5.7.1):

* ``id``: ``validate_hosting``.
* ``phase``: ``data_validation``.
* ``inputs``: a :class:`~shop_gen.steps.base.StepInput` for the
  upstream ``validate_schema`` step + one
  :class:`~shop_gen.steps.base.FileInput` per ``data/*.json`` file.
* ``outputs``: ``[data_validation.json]``.
* ``depends_on``: ``[validate_schema]``.

Module is import-safe: no I/O, no env reads, no side effects at
import time.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Final, cast

import httpx

from shop_gen.steps.base import FileInput, InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_validation"
_STEP_ID: Final[str] = "validate_hosting"
_STEP_VERSION: Final[int] = 1

_UPSTREAM_VALIDATE_SCHEMA: Final[str] = "validate_schema"

_DATA_DIR: Final[Path] = Path("data")
_OUT_REPORT: Final[Path] = Path("data_validation.json")

_IN_FILES: Final[tuple[Path, ...]] = (
    _DATA_DIR / "store.json",
    _DATA_DIR / "products.json",
    _DATA_DIR / "collections.json",
    _DATA_DIR / "pages.json",
    _DATA_DIR / "policies.json",
    _DATA_DIR / "navigation.json",
)

_HEALTH_TIMEOUT_S: Final[float] = 15.0
"""Maximum wall-clock time spent polling ``/health`` after spawn."""

_HEALTH_POLL_INTERVAL_S: Final[float] = 0.1
"""Sleep between ``/health`` poll attempts."""

_REQUEST_TIMEOUT_S: Final[float] = 10.0
"""Per-request HTTP timeout for GraphQL + image checks."""

_TERMINATE_GRACE_S: Final[float] = 3.0
"""Time given to the subprocess to exit after ``SIGTERM`` before ``SIGKILL``."""

_TARGET_PRODUCT_RATIO: Final[float] = 0.8
"""Spec §5.4: ``Query.products(first: 50)`` must return >= 0.8 * target."""

_PAGE_SIZE: Final[int] = 50
"""``first:`` argument shared by ``products`` / ``collections`` queries."""

_HTTP_OK: Final[int] = 200
"""HTTP success status code (matches ``shop-backend``'s ``/health``)."""

_CART_TOTAL_AFTER_ADD: Final[int] = 3
"""Expected ``totalQuantity`` after ``cartCreate(qty=1)`` + ``cartLinesAdd(qty=2)``."""

_CART_TOTAL_AFTER_UPDATE: Final[int] = 1
"""Expected ``totalQuantity`` after dropping the secondary line via ``cartLinesUpdate(0)``."""

_CART_TOTAL_AFTER_REMOVE: Final[int] = 0
"""Expected ``totalQuantity`` after ``cartLinesRemove`` empties the cart."""

_MIN_DISTINCT_VARIANTS: Final[int] = 2
"""Cart-lifecycle check needs two distinct variants to exercise add/update/remove."""

# Storefront API GIDs use ``gid://shopify/<Type>/<numeric-id>`` for numeric
# dataset ids (see ``packages/shop_backend/src/resolvers/builders.ts``).
_VARIANT_GID_TEMPLATE: Final[str] = "gid://shopify/ProductVariant/{id}"

_TITLE_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z]{3,}")
"""Pick the first 3+-character alphabetic word as a deterministic search token."""


class HostingValidationError(RuntimeError):
    """Raised when the hosting check fails.

    Carries the structured per-check verdict so callers can surface
    every failure in one shot rather than re-running to discover the
    next one.

    Attributes:
        message: Short human-readable summary (also embedded in
            ``str(exc)``).
        checks: One dict per executed check. Each entry has at least
            ``name``, ``ok``, and ``detail`` fields. Empty when the
            failure prevented any check from running (e.g. the CLI
            could not be located).
    """

    def __init__(
        self,
        *,
        message: str,
        checks: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(f"{_STEP_ID}: {message}")
        self.message: str = message
        self.checks: list[dict[str, Any]] = list(checks) if checks else []


class ValidateHostingStep:
    """Phase 3 ``validate_hosting`` step (spec §5.4).

    Boots ``shop-backend`` against ``<ctx.out_dir>/data/`` and runs the
    canonical query suite. Writes ``data_validation.json`` on success;
    raises :class:`HostingValidationError` on failure.

    Attributes:
        id: Step id (``validate_hosting``).
        phase: ``data_validation``.
        inputs: One :class:`StepInput` for ``validate_schema`` plus a
            :class:`FileInput` per ``data/*.json`` file.
        outputs: ``[data_validation.json]``.
        depends_on: ``[validate_schema]``.
        version: Bumped when the query suite changes (spec §5.7.1).
    """

    def __init__(self) -> None:
        """Build the step bound to the upstream ``validate_schema`` producer."""
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [
            StepInput(step_id=_UPSTREAM_VALIDATE_SCHEMA),
            *(FileInput(path=p) for p in _IN_FILES),
        ]
        self.outputs: list[Path] = [_OUT_REPORT]
        self.depends_on: list[str] = [_UPSTREAM_VALIDATE_SCHEMA]
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Boot ``shop-backend``, run the query suite, write the verdict.

        Args:
            ctx: Execution context. ``ctx.runtime`` is ignored — the
                step talks only to the spawned ``shop-backend``
                subprocess.

        Raises:
            HostingValidationError: The subprocess failed to come up,
                a query returned an error / unexpected shape, or the
                static-image GET did not return 200.
        """
        verdict = run_hosting_checks(ctx.out_dir / _DATA_DIR)
        out_path = ctx.out_dir / _OUT_REPORT
        out_path.write_text(
            json.dumps(verdict, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


# --------------------------------------------------------------------------- #
# Pure validator (testable without a running step)
# --------------------------------------------------------------------------- #


def run_hosting_checks(
    data_dir: Path,
    *,
    cli_path: Path | None = None,
    health_timeout_s: float = _HEALTH_TIMEOUT_S,
) -> dict[str, Any]:
    """Boot ``shop-backend`` against ``data_dir`` and run the §5.4 query suite.

    The subprocess is always torn down before this function returns,
    even on failure or when an unrelated exception bubbles up.

    Args:
        data_dir: Directory containing the six published ``data/*.json``
            files plus an ``images/`` subdirectory.
        cli_path: Optional override for the resolved
            ``packages/shop_backend/dist/cli.js`` path. Tests inject a
            stub script here; production callers leave ``None`` and let
            :func:`find_shop_backend_cli` walk the workspace.
        health_timeout_s: Maximum wall-clock time spent polling
            ``/health`` after spawn before declaring the boot a
            failure.

    Returns:
        Verdict mapping suitable for ``data_validation.json``:

        * ``ok`` — overall pass/fail (always ``True`` on a successful
          return; failures raise instead of returning ``ok=False``).
        * ``port`` — the localhost port the subprocess was bound to.
        * ``store_name`` — the shop name reported by ``/health``.
        * ``checks`` — one entry per executed check, each
          ``{"name", "ok", "detail"}``.

    Raises:
        HostingValidationError: A boot, query, or image-fetch check
            failed.
        FileNotFoundError: A required input file is absent under
            ``data_dir``.
    """
    products = _load_array(data_dir / "products.json")
    collections = _load_array(data_dir / "collections.json")

    cli = cli_path if cli_path is not None else find_shop_backend_cli()
    port = _allocate_free_port()

    proc = subprocess.Popen(
        ["node", str(cli), str(data_dir), str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        store_name = _wait_for_health(proc, base_url, timeout_s=health_timeout_s)
        with httpx.Client(base_url=base_url, timeout=_REQUEST_TIMEOUT_S) as client:
            checks = _run_query_suite(
                client=client,
                products=products,
                collections=collections,
            )
    finally:
        _terminate(proc)

    failed = [c for c in checks if not c["ok"]]
    if failed:
        names = ", ".join(c["name"] for c in failed)
        raise HostingValidationError(
            message=f"{len(failed)} hosting check(s) failed: {names}",
            checks=checks,
        )

    return {
        "ok": True,
        "port": port,
        "store_name": store_name,
        "data_dir": str(data_dir),
        "checks": checks,
    }


def find_shop_backend_cli() -> Path:
    """Locate the bundled ``packages/shop_backend/dist/cli.js`` in the monorepo.

    Walks parent directories from this module's location until it finds
    a checkout that contains ``packages/shop_backend/dist/cli.js``. The
    ``SHOP_BACKEND_CLI`` env var overrides the search.

    Returns:
        Absolute path to the compiled ``cli.js``.

    Raises:
        HostingValidationError: The CLI script cannot be located. The
            error message points at the build command that produces it.
    """
    override = os.environ.get("SHOP_BACKEND_CLI")
    if override:
        candidate = Path(override).resolve()
        if candidate.is_file():
            return candidate
        raise HostingValidationError(
            message=f"SHOP_BACKEND_CLI={override!r} does not point at a regular file",
        )
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "packages" / "shop_backend" / "dist" / "cli.js"
        if candidate.is_file():
            return candidate
    raise HostingValidationError(
        message=(
            "could not locate packages/shop_backend/dist/cli.js — "
            "run `pnpm --filter @shop-gym/shop-backend build` first"
        ),
    )


# --------------------------------------------------------------------------- #
# Internals — subprocess lifecycle
# --------------------------------------------------------------------------- #


def _allocate_free_port() -> int:
    """Bind a TCP socket to port 0 and return the kernel-assigned port.

    The socket is closed before returning, so a small race window exists
    between port selection and ``shop-backend`` binding. In practice
    this is acceptable for a single-machine, single-test scenario; the
    spec does not require atomic port handoff.
    """
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return cast("int", sock.getsockname()[1])


def _wait_for_health(
    proc: subprocess.Popen[bytes],
    base_url: str,
    *,
    timeout_s: float,
) -> str:
    """Poll ``GET /health`` until the subprocess responds 200 or the deadline expires.

    Returns:
        The ``store`` field from the health-check JSON.

    Raises:
        HostingValidationError: The subprocess exited before becoming
            healthy, or the deadline expired.
    """
    deadline = time.monotonic() + timeout_s
    last_error: str = ""
    while time.monotonic() < deadline:
        rc = proc.poll()
        if rc is not None:
            stderr = _drain(proc.stderr).decode("utf-8", errors="replace")
            raise HostingValidationError(
                message=(
                    f"shop-backend exited with code {rc} before /health responded; "
                    f"stderr=\n{stderr}"
                ),
            )
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
        except httpx.HTTPError as exc:
            last_error = str(exc)
            time.sleep(_HEALTH_POLL_INTERVAL_S)
            continue
        if response.status_code == _HTTP_OK:
            payload = cast("dict[str, Any]", response.json())
            store = payload.get("store")
            if not isinstance(store, str):
                raise HostingValidationError(
                    message=f"/health returned unexpected payload: {payload!r}",
                )
            return store
        last_error = f"HTTP {response.status_code}"
        time.sleep(_HEALTH_POLL_INTERVAL_S)
    raise HostingValidationError(
        message=f"timed out waiting for /health after {timeout_s:.1f}s; last={last_error}",
    )


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    """Stop the spawned subprocess. Idempotent for an already-exited process."""
    if proc.poll() is not None:
        return
    proc.terminate()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=_TERMINATE_GRACE_S)
        return
    proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=_TERMINATE_GRACE_S)


def _drain(stream: object) -> bytes:
    """Read whatever is currently buffered on ``stream`` (best-effort)."""
    if stream is None:
        return b""
    try:
        return cast("Any", stream).read() or b""
    except (OSError, ValueError):
        return b""


# --------------------------------------------------------------------------- #
# Internals — query suite
# --------------------------------------------------------------------------- #


def _run_query_suite(
    *,
    client: httpx.Client,
    products: list[dict[str, Any]],
    collections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Run every spec §5.4 check in order; return the ordered verdict list."""
    return [
        _check_shop(client),
        _check_products(client, target=len(products)),
        _check_collections(client, target=len(collections)),
        _check_collection_by_handle(client, collections=collections),
        _check_product_by_handle(client, products=products),
        _check_cart_lifecycle(client, products=products),
        _check_search(client, products=products),
        _check_image(client, products=products),
    ]


def _check_shop(client: httpx.Client) -> dict[str, Any]:
    query = """
    {
      shop {
        name
        primaryDomain { host url }
        paymentSettings { currencyCode }
      }
    }
    """
    name = "shop"
    try:
        data = _gql(client, query)
    except _GqlError as exc:
        return _failure(name, str(exc))
    shop = cast("dict[str, Any] | None", data.get("shop"))
    if not isinstance(shop, dict):
        return _failure(name, "Query.shop returned null")
    if not shop.get("name"):
        return _failure(name, "shop.name is empty")
    domain = cast("dict[str, Any] | None", shop.get("primaryDomain"))
    if not isinstance(domain, dict) or not domain.get("host"):
        return _failure(name, "shop.primaryDomain.host is empty")
    payment = cast("dict[str, Any] | None", shop.get("paymentSettings"))
    if not isinstance(payment, dict) or not payment.get("currencyCode"):
        return _failure(name, "shop.paymentSettings.currencyCode is empty")
    return _success(name, f"name={shop['name']!r}, currency={payment['currencyCode']!r}")


def _check_products(client: httpx.Client, *, target: int) -> dict[str, Any]:
    name = "products"
    if target == 0:
        return _failure(name, "products.json is empty")
    query = f"{{ products(first: {_PAGE_SIZE}) {{ nodes {{ handle }} }} }}"
    try:
        data = _gql(client, query)
    except _GqlError as exc:
        return _failure(name, str(exc))
    nodes = _nodes(data, "products")
    # The first-page response is capped at ``_PAGE_SIZE``; catalog
    # completeness is enforced upstream by ``validate_schema``. This
    # check only verifies the products surface is wired up.
    expected = min(target, _PAGE_SIZE)
    threshold = max(1, int(_TARGET_PRODUCT_RATIO * expected))
    if len(nodes) < threshold:
        return _failure(
            name,
            (
                f"products(first: {_PAGE_SIZE}) returned {len(nodes)}; "
                f"expected >= {threshold} (0.8 * {expected}) of {target} on disk"
            ),
        )
    return _success(name, f"returned {len(nodes)} of {target}")


def _check_collections(client: httpx.Client, *, target: int) -> dict[str, Any]:
    name = "collections"
    if target == 0:
        return _failure(name, "collections.json is empty")
    query = f"{{ collections(first: {_PAGE_SIZE}) {{ nodes {{ handle }} }} }}"
    try:
        data = _gql(client, query)
    except _GqlError as exc:
        return _failure(name, str(exc))
    nodes = _nodes(data, "collections")
    if len(nodes) != target:
        return _failure(
            name,
            f"collections(first: {_PAGE_SIZE}) returned {len(nodes)}; expected {target}",
        )
    return _success(name, f"returned {len(nodes)} of {target}")


def _check_collection_by_handle(
    client: httpx.Client,
    *,
    collections: list[dict[str, Any]],
) -> dict[str, Any]:
    name = "collection_by_handle"
    if not collections:
        return _failure(name, "collections.json is empty")
    handle = cast("str", collections[0]["handle"])
    query = f"""
    {{
      collection(handle: "{handle}") {{
        handle
        products(first: 5) {{ nodes {{ handle }} }}
      }}
    }}
    """
    try:
        data = _gql(client, query)
    except _GqlError as exc:
        return _failure(name, str(exc))
    collection = cast("dict[str, Any] | None", data.get("collection"))
    if not isinstance(collection, dict):
        return _failure(name, f"collection(handle: {handle!r}) returned null")
    nodes = _nodes(collection, "products")
    if not nodes:
        return _failure(name, f"collection(handle: {handle!r}) has no products")
    return _success(name, f"handle={handle!r} has {len(nodes)} product(s)")


def _check_product_by_handle(
    client: httpx.Client,
    *,
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    name = "product_by_handle"
    if not products:
        return _failure(name, "products.json is empty")
    handle = cast("str", products[0]["handle"])
    # Use scalar selectors here: ``Product.variants/images`` are SDL
    # connections but the v0.1 ``shop_backend`` resolvers return plain
    # arrays (storefront_api_implementation v0.2 follow-up). The
    # ``selectedOrFirstAvailableVariant`` + ``featuredImage`` selectors
    # exercise the same data without depending on the connection wiring.
    query = f"""
    {{
      product(handle: "{handle}") {{
        handle
        selectedOrFirstAvailableVariant {{ id }}
        featuredImage {{ url }}
      }}
    }}
    """
    try:
        data = _gql(client, query)
    except _GqlError as exc:
        return _failure(name, str(exc))
    product = cast("dict[str, Any] | None", data.get("product"))
    if not isinstance(product, dict):
        return _failure(name, f"product(handle: {handle!r}) returned null")
    variant = cast("dict[str, Any] | None", product.get("selectedOrFirstAvailableVariant"))
    if not isinstance(variant, dict) or not variant.get("id"):
        return _failure(name, f"product(handle: {handle!r}) has no variants")
    image = cast("dict[str, Any] | None", product.get("featuredImage"))
    if not isinstance(image, dict) or not image.get("url"):
        return _failure(name, f"product(handle: {handle!r}) has no images")
    return _success(
        name,
        f"handle={handle!r}: variant={variant['id']!r}, image={image['url']!r}",
    )


def _check_cart_lifecycle(  # noqa: PLR0911 — each cart stage is its own failure path
    client: httpx.Client,
    *,
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    name = "cart_lifecycle"
    variants = _pick_two_variants(products)
    if variants is None:
        return _failure(name, "dataset has fewer than two distinct variants")
    primary_id, secondary_id = variants
    primary_gid = _VARIANT_GID_TEMPLATE.format(id=primary_id)
    secondary_gid = _VARIANT_GID_TEMPLATE.format(id=secondary_id)

    cart_fragment = """cart {
      id
      totalQuantity
      lines(first: 10) {
        nodes {
          ... on CartLine {
            id
            quantity
            merchandise { ... on ProductVariant { id } }
          }
        }
      }
    }"""

    # 1. cartCreate with one starting line.
    try:
        created = _gql(
            client,
            f"""
            mutation {{
              cartCreate(input: {{
                lines: [{{ merchandiseId: "{primary_gid}", quantity: 1 }}]
              }}) {{ {cart_fragment} }}
            }}
            """,
        )
    except _GqlError as exc:
        return _failure(name, f"cartCreate: {exc}")
    cart = _extract_cart(created, "cartCreate")
    if cart is None:
        return _failure(name, "cartCreate returned null cart")
    cart_id = cart["id"]

    # 2. cartLinesAdd appends a second variant.
    try:
        added = _gql(
            client,
            f"""
            mutation {{
              cartLinesAdd(
                cartId: "{cart_id}"
                lines: [{{ merchandiseId: "{secondary_gid}", quantity: 2 }}]
              ) {{ {cart_fragment} }}
            }}
            """,
        )
    except _GqlError as exc:
        return _failure(name, f"cartLinesAdd: {exc}")
    cart_after_add = _extract_cart(added, "cartLinesAdd")
    if cart_after_add is None or cart_after_add["totalQuantity"] != _CART_TOTAL_AFTER_ADD:
        return _failure(
            name,
            f"cartLinesAdd: expected totalQuantity={_CART_TOTAL_AFTER_ADD}, got {cart_after_add!r}",
        )
    secondary_line_id = _line_id_for(cart_after_add, secondary_gid)
    if secondary_line_id is None:
        return _failure(name, "cartLinesAdd: secondary line not present in response")

    # 3. cartLinesUpdate(quantity: 0) drops the secondary line.
    try:
        updated = _gql(
            client,
            f"""
            mutation {{
              cartLinesUpdate(
                cartId: "{cart_id}"
                lines: [{{ id: "{secondary_line_id}", quantity: 0 }}]
              ) {{ {cart_fragment} }}
            }}
            """,
        )
    except _GqlError as exc:
        return _failure(name, f"cartLinesUpdate: {exc}")
    cart_after_update = _extract_cart(updated, "cartLinesUpdate")
    if cart_after_update is None or cart_after_update["totalQuantity"] != _CART_TOTAL_AFTER_UPDATE:
        return _failure(
            name,
            f"cartLinesUpdate: expected totalQuantity={_CART_TOTAL_AFTER_UPDATE}, "
            f"got {cart_after_update!r}",
        )
    primary_line_id = _line_id_for(cart_after_update, primary_gid)
    if primary_line_id is None:
        return _failure(name, "cartLinesUpdate: primary line missing post-update")

    # 4. cartLinesRemove drops the primary line.
    try:
        removed = _gql(
            client,
            f"""
            mutation {{
              cartLinesRemove(
                cartId: "{cart_id}"
                lineIds: ["{primary_line_id}"]
              ) {{ {cart_fragment} }}
            }}
            """,
        )
    except _GqlError as exc:
        return _failure(name, f"cartLinesRemove: {exc}")
    cart_after_remove = _extract_cart(removed, "cartLinesRemove")
    if cart_after_remove is None or cart_after_remove["totalQuantity"] != _CART_TOTAL_AFTER_REMOVE:
        return _failure(
            name,
            f"cartLinesRemove: expected totalQuantity={_CART_TOTAL_AFTER_REMOVE}, "
            f"got {cart_after_remove!r}",
        )
    return _success(name, "create -> add -> update(0) -> remove all returned valid carts")


def _check_search(
    client: httpx.Client,
    *,
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    name = "search"
    token = _pick_search_token(products)
    if token is None:
        return _failure(name, "no usable search token in any product title")
    query = f"""
    {{
      search(query: "{token}", first: 5) {{
        nodes {{ __typename }}
      }}
    }}
    """
    try:
        data = _gql(client, query)
    except _GqlError as exc:
        return _failure(name, str(exc))
    nodes = _nodes(data, "search")
    if not nodes:
        return _failure(name, f"search(query: {token!r}) returned 0 hits")
    return _success(name, f"query={token!r} returned {len(nodes)} hit(s)")


def _check_image(
    client: httpx.Client,
    *,
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    name = "image_get"
    sample = _pick_image_src(products)
    if sample is None:
        return _failure(name, "no product image src present in dataset")
    url_path = f"/images/{sample}"
    try:
        response = client.get(url_path)
    except httpx.HTTPError as exc:
        return _failure(name, f"GET {url_path}: {exc}")
    if response.status_code != _HTTP_OK:
        return _failure(name, f"GET {url_path}: HTTP {response.status_code}")
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        return _failure(name, f"GET {url_path}: content-type={content_type!r}")
    return _success(name, f"GET {url_path}: {content_type}")


# --------------------------------------------------------------------------- #
# Internals — GraphQL helpers
# --------------------------------------------------------------------------- #


class _GqlError(RuntimeError):
    """Local-only marker for GraphQL transport / payload errors."""


def _gql(client: httpx.Client, query: str) -> dict[str, Any]:
    """POST ``query`` to ``/graphql`` and return ``data`` or raise :class:`_GqlError`."""
    try:
        response = client.post("/graphql", json={"query": query})
    except httpx.HTTPError as exc:
        raise _GqlError(f"http error: {exc}") from exc
    if response.status_code != _HTTP_OK:
        raise _GqlError(f"HTTP {response.status_code}: {response.text[:200]}")
    payload = cast("dict[str, Any]", response.json())
    errors = payload.get("errors")
    if errors:
        raise _GqlError(f"graphql errors: {errors!r}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise _GqlError(f"missing data: {payload!r}")
    return cast("dict[str, Any]", data)


def _nodes(parent: dict[str, Any], field: str) -> list[dict[str, Any]]:
    """Return ``parent[field].nodes`` as a list, or ``[]`` if missing/null."""
    container = cast("dict[str, Any] | None", parent.get(field))
    if not isinstance(container, dict):
        return []
    nodes = cast("list[dict[str, Any]] | None", container.get("nodes"))
    if not isinstance(nodes, list):
        return []
    return nodes


def _extract_cart(payload: dict[str, Any], mutation: str) -> dict[str, Any] | None:
    """Return ``payload[mutation].cart`` as a dict, or ``None`` if absent."""
    outer = cast("dict[str, Any] | None", payload.get(mutation))
    if not isinstance(outer, dict):
        return None
    cart = cast("dict[str, Any] | None", outer.get("cart"))
    if not isinstance(cart, dict):
        return None
    return cart


def _line_id_for(cart: dict[str, Any], variant_gid: str) -> str | None:
    """Return the cart-line id whose ``merchandise.id`` matches ``variant_gid``."""
    for line in _nodes(cart, "lines"):
        merch = cast("dict[str, Any] | None", line.get("merchandise"))
        if isinstance(merch, dict) and merch.get("id") == variant_gid:
            line_id = line.get("id")
            if isinstance(line_id, str):
                return line_id
    return None


# --------------------------------------------------------------------------- #
# Internals — fixture helpers (data file plumbing)
# --------------------------------------------------------------------------- #


def _load_array(path: Path) -> list[dict[str, Any]]:
    """Load a JSON array of objects; tolerate ``[]`` and the file being absent (raises)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise HostingValidationError(
            message=f"{path.as_posix()}: expected JSON array, got {type(raw).__name__}",
        )
    return cast("list[dict[str, Any]]", raw)


def _pick_two_variants(products: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Pick two distinct numeric variant ids from the first products that have any."""
    ids: list[int] = []
    for product in products:
        variants = cast("list[dict[str, Any]] | None", product.get("variants"))
        if not isinstance(variants, list):
            continue
        for variant in variants:
            vid = variant.get("id")
            if isinstance(vid, int) and vid not in ids:
                ids.append(vid)
                if len(ids) == _MIN_DISTINCT_VARIANTS:
                    return ids[0], ids[1]
    return None


def _pick_search_token(products: list[dict[str, Any]]) -> str | None:
    """Return the first 3+-character alphabetic token from any product title."""
    for product in products:
        title = product.get("title")
        if not isinstance(title, str):
            continue
        match = _TITLE_TOKEN_RE.search(title)
        if match is not None:
            return match.group(0)
    return None


def _pick_image_src(products: list[dict[str, Any]]) -> str | None:
    """Return the first product image src that has a recognised image extension."""
    for product in products:
        images = cast("list[dict[str, Any]] | None", product.get("images"))
        if not isinstance(images, list):
            continue
        for image in images:
            src = image.get("src")
            if isinstance(src, str) and src.lower().endswith(
                (".png", ".jpg", ".jpeg", ".webp", ".svg")
            ):
                return src
    return None


def _success(name: str, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": True, "detail": detail}


def _failure(name: str, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": False, "detail": detail}


__all__ = [
    "HostingValidationError",
    "ValidateHostingStep",
    "find_shop_backend_cli",
    "run_hosting_checks",
]
