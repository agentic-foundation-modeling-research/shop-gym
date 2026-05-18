"""5-bucket page discovery + ``pages.json`` writer/reuse (spec §5.2, M1).

EnvEval visits exactly five buckets per shop: ``homepage``, ``collection``,
``product``, ``policy``, and ``cart_and_search``. Discovery is fully
browser-driven and **not** LLM-driven: it walks the storefront with
Playwright, scans hrefs in DOM order, and applies the deterministic
selection rules from spec §5.2.

Top-level helpers:

* :func:`normalize_base_url` — scheme + host + ``"/"`` per spec §5.2.
* :func:`discover_pages` — drive the discovery flow against a live
  :class:`~shop_arena.env_eval.env.EnvEvalSession` and return a
  :class:`PagesDoc`.
* :func:`load_or_discover` — read an existing ``pages.json`` from a run
  directory if present (spec §5.7 reuse), otherwise run discovery and
  persist it. Honours ``rediscover=True`` by ignoring any cached file.
* :func:`write_pages_json` / :func:`read_pages_json` — JSON
  serialisation helpers that round-trip through the closed pydantic v2
  schema.

The richer per-bucket fallback chain, raw-source recording, and the full
edge-case matrix (404 handling, query/fragment stripping nuances, link-
text nav labels, …) are implemented here. Soft-404 detection is
deliberately out-of-scope for v0.1 (spec §5.2).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Final, Literal, Protocol
from urllib.parse import quote_plus, urljoin, urlsplit

import playwright.sync_api
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shop_arena.env_eval.env import EnvEvalSession
from shop_arena.env_eval.errors import PageDiscoveryError, ShopUnreachableError

__all__ = [
    "PAGES_JSON_FILENAME",
    "CartAndSearch",
    "DiscoveryBrowser",
    "PageNotFound",
    "PageOk",
    "PagesDoc",
    "SearchPageOk",
    "SelectionRule",
    "discover_pages",
    "load_or_discover",
    "normalize_base_url",
    "read_pages_json",
    "write_pages_json",
]

logger = logging.getLogger(__name__)

#: Filename written inside ``run_dir`` (spec §5.6).
PAGES_JSON_FILENAME: Final[str] = "pages.json"

#: HTTP status floor that EnvEval treats as "bucket unavailable".  4xx and
#: 5xx are demoted to ``not_found`` for non-homepage buckets; the homepage
#: itself escalates to :class:`ShopUnreachableError`.
_HTTP_ERROR_FLOOR: Final[int] = 400

#: Sentinel status returned by :class:`_SessionDiscoveryBrowser.goto` when
#: Playwright raises a navigation error (e.g. ``net::ERR_ABORTED``,
#: ``net::ERR_NAME_NOT_RESOLVED``, ``TimeoutError``). Picked above
#: ``_HTTP_ERROR_FLOOR`` so existing per-bucket checks demote the bucket to
#: ``not_found`` and the homepage check still escalates to
#: :class:`ShopUnreachableError`.
_NAV_ERROR_STATUS: Final[int] = 599

#: Generic commerce words dropped from derived search queries (spec §5.2).
#: Kept lowercase so token matching is straightforward; extended slightly
#: past the spec's example list (``shop|all|new|sale|collection``) with the
#: obvious plurals and ``home`` / ``menu`` to keep nav-derived queries
#: from being trivially generic.
_QUERY_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "shop",
        "shops",
        "all",
        "new",
        "sale",
        "collection",
        "collections",
        "product",
        "products",
        "home",
        "menu",
    },
)

#: Maximum tokens kept in the derived search query (spec §5.2 "1-3").
_QUERY_TOKEN_LIMIT: Final[int] = 3

#: Token splitter for derived queries: keep ``[A-Za-z0-9]+`` runs and drop
#: punctuation/whitespace.  Lowercased before deduplication.
_QUERY_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9]+")

#: Conventional policy URL EnvEval tries first (spec §5.2 step 4).
_POLICY_CONVENTION_PATH: Final[str] = "/policies/privacy-policy"

#: Cart URL — same on every Shopify-shaped storefront.
_CART_PATH: Final[str] = "/cart"


# ---------------------------------------------------------------------------
# Closed schema for ``pages.json``.
# ---------------------------------------------------------------------------

#: Closed selection-rule enum.  Matches
#: :data:`shop_arena.env_eval.schema.metrics.SelectedBy` so rules round-trip into
#: ``metrics.json`` without translation.
SelectionRule = Literal[
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


class _Closed(BaseModel):
    """Base model: frozen + ``extra="forbid"`` so ``pages.json`` drift fails loud."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PageOk(_Closed):
    """A successfully discovered URL bucket.

    Attributes:
        status: Discriminator literal — always ``"ok"``.
        url: Concrete URL EnvEval will visit.  Stored as a host-relative
            path (e.g. ``"/collections/men"``) for in-domain pages and as
            an absolute URL for the rare cross-host fallback.
        canonical_url: Templated id used as the transition graph node id
            (e.g. ``"/collections/<*>"``).  ``None`` when the URL is its
            own canonical id (homepage, ``/cart``).
        selected_by: Rule that picked this URL.
    """

    status: Literal["ok"] = "ok"
    url: str = Field(min_length=1)
    canonical_url: str | None = None
    selected_by: SelectionRule


