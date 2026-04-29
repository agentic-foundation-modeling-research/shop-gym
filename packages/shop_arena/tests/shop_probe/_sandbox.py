"""Localhost SandboxShop fixture for axis-A probe tests (T1.7 + T3.3).

A single in-process HTTP server that serves a deterministic
storefront — the minimum HTML needed to exercise every probe in the
``rubric/v1.yaml`` v1 slice (M1 core probes plus the M3 expansion to
~60 probes across all 11 categories per spec §5.3). Routes:

* ``/`` — homepage with sticky header, logo, primary nav (with
  ``/collections/*`` link), header cart link, search trigger, locale +
  currency switcher, hero section, feature grid, testimonial section,
  cookie-consent banner, newsletter popup, chat widget, and a labeled
  footer link group.
* ``/collections/all`` — collection listing with at least two product
  cards (image + title + price), filter sidebar (``<aside>``), sort
  control, pagination, URL-state-sync links, and active-filter chips.
* ``/products/sample`` — PDP with gallery image + thumbnails, ``<h1>``
  title, price, variant selector (radio swatches), quantity spinner,
  enabled add-to-cart button (``<form action="/cart/add" method="post">``),
  accordion description, breadcrumbs, recommendations, lazy-loaded +
  ``srcset`` images, and a lightbox affordance.
* ``/cart`` — cart page with the standard empty / populated states plus a
  promo-code input.
* ``/search`` — search results page that renders product cards on a
  positive query, an empty-state on ``q=zzznoresults``, and echoes the
  query into a heading.
* ``/cart.js`` — JSON endpoint for AJAX cart discovery.
* ``POST /cart/add`` / ``POST /cart/remove`` — cart mutations.
* ``/account/login`` — customer login form (email + password);
  v1.1 auth surface (T7.4).
* ``/account/register`` — customer signup form (email + password + name);
  v1.1 auth surface (T7.4).
* ``/account`` — logged-in customer dashboard;
  v1.1 auth surface (T7.4).
* ``/checkout`` — checkout page (contact + shipping + payment placeholder);
  v1.1 transactional surface (T7.4).

The cart state is held on the server instance and is therefore **isolated
per fixture**. Tests that mutate cart state (cart line-item probes) start
a fresh server, so ordering between probes is irrelevant.

This module performs no I/O at import time; ``SandboxShop.__enter__`` is
the entry point.
"""

from __future__ import annotations

import http.server
import json
import socketserver
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Final
from urllib.parse import parse_qs, urlparse

# --------------------------------------------------------------------------- #
# Page templates
# --------------------------------------------------------------------------- #

# Skip-to-content link is the very first focusable element so a11y probes
# can find it without scrolling.
_SKIP_LINK_HTML: Final[str] = (
    '<a class="skip-to-content-link" href="#main-content">Skip to main content</a>'
)

