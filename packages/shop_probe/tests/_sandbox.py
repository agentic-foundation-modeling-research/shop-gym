"""Localhost SandboxShop fixture for axis-A probe tests (T1.7 — spec §7 M1).

A single in-process HTTP server that serves a deterministic Shopify-shaped
storefront — minimum HTML to exercise every M1 ``core`` probe in
``rubric/v1.yaml``. Routes:

* ``/`` — homepage with sticky header, logo, primary nav
  (with ``/collections/*`` link), header cart link, and a labeled footer
  link group.
* ``/collections/all`` — collection listing with at least two product cards
  (image + title + price), filter sidebar, sort control, and pagination.
* ``/products/sample`` — PDP with gallery image, ``<h1>`` title, price, an
  enabled add-to-cart button (``<form action="/cart/add" method="post">``),
  and a description block.
* ``/cart`` — cart page; renders an explicit empty-state message when the
  in-memory cart is empty, or a single line item with quantity editor +
  remove control when populated.
* ``POST /cart/add`` — adds the sample product to the in-memory cart and
  redirects to ``/cart``.

The cart state is held on the server instance and is therefore **isolated
per fixture**. Tests that mutate cart state (cart line-item probes) start a
fresh server, so ordering between probes is irrelevant.

This module performs no I/O at import time; ``SandboxShop.__enter__`` is
the entry point.
"""

from __future__ import annotations

import http.server
import socketserver
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Final

# --------------------------------------------------------------------------- #
# Page templates
# --------------------------------------------------------------------------- #

_HEADER_HTML: Final[str] = """\
<header class="site-header" style="position: sticky; top: 0; background: #fff; padding: 12px;">
  <a class="site-logo" href="/">FixtureShop</a>
  <nav aria-label="Primary">
    <a href="/collections/all">All</a>
    <a href="/collections/featured">Featured</a>
  </nav>
  <a class="header-cart-link" href="/cart" aria-label="Cart">
    Cart (<span data-cart-count>0</span>)
  </a>
</header>
"""

_FOOTER_HTML: Final[str] = """\
<footer class="site-footer">
  <nav class="footer-link-group" aria-label="Customer service">
    <h3>Help</h3>
    <ul>
      <li><a href="/pages/faq">FAQ</a></li>
      <li><a href="/pages/contact">Contact us</a></li>
    </ul>
  </nav>
</footer>
"""

# Tall spacer so a 600px scroll on the homepage actually moves the viewport.
_TALL_SPACER: Final[str] = '<div style="height: 3000px"></div>'

_HOMEPAGE_HTML: Final[str] = f"""\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>FixtureShop</title>
</head>
<body>
{_HEADER_HTML}
<main>
  <h1>Welcome to FixtureShop</h1>
  <p>Shop our collections.</p>
</main>
{_TALL_SPACER}
{_FOOTER_HTML}
</body>
</html>
"""

_COLLECTION_HTML: Final[str] = f"""\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>All — FixtureShop</title>
</head>
<body>
{_HEADER_HTML}
<main>
  <aside class="collection-filters" aria-label="Filters">
    <h2>Filter</h2>
    <form>
      <fieldset>
        <legend>Type</legend>
        <label><input type="checkbox" name="type" value="t-shirt"> T-shirt</label>
        <label><input type="checkbox" name="type" value="hat"> Hat</label>
      </fieldset>
    </form>
  </aside>
  <section class="collection-listing">
    <div class="collection-toolbar">
      <label for="sort-by">Sort by</label>
      <select id="sort-by" class="collection-sort" name="sort_by">
        <option value="featured">Featured</option>
        <option value="price-asc">Price, low to high</option>
        <option value="price-desc">Price, high to low</option>
      </select>
    </div>
    <ul class="product-grid">
      <li class="product-card">
        <a href="/products/sample">
          <img src="/static/p1.png" alt="Sample one">
          <h3 class="product-card__title">Sample One</h3>
          <span class="product-card__price">$10.00</span>
        </a>
      </li>
      <li class="product-card">
        <a href="/products/sample-two">
          <img src="/static/p2.png" alt="Sample two">
          <h3 class="product-card__title">Sample Two</h3>
          <span class="product-card__price">$20.00</span>
        </a>
      </li>
    </ul>
    <nav class="pagination" aria-label="Pagination">
      <a href="/collections/all?page=2" rel="next">Next page</a>
    </nav>
  </section>
</main>
{_FOOTER_HTML}
</body>
</html>
"""