class PageNotFound(_Closed):
    """An unavailable bucket.

    Attributes:
        status: Discriminator literal — always ``"not_found"``.
        reason: Short, machine-readable reason
            (e.g. ``"no_product_link"``, ``"no_search_query"``).
    """

    status: Literal["not_found"] = "not_found"
    reason: str = Field(min_length=1)


class SearchPageOk(_Closed):
    """An ``ok`` ``/search?q=...`` entry.

    Attributes:
        status: Discriminator literal — always ``"ok"``.
        url: ``/search?q=<query>`` URL with the query value preserved.
        query: The deterministic, lowercased query (spec §5.2).
        selected_by: Source rule that produced ``query``.
        raw_source: Untrimmed source text the rule pulled the query from
            (e.g. the product ``<h1>``).  Optional so an early discovery
            pass can leave it unset.
    """

    status: Literal["ok"] = "ok"
    url: str = Field(min_length=1)
    query: str = Field(min_length=1)
    selected_by: SelectionRule
    raw_source: str | None = None


class CartAndSearch(_Closed):
    """The merged ``cart_and_search`` bucket (spec §5.2)."""

    cart: PageOk | PageNotFound
    search: SearchPageOk | PageNotFound


class PagesDoc(_Closed):
    """The full ``pages.json`` document.

    Attributes:
        base_url: Normalised storefront URL (scheme + host + ``"/"``).
        homepage: Always ``ok`` (the run aborts with
            :class:`shop_arena.env_eval.errors.ShopUnreachableError`
            before we get this far otherwise).
        collection / product / policy: ``ok`` or ``not_found`` per §5.2.
        cart_and_search: Pair of ``/cart`` + ``/search`` entries.
    """

    base_url: str = Field(min_length=1)
    homepage: PageOk
    collection: PageOk | PageNotFound
    product: PageOk | PageNotFound
    policy: PageOk | PageNotFound
    cart_and_search: CartAndSearch


# ---------------------------------------------------------------------------
# Discovery driver protocol — production wraps a real BrowserGym session,
# tests inject a fake.
# ---------------------------------------------------------------------------


class DiscoveryBrowser(Protocol):
    """Minimal browser surface :func:`discover_pages` consumes.

    Wrapping the session through this protocol keeps the discovery logic
    testable without launching Playwright: tests pass a hand-rolled fake
    that returns canned hrefs/text/status values.
    """

    def goto(self, url: str) -> int | None:
        """Navigate to ``url`` and return the HTTP status (or ``None`` if unknown)."""
        ...

    def hrefs(self, selector: str = "a[href]") -> list[str]:
        """Return absolute hrefs for ``selector`` matches in DOM order."""
        ...

    def link_texts(self, selector: str) -> list[tuple[str, str]]:
        """Return ``(href, text)`` pairs for ``selector`` matches in DOM order.

        ``text`` is the link's trimmed visible text content (or its
        ``aria-label`` when no text is present); empty when neither is
        available. Hrefs are absolute, mirroring :meth:`hrefs`.
        """
        ...

    def text(self, selector: str) -> str | None:
        """Return trimmed text content of the first ``selector`` match, or ``None``."""
        ...


