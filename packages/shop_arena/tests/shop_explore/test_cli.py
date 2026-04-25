"""Unit tests for :mod:`shop_explore.cli`.

Covers T1.6 of ``docs/impl/shop_explore_implementation.md``:

* ``shop-explore --prefetch-only <url>`` runs :func:`shop_explore.prefetch.run`
  against the supplied URL and writes the §5.4 ``prefetch/`` layout
  under ``--out PATH``.
* ``shop-explore --prefetch-only`` defaults its output directory to
  ``outputs/shop_manuals/<domain>/<run_id>/`` when ``--out`` is omitted.
* The CLI surfaces :class:`shop_explore.prefetch.ShopUnreachableError`
  as a non-zero exit code with a helpful stderr message.
* Invocation without ``--prefetch-only`` is rejected (the full pipeline
  is wired in a later milestone).
* Argparse rejects a missing ``url`` positional with a non-zero exit
  via ``SystemExit``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from shop_explore.cli import EXIT_OK, EXIT_USAGE, main

BASE_URL = "https://example-shop.com"


def _ok(content: str | bytes, *, content_type: str = "text/html; charset=utf-8") -> httpx.Response:
    body = content.encode("utf-8") if isinstance(content, str) else content
    return httpx.Response(200, content=body, headers={"content-type": content_type})


def _stub_storefront(mock: respx.MockRouter) -> None:
    """Stub every URL the prefetch plan hits with a 200 response."""
    mock.get(f"{BASE_URL}/robots.txt").mock(
        return_value=_ok("User-agent: *\nAllow: /\n", content_type="text/plain")
    )
    mock.get(f"{BASE_URL}/").mock(return_value=_ok("<!doctype html><html></html>"))
    mock.get(f"{BASE_URL}/sitemap.xml").mock(
        return_value=_ok("<?xml version='1.0'?><urlset></urlset>", content_type="application/xml")
    )
    mock.get(f"{BASE_URL}/products.json", params={"limit": "50"}).mock(
        return_value=_ok('{"products": []}', content_type="application/json")
    )
    mock.get(f"{BASE_URL}/collections.json", params={"limit": "50"}).mock(
        return_value=_ok('{"collections": []}', content_type="application/json")
    )
    mock.get(
        f"{BASE_URL}/search/suggest.json",
        params={"q": "a", "resources[type]": "product"},
    ).mock(return_value=_ok('{"resources": {}}', content_type="application/json"))
    mock.get(f"{BASE_URL}/cart.js").mock(
        return_value=_ok('{"items": []}', content_type="application/json")
    )
    mock.get(f"{BASE_URL}/cart").mock(return_value=_ok("<html>cart</html>"))
    mock.get(f"{BASE_URL}/search").mock(return_value=_ok("<html>search</html>"))
    for slug in ("refund-policy", "privacy-policy", "terms-of-service", "shipping-policy"):
        mock.get(f"{BASE_URL}/policies/{slug}").mock(return_value=_ok(f"<html>{slug}</html>"))
    for slug in ("about", "contact", "faq"):
        mock.get(f"{BASE_URL}/pages/{slug}").mock(return_value=_ok(f"<html>{slug}</html>"))


@respx.mock
def test_prefetch_only_writes_expected_layout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_storefront(respx.mock)

    rc = main(["--prefetch-only", "--out", str(tmp_path), BASE_URL])

    assert rc == EXIT_OK

    prefetch_dir = tmp_path / "artifact" / "prefetch"
    assert prefetch_dir.is_dir()
    # §5.4 layout — top-level files.
    for name in (
        "robots.txt",
        "index.html",
        "sitemap.xml",
        "products.json",
        "collections.json",
        "search_suggest.json",
        "cart.js",
        "cart.html",
        "search.html",
        "prefetch.json",
    ):
        assert (prefetch_dir / name).is_file(), name
    for slug in ("refund-policy", "privacy-policy", "terms-of-service", "shipping-policy"):
        assert (prefetch_dir / "policies" / f"{slug}.html").is_file()
    for slug in ("about", "contact", "faq"):
        assert (prefetch_dir / "pages" / f"{slug}.html").is_file()

    summary = json.loads((prefetch_dir / "prefetch.json").read_text())
    assert summary["base_url"] == BASE_URL

    out = capsys.readouterr().out
    assert str(prefetch_dir) in out


@respx.mock
def test_prefetch_only_defaults_run_dir_under_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_storefront(respx.mock)
    monkeypatch.chdir(tmp_path)

    rc = main(["--prefetch-only", BASE_URL])

    assert rc == EXIT_OK
    domain_root = tmp_path / "outputs" / "shop_manuals" / "example-shop.com"
    assert domain_root.is_dir()
    runs = list(domain_root.iterdir())
    assert len(runs) == 1
    assert (runs[0] / "artifact" / "prefetch" / "prefetch.json").is_file()


@respx.mock
def test_prefetch_only_returns_nonzero_on_bot_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.mock.get(f"{BASE_URL}/robots.txt").mock(
        return_value=httpx.Response(
            200,
            content=b"User-agent: *\nDisallow: /\n",
            headers={"content-type": "text/plain"},
        )
    )

    rc = main(["--prefetch-only", "--out", str(tmp_path), BASE_URL])

    assert rc == EXIT_USAGE
    err = capsys.readouterr().err
    assert "shop unreachable" in err
    assert "robots_disallow" in err


def test_synthesize_only_publishes_manual_against_existing_run_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--synthesize-only PATH`` runs §5.10 against an existing run_dir."""
    run_dir = _seed_minimal_run_dir(tmp_path)

    rc = main(["--synthesize-only", str(run_dir), BASE_URL])

    assert rc == EXIT_OK
    artifact = run_dir / "artifact"
    assert (artifact / "manual.md").is_file()
    assert (artifact / "capabilities.json").is_file()
    assert (artifact / "stats.json").is_file()
    assert (artifact / "manifest.json").is_file()

    # Without a real LLM client wired the CLI uses the no-op fallback,
    # so the manual is the deterministic concatenation of parts/*.md.
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manual_fallback"] is True
    manual_text = (artifact / "manual.md").read_text(encoding="utf-8")
    assert "placeholder body" in manual_text

    out = capsys.readouterr().out
    assert "manual_fallback=true" in out