_PRODUCT_HTML: Final[str] = f"""\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Sample One — FixtureShop</title>
</head>
<body>
{_HEADER_HTML}
<main>
  <div class="product-gallery">
    <img class="product-gallery__main" src="/static/p1.png" alt="Sample One main image">
  </div>
  <h1 class="product-title">Sample One</h1>
  <div class="product-price">$10.00</div>
  <form class="product-form" method="post" action="/cart/add">
    <input type="hidden" name="product_id" value="sample">
    <button type="submit" class="add-to-cart">Add to cart</button>
  </form>
  <section class="product-description">
    <p>Sample One is a representative test product used by the
    ShopProbe localhost fixture.</p>
  </section>
</main>
{_FOOTER_HTML}
</body>
</html>
"""

_CART_EMPTY_BODY: Final[str] = """\
<main>
  <h1>Your cart</h1>
  <p class="cart-empty-state">Your cart is currently empty.</p>
  <a href="/collections/all">Continue shopping</a>
</main>
"""

_CART_WITH_ITEM_BODY: Final[str] = """\
<main>
  <h1>Your cart</h1>
  <ul class="cart-items">
    <li class="cart-item" data-product-id="sample">
      <span class="cart-item__title">Sample One</span>
      <span class="cart-item__price">$10.00</span>
      <label>
        Quantity
        <input
          type="number"
          name="quantity"
          class="cart-item__qty-editor"
          aria-label="Quantity"
          value="1"
          min="1">
      </label>
      <form method="post" action="/cart/remove">
        <input type="hidden" name="product_id" value="sample">
        <button
          type="submit"
          class="cart-item__remove"
          aria-label="Remove Sample One">Remove</button>
      </form>
    </li>
  </ul>
</main>
"""


def _wrap(body: str, *, title: str = "Cart — FixtureShop") -> str:
    return (
        '<!doctype html>\n<html lang="en">\n<head>'
        f'<meta charset="utf-8"><title>{title}</title></head>\n'
        f"<body>\n{_HEADER_HTML}{body}{_FOOTER_HTML}\n</body></html>"
    )


# --------------------------------------------------------------------------- #
# HTTP server
# --------------------------------------------------------------------------- #

_SESSION_COOKIE: Final[str] = "shop_probe_session"
"""Cookie name carrying the per-context cart session id."""