class _SessionDiscoveryBrowser:
    """:class:`DiscoveryBrowser` backed by an :class:`EnvEvalSession`."""

    def __init__(self, session: EnvEvalSession) -> None:
        self._session = session

    def goto(self, url: str) -> int | None:
        try:
            response = self._session.goto(url)
        except playwright.sync_api.Error as exc:
            # ``net::ERR_ABORTED`` (download responses, mid-load redirects,
            # anti-bot resets), ``ERR_NAME_NOT_RESOLVED``, navigation
            # timeouts, etc. surface as ``playwright.sync_api.Error``.
            # Demote to a non-2xx sentinel so the homepage check escalates
            # to :class:`ShopUnreachableError` and per-bucket discovery
            # marks the bucket as ``not_found`` instead of crashing.
            logger.warning("navigation to %s failed: %s", url, exc)
            return _NAV_ERROR_STATUS
        # ``Response`` is ``None`` for same-document navigations; the
        # caller already saw a 2xx for the base URL in that case.
        return None if response is None else int(response.status)

    def hrefs(self, selector: str = "a[href]") -> list[str]:
        page = self._session.page
        # ``Array.from(..., a => a.href)`` returns absolute URLs even when
        # the underlying ``href`` attribute is relative, so the caller does
        # not need a separate ``urljoin`` step.
        result: Any = page.evaluate(
            "(sel) => Array.from(document.querySelectorAll(sel), (a) => a.href)",
            selector,
        )
        if not isinstance(result, list):
            return []
        out: list[str] = []
        for item in result:  # pyright: ignore[reportUnknownVariableType]
            if isinstance(item, str):
                out.append(item)
        return out

    def link_texts(self, selector: str) -> list[tuple[str, str]]:
        page = self._session.page
        result: Any = page.evaluate(
            "(sel) => Array.from(document.querySelectorAll(sel), (a) => ["
            "a.href, ((a.textContent || a.getAttribute('aria-label') || '').trim())"
            "])",
            selector,
        )
        if not isinstance(result, list):
            return []
        out: list[tuple[str, str]] = []
        for item in result:  # pyright: ignore[reportUnknownVariableType]
            if not isinstance(item, list) or len(item) != _LINK_TEXT_PAIR_LEN:  # pyright: ignore[reportUnknownArgumentType]
                continue
            href = item[0]  # pyright: ignore[reportUnknownVariableType]
            text = item[1]  # pyright: ignore[reportUnknownVariableType]
            if isinstance(href, str) and isinstance(text, str):
                out.append((href, text))
        return out

    def text(self, selector: str) -> str | None:
        page = self._session.page
        try:
            value = page.locator(selector).first.text_content()
        except Exception:
            return None
        if value is None:
            return None
        text = value.strip()
        return text or None


#: Tuple length returned by :meth:`DiscoveryBrowser.link_texts` items.
_LINK_TEXT_PAIR_LEN: Final[int] = 2


# ---------------------------------------------------------------------------
# URL helpers.
# ---------------------------------------------------------------------------


def normalize_base_url(url: str) -> str:
    """Return the storefront URL normalised to ``scheme://host/`` (spec §5.2).

    Args:
        url: User-supplied storefront URL.

    Returns:
        ``scheme + "://" + host + "/"`` with the original casing preserved
        for the host (Playwright's URL handling is case-insensitive on
        host but the raw form is kept for human readability).

    Raises:
        ValueError: ``url`` lacks a scheme or host.
    """
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"invalid storefront URL: {url!r}")
    return f"{parts.scheme}://{parts.netloc}/"


_DISALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"mailto", "tel", "javascript"})


def _to_relative(href: str, base_url: str) -> str | None:
    """Return ``href`` as a host-relative path if it is in-domain, else ``None``.

    Same-host filtering (spec §5.2) is applied: cross-host hrefs return
    ``None``. Non-HTTP schemes (``mailto:``, ``tel:``, ``javascript:``)
    are rejected explicitly so they never enter the selection ladder.
    Query and fragment are stripped from the returned path: spec §5.2
    requires query/fragment-free canonical ids, and the only sampled
    URL that legitimately carries a query (``/search?q=…``) is built
    by :func:`_discover_cart_and_search` — it is never selected from a
    storefront ``href``.
    """
    abs_url = urljoin(base_url, href)
    parts = urlsplit(abs_url)
    if parts.scheme.lower() in _DISALLOWED_SCHEMES:
        return None
    base_parts = urlsplit(base_url)
    if parts.netloc != base_parts.netloc:
        return None
    return parts.path or "/"


def _canonicalize_path(path: str) -> str:
    """Collapse ``/products/<slug>`` etc. to canonical templates (spec §5.2)."""
    bare = path.split("?", 1)[0].split("#", 1)[0]
    for prefix in ("/products/", "/collections/", "/policies/"):
        if bare.startswith(prefix) and len(bare) > len(prefix):
            return prefix + "<*>"
    return bare


