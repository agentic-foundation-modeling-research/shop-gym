"""BrowserGym-backed accessibility-tree link crawler.

This module crawls only links that are exposed through BrowserGym's merged
accessibility tree. It intentionally does not depend on ``shop_arena`` or the
ShopGuru evaluation task wrappers; callers can use it as a standalone utility
from ``shop_guru.bgym_task``.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import playwright.sync_api
from browsergym.core.observation import (  # pyright: ignore[reportPrivateUsage]
    MarkingError,
    _post_extract,
    _pre_extract,
    extract_merged_axtree,
)
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
Axtree = Mapping[str, object]
Node = Mapping[str, object]
TraversalMode = Literal["bfs", "dfs"]

_HTTP_SCHEMES = frozenset({"http", "https"})
_HTTP_DEFAULT_PORT = 80
_HTTPS_DEFAULT_PORT = 443
_AXTREE_EXTRACT_MAX_ATTEMPTS = 3
_AXTREE_EXTRACT_FINAL_ATTEMPT = _AXTREE_EXTRACT_MAX_ATTEMPTS - 1
_DEFAULT_EXCLUDED_EXTENSIONS = frozenset(
    {
        ".avi",
        ".css",
        ".doc",
        ".docx",
        ".gif",
        ".gz",
        ".jpeg",
        ".jpg",
        ".js",
        ".mov",
        ".mp3",
        ".mp4",
        ".pdf",
        ".png",
        ".ppt",
        ".pptx",
        ".rar",
        ".rss",
        ".svg",
        ".tar",
        ".wav",
        ".xls",
        ".xlsx",
        ".xml",
        ".zip",
    }
)
_URL_PROPERTY_NAMES = frozenset({"url"})
_URL_ATTRIBUTE_NAMES = frozenset({"href", "url", "data-href", "data-url"})
_LINK_HREF_FUNCTION = """function () {
    const href = this.href || this.getAttribute("href");
    if (href) return href;
    return this.getAttribute("data-href") || this.getAttribute("data-url") || "";
}"""


@dataclass(frozen=True, slots=True)
class AxCrawlerConfig:
    """Configuration for :func:`crawl_ax_links`.

    Attributes:
        start_url: Absolute URL where crawling starts.
        out_dir: Directory where crawl artifacts are written.
        max_depth: Maximum BFS depth. The start page is depth 0.
        max_pages: Maximum number of pages to visit.
        same_origin_only: Whether to reject links outside ``start_url``'s
            scheme, host, and port.
        wait_ms: Fixed wait after navigation before extracting the axtree.
        timeout_ms: Playwright navigation and operation timeout.
        delay_seconds: Optional delay between page visits.
        viewport: Browser viewport as ``(width, height)``.
        store_axtree_json: Whether to write raw merged axtree JSON artifacts.
        store_axtree_text: Whether to write deterministic text axtree artifacts.
        headless: Whether Chromium runs headless.
        traversal: Frontier traversal mode. ``"bfs"`` visits breadth-first;
            ``"dfs"`` follows the first discovered branch depth-first.
        crawl_query_urls: Whether URLs with query strings may enter the crawl
            frontier. Query URLs are still recorded as discovered graph edges
            when this is false.
    """

    start_url: str
    out_dir: Path
    max_depth: int = 3
    max_pages: int = 500
    same_origin_only: bool = True
    wait_ms: int = 1_000
    timeout_ms: int = 30_000
    delay_seconds: float = 0.0
    viewport: tuple[int, int] = (1280, 720)
    store_axtree_json: bool = True
    store_axtree_text: bool = True
    headless: bool = True
    traversal: TraversalMode = "bfs"
    crawl_query_urls: bool = False


@dataclass(frozen=True, slots=True)
class AxLink:
    """One URL-bearing accessibility node discovered on a page."""

    url: str
    role: str
    name: str
    bid: str | None
    source: str


@dataclass(frozen=True, slots=True)
class AxPageRecord:
    """Metadata recorded for one visited page."""

    index: int
    requested_url: str
    final_url: str
    title: str
    depth: int
    status: int | None
    links: list[AxLink]
    axtree_json: str | None
    axtree_text: str | None
    crawled_at: float


@dataclass(frozen=True, slots=True)
class AxCrawlResult:
    """Summary returned by :func:`crawl_ax_links`."""

    start_url: str
    out_dir: Path
    pages: list[AxPageRecord]
    failed_urls: list[dict[str, str]]
    discovered_urls: list[str]


def crawl_ax_links(config: AxCrawlerConfig) -> AxCrawlResult:
    """Crawl links exposed in BrowserGym accessibility trees.

    Args:
        config: Crawl configuration and output location.

    Returns:
        Summary of visited pages, failed URLs, and discovered URLs.

    Raises:
        ValueError: ``config`` is invalid.
        playwright.sync_api.Error: Browser startup or navigation can still
            surface Playwright errors for unrecoverable failures.
    """
    _validate_config(config)
    paths = _prepare_output_dirs(config.out_dir)

    start_url = normalize_url(config.start_url)
    start_origin = _origin_key(start_url)
    visited: set[str] = set()
    queued: set[str] = {start_url}
    frontier: deque[tuple[str, int]] = deque([(start_url, 0)])
    pages: list[AxPageRecord] = []
    failed_urls: list[dict[str, str]] = []
    discovered_urls: set[str] = {start_url}

    logger.info(
        "Starting AX crawl: start_url=%s out_dir=%s max_depth=%d max_pages=%d traversal=%s",
        start_url,
        config.out_dir,
        config.max_depth,
        config.max_pages,
        config.traversal,
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=config.headless)
        try:
            context = browser.new_context(
                viewport={"width": config.viewport[0], "height": config.viewport[1]}
            )
            while frontier and len(pages) < config.max_pages:
                requested_url, depth = _pop_frontier(frontier, config.traversal)
                queued.discard(requested_url)
                if requested_url in visited or depth > config.max_depth:
                    continue

                visited.add(requested_url)
                logger.info(
                    "Crawling page %d/%d at depth %d: %s",
                    len(pages) + 1,
                    config.max_pages,
                    depth,
                    requested_url,
                )
                try:
                    record = _crawl_one_page(
                        context=context,
                        config=config,
                        paths=paths,
                        requested_url=requested_url,
                        depth=depth,
                        page_index=len(pages),
                    )
                    pages.append(record)
                    _append_jsonl(paths.urls_jsonl, _page_json(record))
                    links_to_enqueue = _links_for_traversal(record.links, config.traversal)
                    enqueued_count = 0
                    for link in links_to_enqueue:
                        _append_jsonl(
                            paths.edges_jsonl,
                            {
                                "source_url": record.final_url,
                                "target_url": link.url,
                                "role": link.role,
                                "name": link.name,
                                "bid": link.bid,
                            },
                        )
                        discovered_urls.add(link.url)
                        if (
                            depth < config.max_depth
                            and link.url not in visited
                            and link.url not in queued
                            and _url_allowed(
                                link.url,
                                start_origin=start_origin,
                                same_origin_only=config.same_origin_only,
                                crawl_query_urls=config.crawl_query_urls,
                            )
                        ):
                            _push_frontier(frontier, link.url, depth + 1)
                            queued.add(link.url)
                            enqueued_count += 1

                    logger.info(
                        (
                            "Crawled page %d: status=%s links=%d enqueued=%d "
                            "frontier=%d final_url=%s"
                        ),
                        record.index,
                        record.status,
                        len(record.links),
                        enqueued_count,
                        len(frontier),
                        record.final_url,
                    )

                    if config.delay_seconds > 0:
                        time.sleep(config.delay_seconds)
                except Exception as exc:
                    logger.warning("Failed to crawl %s: %s", requested_url, exc)
                    failed_urls.append({"url": requested_url, "error": str(exc)})
                    _append_jsonl(paths.failures_jsonl, failed_urls[-1])
        finally:
            browser.close()

    result = AxCrawlResult(
        start_url=start_url,
        out_dir=config.out_dir,
        pages=pages,
        failed_urls=failed_urls,
        discovered_urls=sorted(discovered_urls),
    )
    _write_manifest(config, result, paths.manifest_json)
    logger.info(
        "Finished AX crawl: pages=%d failed=%d discovered=%d out_dir=%s",
        len(result.pages),
        len(result.failed_urls),
        len(result.discovered_urls),
        result.out_dir,
    )
    return result


def _crawl_one_page(
    *,
    context: playwright.sync_api.BrowserContext,
    config: AxCrawlerConfig,
    paths: _OutputPaths,
    requested_url: str,
    depth: int,
    page_index: int,
) -> AxPageRecord:
    """Navigate to one page, extract its axtree, and write page artifacts."""
    page = context.new_page()
    page.set_default_timeout(config.timeout_ms)
    try:
        response = page.goto(
            requested_url,
            wait_until="domcontentloaded",
            timeout=config.timeout_ms,
        )
        if config.wait_ms > 0:
            page.wait_for_timeout(config.wait_ms)

        axtree = extract_browsergym_axtree(page)
        final_url = normalize_url(page.url)
        url_by_backend_id = resolve_link_urls_from_page(page, axtree)
        links = extract_links_from_axtree(
            axtree,
            base_url=final_url,
            url_by_backend_id=url_by_backend_id,
        )
        return _write_page_artifacts(
            paths=paths,
            page_index=page_index,
            requested_url=requested_url,
            final_url=final_url,
            title=page.title(),
            depth=depth,
            status=response.status if response is not None else None,
            links=links,
            axtree=axtree,
            store_axtree_json=config.store_axtree_json,
            store_axtree_text=config.store_axtree_text,
        )
    finally:
        page.close()


def extract_browsergym_axtree(page: playwright.sync_api.Page) -> dict[str, object]:
    """Extract a BrowserGym merged accessibility tree for ``page``.

    Args:
        page: Playwright page to observe.

    Returns:
        BrowserGym/CDP-style merged axtree object.
    """
    last_error: Exception | None = None
    for attempt in range(_AXTREE_EXTRACT_MAX_ATTEMPTS):
        try:
            _pre_extract(
                page,
                tags_to_mark="standard_html",
                lenient=attempt == _AXTREE_EXTRACT_FINAL_ATTEMPT,
            )
            axtree = extract_merged_axtree(page)
            if isinstance(axtree, dict):
                return axtree
            return dict(axtree)
        except (playwright.sync_api.Error, MarkingError) as exc:
            last_error = exc
            _post_extract(page)
            if attempt == _AXTREE_EXTRACT_FINAL_ATTEMPT:
                raise
            time.sleep(0.5)
        finally:
            try:
                _post_extract(page)
            except playwright.sync_api.Error as exc:
                if "Frame has been detached" not in str(exc) and "Frame was detached" not in str(
                    exc
                ):
                    raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("BrowserGym axtree extraction failed without an exception")


def resolve_link_urls_from_page(
    page: playwright.sync_api.Page,
    axtree: Axtree,
) -> dict[int, str]:
    """Resolve DOM hrefs for link nodes present in ``axtree``.

    BrowserGym's merged axtree identifies AX links, but Chrome does not always
    include the target URL in the AX node payload. This helper keeps the AX tree
    as the source of truth for which elements count as links, then uses each AX
    node's ``backendDOMNodeId`` to read that exact element's href from the live
    page.

    Args:
        page: Live Playwright page that produced ``axtree``.
        axtree: BrowserGym merged accessibility tree.

    Returns:
        Mapping from AX ``backendDOMNodeId`` to raw href value.
    """
    backend_ids = [
        backend_id
        for node in _axtree_nodes(axtree)
        if _node_role(node) == "link" and (backend_id := _node_backend_id(node)) is not None
    ]
    if not backend_ids:
        return {}

    cdp = page.context.new_cdp_session(page)
    try:
        resolved: dict[int, str] = {}
        for backend_id in backend_ids:
            href = _resolve_backend_node_href(cdp, backend_id)
            if href:
                resolved[backend_id] = href
        return resolved
    finally:
        cdp.detach()


def extract_links_from_axtree(
    axtree: Axtree,
    *,
    base_url: str,
    url_by_backend_id: Mapping[int, str] | None = None,
) -> list[AxLink]:
    """Extract normalized URL links from a BrowserGym accessibility tree.

    Only URL-bearing accessibility nodes are considered. Raw DOM anchors are
    intentionally ignored.

    Args:
        axtree: BrowserGym merged accessibility tree.
        base_url: URL used to resolve relative link targets.
        url_by_backend_id: Optional href lookup keyed by AX node
            ``backendDOMNodeId``. Use :func:`resolve_link_urls_from_page` to
            build this from the live page when the axtree itself omits URL
            fields.

    Returns:
        Deduplicated links in axtree order.
    """
    links: list[AxLink] = []
    seen: set[str] = set()
    node_index = _node_index(axtree)
    for node in _axtree_nodes(axtree):
        role = _node_role(node)
        if role != "link":
            continue

        raw_url, source = _url_from_node(node, node_index, url_by_backend_id or {})
        if not raw_url:
            continue

        absolute = normalize_url(urljoin(base_url, raw_url))
        if not _is_http_url(absolute):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(
            AxLink(
                url=absolute,
                role=role,
                name=_node_name(node),
                bid=_node_bid(node),
                source=source,
            )
        )
    return links


def render_axtree_text(axtree: Axtree) -> str:
    """Render an accessibility tree as deterministic indented text.

    Args:
        axtree: BrowserGym merged accessibility tree.

    Returns:
        Text view containing role, accessible name, and BrowserGym bid.
    """
    nodes = _axtree_nodes(axtree)
    if not nodes:
        return ""
    node_index = _node_index(axtree)
    root = nodes[0]
    root_id = _node_id(root)
    if root_id is None:
        return "\n".join(_format_node_line(node, 0) for node in nodes)

    lines: list[str] = []
    seen: set[str] = set()

    def visit(node: Node, depth: int) -> None:
        node_id = _node_id(node)
        if node_id is not None:
            if node_id in seen:
                return
            seen.add(node_id)
        lines.append(_format_node_line(node, depth))
        for child_id in _node_child_ids(node):
            child = node_index.get(child_id)
            if child is not None:
                visit(child, depth + 1)

    visit(root, 0)
    return "\n".join(lines)


def normalize_url(url: str) -> str:
    """Normalize a URL for queue de-duplication.

    Args:
        url: Absolute or relative URL string.

    Returns:
        URL with lower-cased scheme/host, default ports removed, sorted query,
        fragment stripped, and non-root trailing slash removed.
    """
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    netloc = hostname
    is_default_port = (scheme == "http" and port == _HTTP_DEFAULT_PORT) or (
        scheme == "https" and port == _HTTPS_DEFAULT_PORT
    )
    if port is not None and not is_default_port:
        netloc = f"{hostname}:{port}"

    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)), doseq=True)
    return urlunparse((scheme, netloc, path, parsed.params, query, ""))


def _validate_config(config: AxCrawlerConfig) -> None:
    if not _is_http_url(config.start_url):
        raise ValueError(f"start_url must be an absolute http(s) URL: {config.start_url!r}")
    if config.max_depth < 0:
        raise ValueError("max_depth must be >= 0")
    if config.max_pages < 1:
        raise ValueError("max_pages must be >= 1")
    if config.wait_ms < 0:
        raise ValueError("wait_ms must be >= 0")
    if config.timeout_ms < 1:
        raise ValueError("timeout_ms must be >= 1")
    if config.delay_seconds < 0:
        raise ValueError("delay_seconds must be >= 0")
    if config.traversal not in ("bfs", "dfs"):
        raise ValueError("traversal must be 'bfs' or 'dfs'")


def _pop_frontier(
    frontier: deque[tuple[str, int]],
    traversal: TraversalMode,
) -> tuple[str, int]:
    if traversal == "bfs":
        return frontier.popleft()
    return frontier.pop()


def _push_frontier(frontier: deque[tuple[str, int]], url: str, depth: int) -> None:
    frontier.append((url, depth))


def _links_for_traversal(links: list[AxLink], traversal: TraversalMode) -> Iterable[AxLink]:
    if traversal == "dfs":
        return reversed(links)
    return links


def _axtree_nodes(axtree: Axtree) -> list[Node]:
    raw_nodes = axtree.get("nodes")
    if not isinstance(raw_nodes, list):
        return []
    return [node for node in raw_nodes if isinstance(node, Mapping)]


def _node_index(axtree: Axtree) -> dict[str, Node]:
    index: dict[str, Node] = {}
    for node in _axtree_nodes(axtree):
        node_id = _node_id(node)
        if node_id is not None:
            index[node_id] = node
    return index


def _node_id(node: Node) -> str | None:
    raw = node.get("nodeId")
    return raw if isinstance(raw, str) else None


def _node_child_ids(node: Node) -> list[str]:
    raw = node.get("childIds")
    if not isinstance(raw, list):
        return []
    return [child_id for child_id in raw if isinstance(child_id, str)]


def _node_role(node: Node) -> str:
    role = _dict_value(node, "role")
    value = _dict_value(role, "value")
    return value if isinstance(value, str) else ""


def _node_name(node: Node) -> str:
    name = _dict_value(node, "name")
    value = _dict_value(name, "value")
    return value if isinstance(value, str) else ""


def _node_bid(node: Node) -> str | None:
    raw = node.get("browsergym_id")
    return raw if isinstance(raw, str) else None


def _node_backend_id(node: Node) -> int | None:
    raw = node.get("backendDOMNodeId")
    return raw if isinstance(raw, int) else None


def _url_from_node(
    node: Node,
    node_index: Mapping[str, Node],
    url_by_backend_id: Mapping[int, str],
) -> tuple[str | None, str]:
    direct = node.get("url")
    if isinstance(direct, str) and direct:
        return direct, "node.url"

    backend_id = _node_backend_id(node)
    if backend_id is not None:
        raw = url_by_backend_id.get(backend_id)
        if raw:
            return raw, "backend_dom.href"

    for prop in _mapping_list(node.get("properties")):
        name = prop.get("name")
        if name not in _URL_PROPERTY_NAMES:
            continue
        value = _dict_value(_dict_value(prop, "value"), "value")
        if isinstance(value, str) and value:
            return value, f"property.{name}"

    for attr in _mapping_list(node.get("attributes")):
        name = attr.get("name")
        if name not in _URL_ATTRIBUTE_NAMES:
            continue
        value = attr.get("value")
        if isinstance(value, str) and value:
            return value, f"attribute.{name}"

    for child_id in _node_child_ids(node):
        child = node_index.get(child_id)
        if child is None:
            continue
        child_url = child.get("url")
        if isinstance(child_url, str) and child_url:
            return child_url, "child.url"

    return None, "none"


def _resolve_backend_node_href(
    cdp: playwright.sync_api.CDPSession,
    backend_id: int,
) -> str | None:
    try:
        resolved = cdp.send("DOM.resolveNode", {"backendNodeId": backend_id})
        remote_object = resolved.get("object")
        if not isinstance(remote_object, Mapping):
            return None
        object_id = remote_object.get("objectId")
        if not isinstance(object_id, str):
            return None
        result = cdp.send(
            "Runtime.callFunctionOn",
            {
                "objectId": object_id,
                "functionDeclaration": _LINK_HREF_FUNCTION,
                "returnByValue": True,
            },
        )
        raw_result = result.get("result")
        if not isinstance(raw_result, Mapping):
            return None
        value = raw_result.get("value")
        return value if isinstance(value, str) and value else None
    except playwright.sync_api.Error:
        return None


def _dict_value(value: object, key: str) -> object:
    if not isinstance(value, Mapping):
        return None
    return value.get(key)


def _mapping_list(value: object) -> Iterable[Mapping[str, object]]:
    if not isinstance(value, list):
        return ()
    return (item for item in value if isinstance(item, Mapping))


def _format_node_line(node: Node, depth: int) -> str:
    indent = "  " * depth
    bid = _node_bid(node)
    bid_part = f"[{bid}] " if bid else ""
    name = _node_name(node)
    name_part = f" {name!r}" if name else ""
    return f"{indent}{bid_part}{_node_role(node) or 'unknown'}{name_part}"


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in _HTTP_SCHEMES and bool(parsed.netloc)


def _origin_key(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    return (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port)


def _url_allowed(
    url: str,
    *,
    start_origin: tuple[str, str, int | None],
    same_origin_only: bool,
    crawl_query_urls: bool,
) -> bool:
    if not _is_http_url(url):
        return False
    parsed = urlparse(url)
    if parsed.query and not crawl_query_urls:
        return False
    if any(parsed.path.lower().endswith(ext) for ext in _DEFAULT_EXCLUDED_EXTENSIONS):
        return False
    return not same_origin_only or _origin_key(url) == start_origin


@dataclass(frozen=True, slots=True)
class _OutputPaths:
    pages_dir: Path
    axtrees_dir: Path
    urls_jsonl: Path
    edges_jsonl: Path
    failures_jsonl: Path
    manifest_json: Path


def _prepare_output_dirs(out_dir: Path) -> _OutputPaths:
    pages_dir = out_dir / "pages"
    axtrees_dir = out_dir / "axtrees"
    pages_dir.mkdir(parents=True, exist_ok=True)
    axtrees_dir.mkdir(parents=True, exist_ok=True)
    return _OutputPaths(
        pages_dir=pages_dir,
        axtrees_dir=axtrees_dir,
        urls_jsonl=out_dir / "urls.jsonl",
        edges_jsonl=out_dir / "edges.jsonl",
        failures_jsonl=out_dir / "failures.jsonl",
        manifest_json=out_dir / "manifest.json",
    )


def _write_page_artifacts(
    *,
    paths: _OutputPaths,
    page_index: int,
    requested_url: str,
    final_url: str,
    title: str,
    depth: int,
    status: int | None,
    links: list[AxLink],
    axtree: Axtree,
    store_axtree_json: bool,
    store_axtree_text: bool,
) -> AxPageRecord:
    stem = f"{page_index:06d}"
    axtree_json_path = paths.axtrees_dir / f"{stem}.axtree.json"
    axtree_text_path = paths.axtrees_dir / f"{stem}.axtree.txt"
    if store_axtree_json:
        _write_json(axtree_json_path, _json_safe(axtree))
    if store_axtree_text:
        axtree_text_path.write_text(render_axtree_text(axtree), encoding="utf-8")

    record = AxPageRecord(
        index=page_index,
        requested_url=requested_url,
        final_url=final_url,
        title=title,
        depth=depth,
        status=status,
        links=links,
        axtree_json=str(axtree_json_path) if store_axtree_json else None,
        axtree_text=str(axtree_text_path) if store_axtree_text else None,
        crawled_at=time.time(),
    )
    _write_json(paths.pages_dir / f"{stem}.json", _page_json(record))
    return record


def _page_json(record: AxPageRecord) -> dict[str, JsonValue]:
    return {
        "index": record.index,
        "requested_url": record.requested_url,
        "final_url": record.final_url,
        "title": record.title,
        "depth": record.depth,
        "status": record.status,
        "links": [asdict(link) for link in record.links],
        "axtree_json": record.axtree_json,
        "axtree_text": record.axtree_text,
        "crawled_at": record.crawled_at,
    }


def _write_manifest(config: AxCrawlerConfig, result: AxCrawlResult, path: Path) -> None:
    _write_json(
        path,
        {
            "config": {
                "start_url": config.start_url,
                "max_depth": config.max_depth,
                "max_pages": config.max_pages,
                "same_origin_only": config.same_origin_only,
                "wait_ms": config.wait_ms,
                "timeout_ms": config.timeout_ms,
                "delay_seconds": config.delay_seconds,
                "viewport": list(config.viewport),
                "store_axtree_json": config.store_axtree_json,
                "store_axtree_text": config.store_axtree_text,
                "headless": config.headless,
                "traversal": config.traversal,
                "crawl_query_urls": config.crawl_query_urls,
            },
            "summary": {
                "start_url": result.start_url,
                "pages_crawled": len(result.pages),
                "failed_urls": len(result.failed_urls),
                "discovered_urls": len(result.discovered_urls),
            },
            "discovered_urls": result.discovered_urls,
            "failed_urls": result.failed_urls,
        },
    )


def _append_jsonl(path: Path, payload: Mapping[str, JsonValue]) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")


def _write_json(path: Path, payload: JsonValue) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _json_safe(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return repr(value)