class _Handler(http.server.BaseHTTPRequestHandler):
    """Handler bound to the parent :class:`SandboxShop` via ``server.shop``.

    Cart state is keyed by an HTTP cookie so each isolated browser context
    (one per probe call in :class:`shop_probe.probes._runner.ProbeRunner`)
    sees its own cart, mirroring how real Shopify storefronts scope cart
    state by session id.
    """

    def _existing_session_id(self) -> str | None:
        """Return the session id from the request cookie, or ``None``."""
        cookie_header = self.headers.get("Cookie", "") or ""
        for part in cookie_header.split(";"):
            key, _, value = part.strip().partition("=")
            if key == _SESSION_COOKIE and value:
                return value
        return None

    def _ensure_session_id(self) -> tuple[str, bool]:
        """Return ``(session_id, is_new)``; mints a fresh id when missing."""
        existing = self._existing_session_id()
        if existing is not None:
            return existing, False
        return uuid.uuid4().hex, True

    def _send(
        self,
        status: int,
        body: bytes,
        *,
        content_type: str = "text/html; charset=utf-8",
        set_session: str | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if set_session is not None:
            self.send_header(
                "Set-Cookie",
                f"{_SESSION_COOKIE}={set_session}; Path=/; HttpOnly",
            )
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str, *, set_session: str | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        if set_session is not None:
            self.send_header(
                "Set-Cookie",
                f"{_SESSION_COOKIE}={set_session}; Path=/; HttpOnly",
            )
        self.end_headers()

    def do_GET(self) -> None:
        shop: SandboxShop = self.server.shop  # type: ignore[attr-defined]
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, _HOMEPAGE_HTML.encode("utf-8"))
            return
        if path in {"/collections/all", "/collections/featured"}:
            self._send(200, _COLLECTION_HTML.encode("utf-8"))
            return
        if path in {"/products/sample", "/products/sample-two"}:
            self._send(200, _PRODUCT_HTML.encode("utf-8"))
            return
        if path == "/cart":
            sid = self._existing_session_id()
            populated = sid is not None and shop.cart_has_item(sid)
            body = _CART_WITH_ITEM_BODY if populated else _CART_EMPTY_BODY
            self._send(200, _wrap(body).encode("utf-8"))
            return
        if path.startswith("/static/"):
            # Tiny 1x1 transparent PNG so <img> requests resolve.
            self._send(200, _PNG_PIXEL, content_type="image/png")
            return
        self._send(404, b"<h1>Not Found</h1>")

    def do_POST(self) -> None:
        shop: SandboxShop = self.server.shop  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length:
            self.rfile.read(length)  # discard form body; cart is single-product fixture
        path = self.path.split("?", 1)[0]
        if path == "/cart/add":
            sid, is_new = self._ensure_session_id()
            shop.add_to_cart(sid)
            self._redirect("/cart", set_session=sid if is_new else None)
            return
        if path == "/cart/remove":
            sid = self._existing_session_id()
            if sid is not None:
                shop.clear_cart(sid)
            self._redirect("/cart")
            return
        self._send(404, b"<h1>Not Found</h1>")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — base API
        # Quiet pytest output.
        del format, args


# 1x1 transparent PNG (67 bytes, base-64 decoded inline).
_PNG_PIXEL: Final[bytes] = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _Server(socketserver.TCPServer):
    """Subclass that exposes the parent :class:`SandboxShop` to handlers."""

    allow_reuse_address = True

    def __init__(self, addr: tuple[str, int], shop: SandboxShop) -> None:
        super().__init__(addr, _Handler)
        self.shop = shop


class SandboxShop:
    """Localhost SandboxShop fixture — a Shopify-shaped storefront in-process.

    Use as a context manager. ``base_url`` is yielded once the server is
    bound to an ephemeral port and serving requests on a daemon thread.

    Cart state is held **per HTTP session** (keyed by a cookie set on the
    first ``POST /cart/add``). Each isolated Playwright browser context
    therefore sees its own cart — matching real Shopify session scoping.
    """

    def __init__(self) -> None:
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._carts: dict[str, int] = {}

    # --- cart state used by the handler --------------------------------- #

    def cart_has_item(self, session_id: str) -> bool:
        """Return whether the cart for ``session_id`` has at least one line item."""
        return self._carts.get(session_id, 0) > 0

    def add_to_cart(self, session_id: str) -> None:
        """Increment the cart line-item counter for ``session_id`` (POST /cart/add)."""
        self._carts[session_id] = self._carts.get(session_id, 0) + 1

    def clear_cart(self, session_id: str) -> None:
        """Empty the cart for ``session_id`` (POST /cart/remove)."""
        self._carts.pop(session_id, None)

    # --- lifecycle ------------------------------------------------------- #

    def __enter__(self) -> str:
        server = _Server(("127.0.0.1", 0), self)
        port: int = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._server = server
        self._thread = thread
        return f"http://127.0.0.1:{port}"

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del exc_type, exc, tb
        server, self._server = self._server, None
        thread, self._thread = self._thread, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2.0)


@contextmanager
def sandbox_shop() -> Iterator[str]:
    """Convenience: ``with sandbox_shop() as base_url`` for one-shot tests."""
    with SandboxShop() as base_url:
        yield base_url