def test_synthesize_only_rejects_missing_run_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--synthesize-only`` exits non-zero when ``PATH`` does not exist."""
    missing = tmp_path / "does-not-exist"

    rc = main(["--synthesize-only", str(missing), BASE_URL])

    assert rc == EXIT_USAGE
    err = capsys.readouterr().err
    assert "--synthesize-only" in err


def _seed_minimal_run_dir(tmp_path: Path) -> Path:
    """Lay down a minimal harness-shaped run_dir for synthesis to consume."""
    run_dir = tmp_path / "example-shop.com" / "20251024T120000Z-deadbeef"
    parts_dir = run_dir / "artifact" / "parts"
    prefetch_dir = run_dir / "artifact" / "prefetch"
    parts_dir.mkdir(parents=True)
    prefetch_dir.mkdir(parents=True)
    (parts_dir / "placeholder.md").write_text(
        "# placeholder\n\nplaceholder body.\n", encoding="utf-8"
    )
    (parts_dir / "placeholder.caps.json").write_text("{}", encoding="utf-8")
    (prefetch_dir / "products.json").write_text('{"products": []}', encoding="utf-8")
    (prefetch_dir / "collections.json").write_text('{"collections": []}', encoding="utf-8")
    (prefetch_dir / "cart.js").write_text('{"items": []}', encoding="utf-8")
    (run_dir / "plan.md").write_text("# plan.md\n\n## Tasks\n\n", encoding="utf-8")
    return run_dir


def test_missing_url_exits_with_usage_error() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main([])
    # argparse's standard usage-error exit code.
    assert exc_info.value.code == EXIT_USAGE