def _slug_from_path(path: str, prefix: str) -> str | None:
    """Extract ``<slug>`` from ``/<prefix>/<slug>(/...)`` paths."""
    bare = path.split("?", 1)[0].split("#", 1)[0]
    if not bare.startswith(prefix):
        return None
    rest = bare[len(prefix) :]
    slug = rest.split("/", 1)[0]
    return slug or None


# ---------------------------------------------------------------------------
# Search-query inference (spec §5.2 candidate ladder).
# ---------------------------------------------------------------------------


def _tokenize_query(text: str) -> list[str]:
    """Lowercase + strip stopwords + cap at :data:`_QUERY_TOKEN_LIMIT`."""
    tokens = [tok.lower() for tok in _QUERY_TOKEN_RE.findall(text)]
    meaningful = [tok for tok in tokens if tok and tok not in _QUERY_STOPWORDS]
    return meaningful[:_QUERY_TOKEN_LIMIT]


def _query_from_text(text: str | None) -> str | None:
    """Build a normalised query from free-form ``text``."""
    if not text:
        return None
    tokens = _tokenize_query(text)
    if not tokens:
        return None
    return " ".join(tokens)


def _query_from_slug(slug: str | None) -> str | None:
    """Build a normalised query from a URL slug like ``"linen-shirt"``."""
    if not slug:
        return None
    return _query_from_text(slug.replace("-", " ").replace("_", " "))


def _infer_search_query(
    browser: DiscoveryBrowser,
    base_url: str,
    *,
    product: PageOk | PageNotFound,
    collection: PageOk | PageNotFound,
    home_hrefs: list[str],
) -> tuple[str, SelectionRule, str] | None:
    """Walk the spec §5.2 query candidate ladder.

    Returns ``(query, selected_by, raw_source)`` or ``None`` when no
    candidate produces a non-empty query.

    The current page on entry is unspecified; callers need not park the
    browser anywhere in particular because this helper navigates each
    candidate explicitly.
    """
    # 1) product title (visit the product page if found).
    if isinstance(product, PageOk):
        status = browser.goto(urljoin(base_url, product.url))
        if status is None or status < _HTTP_ERROR_FLOOR:
            title = browser.text("h1") or browser.text("[property='og:title']")
            query = _query_from_text(title)
            if query:
                return query, "product_title", title or ""
        # 2) product slug — works even when the title fetch failed.
        slug = _slug_from_path(product.url, "/products/")
        query = _query_from_slug(slug)
        if query:
            return query, "product_slug", slug or ""

    # 3) collection title / slug (visit the collection page if found).
    if isinstance(collection, PageOk):
        status = browser.goto(urljoin(base_url, collection.url))
        if status is None or status < _HTTP_ERROR_FLOOR:
            title = browser.text("h1")
            query = _query_from_text(title)
            if query:
                return query, "collection_title", title or ""
        slug = _slug_from_path(collection.url, "/collections/")
        query = _query_from_slug(slug)
        if query:
            return query, "collection_slug", slug or ""

    # 4) first non-generic category/navigation label on the homepage.
    return _nav_label_query(browser, base_url)


def _nav_label_query(
    browser: DiscoveryBrowser,
    base_url: str,
) -> tuple[str, SelectionRule, str] | None:
    """Spec §5.2 step 4: derive a query from the first usable nav link.

    Prefers the visible link text (or aria-label) so ``raw_source`` is
    the actual label; falls back to the URL slug only when no text is
    available.  Returns ``None`` when no link produces a non-empty query.
    """
    browser.goto(base_url)
    for href, text in browser.link_texts("a[href]"):
        rel = _to_relative(href, base_url)
        if rel is None:
            continue
        query = _query_from_text(text)
        if query:
            return query, "nav_label", text
        tail = rel.rstrip("/").rsplit("/", 1)[-1]
        query = _query_from_slug(tail)
        if query:
            return query, "nav_label", tail
    return None


# ---------------------------------------------------------------------------
# Per-bucket discovery.
# ---------------------------------------------------------------------------