# Header includes: logo, primary nav with mega menu, search combobox,
# locale + currency switcher, cart link with badge.
_HEADER_HTML: Final[str] = """\
<header class="site-header" style="position: sticky; top: 0; background: #fff; padding: 12px;">
  <a class="site-logo" href="/">FixtureShop</a>
  <nav aria-label="Primary" class="primary-nav">
    <ul class="nav-mega-menu" data-mega-menu>
      <li class="mega-menu__group">
        <button aria-expanded="false" aria-controls="mega-shop">Shop</button>
        <ul id="mega-shop" class="mega-menu__panel">
          <li><h4>Collections</h4></li>
          <li><a href="/collections/all">All</a></li>
          <li><a href="/collections/featured">Featured</a></li>
        </ul>
      </li>
      <li><a href="/collections/all">All</a></li>
      <li><a href="/collections/featured">Featured</a></li>
    </ul>
  </nav>
  <div class="header-search" role="search">
    <button class="header-search-trigger" type="button"
            aria-label="Search" aria-expanded="false"
            aria-controls="predictive-search">Search</button>
    <input
      class="header-search-input"
      type="search"
      name="q"
      role="combobox"
      aria-controls="predictive-search-listbox"
      aria-expanded="false"
      aria-autocomplete="list"
      data-debounce="300"
      placeholder="Search products">
    <ul id="predictive-search-listbox" role="listbox" hidden>
      <li role="option">Sample One</li>
      <li role="option">Sample Two</li>
    </ul>
  </div>
  <div class="header-localization">
    <form class="locale-form" method="post" action="/localization">
      <label class="locale-label">
        Language
        <select class="locale-switcher" name="locale">
          <option value="en">English (EN)</option>
          <option value="fr">Français (FR)</option>
        </select>
      </label>
      <label class="currency-label">
        Currency
        <select class="currency-switcher" name="currency">
          <option value="USD">USD $</option>
          <option value="EUR">EUR €</option>
        </select>
      </label>
      <label class="country-label">
        Country
        <select class="country-selector" name="country">
          <option value="US">United States</option>
          <option value="CA">Canada</option>
          <option value="FR">France</option>
        </select>
      </label>
    </form>
  </div>
  <a class="header-cart-link" href="/cart" aria-label="Cart">
    Cart (<span class="cart-count" data-cart-count>0</span>)
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

# Floating-region markup (cookie banner, newsletter popup, chat widget,
# toast region). Rendered on every page so any probe can find them.
_FLOATING_HTML: Final[str] = """\
<aside class="cookie-consent-banner" data-cookie-consent role="dialog" aria-label="Cookie consent">
  <p>We use cookies to improve your experience.</p>
  <button type="button" class="cookie-accept">Accept</button>
</aside>
<dialog class="newsletter-popup" data-newsletter-popup aria-label="Newsletter signup">
  <form>
    <label>Email <input type="email" name="email"></label>
    <button type="submit">Subscribe</button>
  </form>
</dialog>
<button class="chat-widget-launcher" data-chat-widget aria-label="Open chat" type="button">
  Chat
</button>
<div class="toast-region" role="status" aria-live="polite" data-toast-region></div>
"""

# Tall spacer so a 600px scroll on the homepage actually moves the viewport.
_TALL_SPACER: Final[str] = '<div style="height: 3000px"></div>'

_HOMEPAGE_BODY: Final[str] = """\
<main id="main-content">
  <section class="hero" data-section-type="hero">
    <img src="/static/hero.png" alt="Hero collection" loading="lazy"
         srcset="/static/hero.png 1x, /static/hero@2x.png 2x">
    <h1>Welcome to FixtureShop</h1>
    <p>Shop our collections.</p>
    <a class="hero-cta" href="/collections/all">Shop all</a>
  </section>
  <section class="featured-collection" data-section-type="featured-collection">
    <h2>Featured products</h2>
    <ul class="feature-grid">
      <li class="feature-grid__item">
        <a href="/products/sample">
          <img src="/static/p1.png" alt="Sample One" loading="lazy">
          <h3>Sample One</h3>
        </a>
      </li>
      <li class="feature-grid__item">
        <a href="/products/sample-two">
          <img src="/static/p2.png" alt="Sample Two" loading="lazy">
          <h3>Sample Two</h3>
        </a>
      </li>
    </ul>
  </section>
  <section class="testimonials" data-section-type="testimonials">
    <h2>What customers are saying</h2>
    <blockquote>"Best shop ever." — A Customer</blockquote>
  </section>