def _discover_collection(
    browser: DiscoveryBrowser,
    base_url: str,
    home_hrefs: list[str],
) -> tuple[PageOk | PageNotFound, list[str]]:
    """Pick the first ``/collections/<slug>`` href; fall back to ``/collections/all``.

    Returns the bucket plus the collection-page hrefs (used by
    :func:`_discover_product`).  When the bucket is ``not_found`` the
    href list is empty.
    """
    rules: list[tuple[str, SelectionRule]] = []
    for href in home_hrefs:
        rel = _to_relative(href, base_url)
        if rel is None:
            continue
        path = rel.split("?", 1)[0]
        if path.startswith("/collections/") and path != "/collections/all":
            rules.append((rel, "first_href"))
            break

    if not rules:
        rules.append(("/collections/all", "fallback_path"))

    chosen_url, selected_by = rules[0]
    status = browser.goto(urljoin(base_url, chosen_url))
    if status is not None and status >= _HTTP_ERROR_FLOOR:
        # Even the fallback failed; record as ``not_found`` rather than
        # raising — only the homepage failure is fatal in v0.1.
        return (
            PageNotFound(reason=f"collection_http_{status}"),
            [],
        )
    bucket = PageOk(
        url=chosen_url,
        canonical_url=_canonicalize_path(chosen_url),
        selected_by=selected_by,
    )
    return bucket, browser.hrefs()


def _discover_product(
    browser: DiscoveryBrowser,
    base_url: str,
    coll_hrefs: list[str],
    home_hrefs: list[str],
) -> PageOk | PageNotFound:
    """Pick the first ``/products/<slug>`` href; collection first, then homepage."""
    for source in (coll_hrefs, home_hrefs):
        for href in source:
            rel = _to_relative(href, base_url)
            if rel is None:
                continue
            path = rel.split("?", 1)[0]
            if path.startswith("/products/"):
                status = browser.goto(urljoin(base_url, rel))
                if status is not None and status >= _HTTP_ERROR_FLOOR:
                    continue
                return PageOk(
                    url=rel,
                    canonical_url=_canonicalize_path(rel),
                    selected_by="first_href",
                )
    return PageNotFound(reason="no_product_link")


def _discover_policy(
    browser: DiscoveryBrowser,
    base_url: str,
    home_hrefs: list[str],
) -> PageOk | PageNotFound:
    """Try ``/policies/privacy-policy``; fall back to footer policy hrefs."""
    convention_status = browser.goto(urljoin(base_url, _POLICY_CONVENTION_PATH))
    if convention_status is None or convention_status < _HTTP_ERROR_FLOOR:
        return PageOk(
            url=_POLICY_CONVENTION_PATH,
            canonical_url=_canonicalize_path(_POLICY_CONVENTION_PATH),
            selected_by="convention",
        )

    # Fall back to any /policies/<*> href in the homepage footer; we
    # already have the homepage hrefs cached, so we don't need to
    # navigate back for this M1 pass.  The dedicated footer-scoped
    # selector is left for the edge-case task.
    for href in home_hrefs:
        rel = _to_relative(href, base_url)
        if rel is None:
            continue
        path = rel.split("?", 1)[0]
        if path.startswith("/policies/"):
            status = browser.goto(urljoin(base_url, rel))
            if status is not None and status >= _HTTP_ERROR_FLOOR:
                continue
            return PageOk(
                url=rel,
                canonical_url=_canonicalize_path(rel),
                selected_by="first_href",
            )
    return PageNotFound(reason="no_policy_link")


def _discover_cart_and_search(
    browser: DiscoveryBrowser,
    base_url: str,
    *,
    product: PageOk | PageNotFound,
    collection: PageOk | PageNotFound,
    home_hrefs: list[str],
) -> CartAndSearch:
    """Visit ``/cart`` then derive ``/search?q=<query>``."""
    cart_status = browser.goto(urljoin(base_url, _CART_PATH))
    cart: PageOk | PageNotFound
    if cart_status is not None and cart_status >= _HTTP_ERROR_FLOOR:
        cart = PageNotFound(reason=f"cart_http_{cart_status}")
    else:
        cart = PageOk(url=_CART_PATH, canonical_url=None, selected_by="convention")

    inferred = _infer_search_query(
        browser,
        base_url,
        product=product,
        collection=collection,
        home_hrefs=home_hrefs,
    )
    search: SearchPageOk | PageNotFound
    if inferred is None:
        search = PageNotFound(reason="no_search_query")
    else:
        query, selected_by, raw_source = inferred
        search_url = f"/search?q={quote_plus(query)}"
        # Visit so downstream observation/action layers reuse the
        # browser state; ignore navigation errors here (search may
        # legitimately 200 even with no results).
        browser.goto(urljoin(base_url, search_url))
        search = SearchPageOk(
            url=search_url,
            query=query,
            selected_by=selected_by,
            raw_source=raw_source or None,
        )

    return CartAndSearch(cart=cart, search=search)


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def discover_pages(
    session: EnvEvalSession,
    base_url: str,
    *,
    browser: DiscoveryBrowser | None = None,
) -> PagesDoc:
    """Drive the spec §5.2 discovery flow and return a :class:`PagesDoc`.

    Args:
        session: Live BrowserGym session (held by ``evaluate()``).
        base_url: Storefront URL.  Will be normalised internally.
        browser: Discovery driver override.  Defaults to
            :class:`_SessionDiscoveryBrowser` wrapping ``session``;
            tests pass a stub.

    Returns:
        Closed :class:`PagesDoc` recording the URL + selection rule for
        each bucket.

    Raises:
        ShopUnreachableError: Homepage navigation failed (spec §5.2 step 1).
        PageDiscoveryError: A non-recoverable discovery failure surfaced
            (reserved; the per-bucket misses use ``not_found`` instead).
    """
    base = normalize_base_url(base_url)
    driver = browser if browser is not None else _SessionDiscoveryBrowser(session)

    home_status = driver.goto(base)
    if home_status is not None and home_status >= _HTTP_ERROR_FLOOR:
        raise ShopUnreachableError(
            f"homepage navigation to {base!r} returned HTTP {home_status}",
        )
    home_hrefs = driver.hrefs()
    if not home_hrefs:
        # An empty axtree is suspicious but not fatal: page selection can
        # still produce ``not_found`` for every downstream bucket.  Log so
        # operators see it and move on; keep this branch open for the
        # edge-case task to harden if needed.
        logger.info("homepage at %s exposed no <a> elements", base)

    homepage = PageOk(url="/", canonical_url=None, selected_by="input")

    collection, coll_hrefs = _discover_collection(driver, base, home_hrefs)
    product = _discover_product(driver, base, coll_hrefs, home_hrefs)
    policy = _discover_policy(driver, base, home_hrefs)
    cart_and_search = _discover_cart_and_search(
        driver,
        base,
        product=product,
        collection=collection,
        home_hrefs=home_hrefs,
    )

    return PagesDoc(
        base_url=base,
        homepage=homepage,
        collection=collection,
        product=product,
        policy=policy,
        cart_and_search=cart_and_search,
    )


def write_pages_json(doc: PagesDoc, run_dir: Path | str) -> Path:
    """Serialise ``doc`` to ``<run_dir>/pages.json``.

    The ``run_dir`` is created if it does not already exist; output is
    deterministic JSON (two-space indent, trailing newline) so
    byte-stable reuse checks in M6 are straightforward.
    """
    target = Path(run_dir) / PAGES_JSON_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = doc.model_dump(mode="json")
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def read_pages_json(run_dir: Path | str) -> PagesDoc:
    """Load ``<run_dir>/pages.json`` and validate against :class:`PagesDoc`.

    Raises:
        PageDiscoveryError: The file is missing, malformed, or violates
            the closed schema.  Wraps the underlying error so callers
            depend only on the EnvEval failure vocabulary.
    """
    target = Path(run_dir) / PAGES_JSON_FILENAME
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise PageDiscoveryError(f"cannot read {target}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PageDiscoveryError(f"{target} is not valid JSON: {exc}") from exc
    try:
        return PagesDoc.model_validate(payload)
    except ValidationError as exc:
        raise PageDiscoveryError(f"{target} failed schema validation: {exc}") from exc


def load_or_discover(
    session: EnvEvalSession,
    base_url: str,
    run_dir: Path | str,
    *,
    rediscover: bool = False,
    browser: DiscoveryBrowser | None = None,
) -> PagesDoc:
    """Return ``pages.json`` for ``run_dir``, running discovery if needed.

    Spec §5.7 reuse: an existing ``pages.json`` is read verbatim and
    discovery is skipped unless ``rediscover=True``.  ``rediscover``
    only invalidates ``pages.json`` itself; downstream artifacts are
    *not* cascade-deleted (callers should use a fresh ``out_dir`` if
    they need that).
    """
    target_dir = Path(run_dir)
    cached = target_dir / PAGES_JSON_FILENAME
    if cached.exists() and not rediscover:
        return read_pages_json(target_dir)

    doc = discover_pages(session, base_url, browser=browser)
    write_pages_json(doc, target_dir)
    return doc