</main>
"""

_HOMEPAGE_HTML: Final[str] = f"""\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>FixtureShop</title>
  <style>:focus-visible {{ outline: 2px solid #06f; }}</style>
</head>
<body>
{_SKIP_LINK_HTML}
{_HEADER_HTML}
{_HOMEPAGE_BODY}
{_TALL_SPACER}
{_FOOTER_HTML}
{_FLOATING_HTML}
</body>
</html>
"""

_COLLECTION_BODY: Final[str] = """\
<main id="main-content">
  <nav aria-label="Breadcrumb" class="breadcrumbs">
    <ol>
      <li><a href="/">Home</a></li>
      <li>All</li>
    </ol>
  </nav>
  <ul class="active-filter-chips" aria-label="Active filters">
    <li class="active-filter-chip"><button type="button">T-shirt &times;</button></li>
  </ul>
  <aside class="collection-filters sidebar-filters" aria-label="Filters">
    <h2>Filter</h2>
    <form method="get" action="/collections/all">
      <fieldset>
        <legend>Type</legend>
        <label><input type="checkbox" name="type" value="t-shirt"> T-shirt</label>
        <label><input type="checkbox" name="type" value="hat"> Hat</label>
      </fieldset>
      <button type="submit">Apply</button>
    </form>
    <ul class="filter-links">
      <li><a href="/collections/all?type=t-shirt">T-shirt</a></li>
      <li><a href="/collections/all?type=hat">Hat</a></li>
    </ul>
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
          <img src="/static/p1.png" alt="Sample one" loading="lazy"
               srcset="/static/p1.png 1x, /static/p1@2x.png 2x">
          <h3 class="product-card__title">Sample One</h3>
          <span class="product-card__price">$10.00</span>
        </a>
      </li>
      <li class="product-card">
        <a href="/products/sample-two">
          <img src="/static/p2.png" alt="Sample two" loading="lazy"
               srcset="/static/p2.png 1x, /static/p2@2x.png 2x">
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
"""

_COLLECTION_HTML: Final[str] = f"""\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>All — FixtureShop</title>
  <style>:focus-visible {{ outline: 2px solid #06f; }}</style>
</head>
<body>
{_SKIP_LINK_HTML}
{_HEADER_HTML}
{_COLLECTION_BODY}
{_FOOTER_HTML}
{_FLOATING_HTML}
</body>
</html>
"""

# PDP markup includes: gallery thumbnails, swatches that swap the main
# image (data-swatch-image), variant radio selector, quantity spinner,
# accordion description, breadcrumbs, recommendations, lazy-load +
# srcset, and a lightbox-trigger button.
_PRODUCT_BODY: Final[str] = """\
<main id="main-content">
  <nav aria-label="Breadcrumb" class="breadcrumbs">
    <ol>
      <li><a href="/">Home</a></li>
      <li><a href="/collections/all">All</a></li>
      <li>Sample One</li>
    </ol>
  </nav>
  <div class="product-gallery" role="tablist" aria-label="Product images">
    <img class="product-gallery__main" src="/static/p1.png" alt="Sample One main image"
         loading="lazy"
         srcset="/static/p1.png 1x, /static/p1@2x.png 2x">
    <ul class="product-gallery__thumbnails">
      <li><button role="tab" aria-selected="true" data-thumb-src="/static/p1.png">
        <img src="/static/p1.png" alt="Sample One thumbnail 1" loading="lazy">
      </button></li>
      <li><button role="tab" aria-selected="false" data-thumb-src="/static/p2.png">
        <img src="/static/p2.png" alt="Sample One thumbnail 2" loading="lazy">
      </button></li>
    </ul>
    <button class="product-gallery__zoom" type="button" data-lightbox aria-label="Zoom image">
      Zoom
    </button>
  </div>
  <h1 class="product-title">Sample One</h1>
  <div class="product-price">$10.00</div>
  <form class="product-form" method="post" action="/cart/add">
    <input type="hidden" name="product_id" value="sample">
    <fieldset class="product-variants" data-variant-selector>
      <legend>Color</legend>
      <label class="swatch">
        <input type="radio" name="variant" value="red" checked
               data-swatch-image="/static/p1.png">
        <span>Red</span>
      </label>
      <label class="swatch">
        <input type="radio" name="variant" value="blue"
               data-swatch-image="/static/p2.png">
        <span>Blue</span>
      </label>
    </fieldset>
    <label class="quantity-selector">
      Quantity
      <input
        type="number"
        name="quantity"
        class="quantity-input"
        aria-label="Quantity"
        value="1"
        min="1"
        step="1">
    </label>
    <button type="submit" class="add-to-cart">Add to cart</button>
  </form>
  <details class="product-description product-description-accordion">
    <summary>Description</summary>
    <p>Sample One is a representative test product used by the
    ShopProbe localhost fixture.</p>
  </details>
  <section class="product-recommendations" aria-label="Recommended products">
    <h2>You may also like</h2>
    <ul>
      <li class="product-card">
        <a href="/products/sample-two">
          <img src="/static/p2.png" alt="Sample Two" loading="lazy">
          <h3 class="product-card__title">Sample Two</h3>
          <span class="product-card__price">$20.00</span>
        </a>
      </li>
    </ul>
  </section>
</main>
"""

_PRODUCT_HTML: Final[str] = f"""\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Sample One — FixtureShop</title>
  <style>:focus-visible {{ outline: 2px solid #06f; }}</style>
</head>
<body>
{_SKIP_LINK_HTML}
{_HEADER_HTML}
{_PRODUCT_BODY}
{_FOOTER_HTML}
{_FLOATING_HTML}
</body>
</html>
"""

_CART_EMPTY_BODY: Final[str] = """\
<main id="main-content">
  <h1>Your cart</h1>
  <p class="cart-empty-state">Your cart is currently empty.</p>
  <a href="/collections/all">Continue shopping</a>
  <form class="cart-promo-form" method="post" action="/cart/discount">
    <label>
      Discount code
      <input type="text" name="discount" class="cart-promo-code" placeholder="Enter code">
    </label>
    <button type="submit">Apply</button>
  </form>
</main>
"""

_CART_WITH_ITEM_BODY: Final[str] = """\
<main id="main-content">
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
  <form class="cart-checkout-form" method="get" action="/checkout">
    <button type="submit" name="checkout" class="cart-checkout-button">Checkout</button>
  </form>
  <form class="cart-promo-form" method="post" action="/cart/discount">
    <label>
      Discount code
      <input type="text" name="discount" class="cart-promo-code" placeholder="Enter code">
    </label>
    <button type="submit">Apply</button>
  </form>
</main>
"""

_LOGIN_BODY: Final[str] = """\
<main id="main-content">
  <h1>Log in</h1>
  <form class="customer-login" method="post" action="/account/login">
    <label>
      Email
      <input type="email" name="customer[email]" autocomplete="email" required>
    </label>
    <label>
      Password
      <input type="password" name="customer[password]" autocomplete="current-password" required>
    </label>
    <button type="submit">Sign in</button>
  </form>
  <p><a href="/account/register">Create account</a></p>
</main>
"""

_REGISTER_BODY: Final[str] = """\
<main id="main-content">
  <h1>Create account</h1>
  <form class="customer-register" method="post" action="/account/register">
    <label>
      First name
      <input type="text" name="customer[first_name]" autocomplete="given-name">
    </label>
    <label>
      Email
      <input type="email" name="customer[email]" autocomplete="email" required>
    </label>
    <label>
      Password
      <input type="password" name="customer[password]" autocomplete="new-password" required>
    </label>
    <button type="submit">Create</button>
  </form>
  <p><a href="/account/login">Already have an account?</a></p>
</main>
"""

_ACCOUNT_BODY: Final[str] = """\
<main id="main-content">
  <h1>Your account</h1>
  <section class="account-summary">
    <p>Welcome back, sample customer.</p>
    <ul class="account-nav">
      <li><a href="/account/orders">Order history</a></li>
      <li><a href="/account/addresses">Addresses</a></li>
      <li><a href="/account/logout">Log out</a></li>
    </ul>
  </section>
</main>
"""

_CHECKOUT_BODY: Final[str] = """\
<main id="main-content">
  <h1>Checkout</h1>
  <form class="checkout-form" method="post" action="/checkout">
    <fieldset class="checkout-contact">
      <legend>Contact</legend>
      <label>
        Email
        <input type="email" name="checkout[email]" autocomplete="email" required>
      </label>
    </fieldset>
    <fieldset class="checkout-shipping">
      <legend>Shipping address</legend>
      <label>Full name <input type="text" name="checkout[shipping_address][name]"></label>
      <label>Address <input type="text" name="checkout[shipping_address][address1]"></label>
    </fieldset>
    <fieldset class="checkout-payment">
      <legend>Payment</legend>
      <p class="payment-placeholder">Card details would render here in production.</p>
    </fieldset>
    <button type="submit" class="checkout-submit">Pay now</button>
  </form>
</main>
"""


def _wrap(body: str, *, title: str = "Cart — FixtureShop") -> str:
    return (
        '<!doctype html>\n<html lang="en">\n<head>'
        f'<meta charset="utf-8"><title>{title}</title>'
        "<style>:focus-visible { outline: 2px solid #06f; }</style></head>\n"
        f"<body>\n{_SKIP_LINK_HTML}{_HEADER_HTML}{body}{_FOOTER_HTML}{_FLOATING_HTML}\n"
        "</body></html>"
    )


def _render_search_page(query: str) -> str:
    """Render the search results page for ``query``.

    A query of ``zzznoresults`` (or empty) yields the no-results state;
    any other query echoes back the query and renders product cards so
    the ``search.results_page.renders`` and ``search.query_echo`` probes
    pass.
    """
    safe = query.replace("<", "&lt;").replace(">", "&gt;")
    if not query or query == "zzznoresults":
        body = f"""\
<main id="main-content">
  <h1>Search results for "{safe}"</h1>
  <p class="search-no-results">No results found for "{safe}".</p>
</main>
"""
    else:
        body = f"""\
<main id="main-content">
  <h1>Search results for "{safe}"</h1>
  <p class="search-query-echo">Showing results for "{safe}"</p>
  <ul class="product-grid">
    <li class="product-card">
      <a href="/products/sample">
        <img src="/static/p1.png" alt="Sample One" loading="lazy">
        <h3 class="product-card__title">Sample One</h3>
        <span class="product-card__price">$10.00</span>
      </a>
    </li>
  </ul>
</main>
"""
    return _wrap(body, title=f'Search "{safe}" — FixtureShop')


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

    def do_GET(self) -> None:  # noqa: PLR0911 — flat route dispatcher
        shop: SandboxShop = self.server.shop  # type: ignore[attr-defined]
        parsed = urlparse(self.path)
        path = parsed.path
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
        if path == "/cart.js":
            sid = self._existing_session_id()
            count = shop.cart_count(sid) if sid is not None else 0
            payload = json.dumps({"item_count": count, "items": []}).encode("utf-8")
            self._send(200, payload, content_type="application/json")
            return
        if path == "/search":
            qs = parse_qs(parsed.query)
            query = qs.get("q", [""])[0]
            self._send(200, _render_search_page(query).encode("utf-8"))
            return
        if path == "/account/login":
            self._send(200, _wrap(_LOGIN_BODY, title="Log in — FixtureShop").encode("utf-8"))
            return
        if path == "/account/register":
            self._send(
                200, _wrap(_REGISTER_BODY, title="Create account — FixtureShop").encode("utf-8")
            )
            return
        if path == "/account":
            self._send(
                200, _wrap(_ACCOUNT_BODY, title="Your account — FixtureShop").encode("utf-8")
            )
            return
        if path == "/checkout":
            self._send(200, _wrap(_CHECKOUT_BODY, title="Checkout — FixtureShop").encode("utf-8"))
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
    """Localhost SandboxShop fixture — a storefront in-process.

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

    def cart_count(self, session_id: str) -> int:
        """Return the cart line-item count for ``session_id``."""
        return self._carts.get(session_id, 0)

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
