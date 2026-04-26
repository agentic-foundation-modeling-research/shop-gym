"""Unit tests for :mod:`shop_explore.cli`.

Covers T1.6 of ``docs/impl/shop_explore_implementation.md`` plus the
``--out``-as-resume affordance from
``docs/specs/harness/resume.md`` §5.6:

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
* When ``--out`` points at a run_dir whose ``run.json`` records a
  prior ``config_snapshot``, the CLI defaults ``--max-iters`` /
  ``--timeout`` / ``--runtime`` from that snapshot, rejects mismatched
  ``url`` / ``--runtime`` values, and forwards ``--force-resume`` to
  :class:`shop_explore.config.ExploreConfig`.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from harness.config import FinalStatus
from shop_explore import cli as cli_mod
from shop_explore.cli import EXIT_OK, EXIT_USAGE, main
from shop_explore.config import (
    DEFAULT_MAX_ITERS,
    DEFAULT_TIMEOUT_SECONDS,
    ExploreConfig,
    ExploreResult,
)

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
    mock.get(f"{BASE_URL}/products.json", params={"page": "1", "limit": "250"}).mock(
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
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--synthesize-only PATH`` runs §5.10 against an existing run_dir.

    The configured runtime is replaced with a non-completer stub so the
    CLI's T6.2 wiring falls back to the no-op LLM client and the manual
    is rendered as the deterministic concatenation of ``parts/*.md``
    (``manifest.manual_fallback == True``). Exercises the
    ``isinstance(runtime, LLMCompleter)`` branch in
    :func:`shop_explore.pipeline.build_runtime_llm`.
    """
    run_dir = _seed_minimal_run_dir(tmp_path)

    class _NoCompleterRuntime:
        """Stand-in runtime missing the optional ``complete`` method."""

    def fake_get_runtime(_name: str) -> _NoCompleterRuntime:
        return _NoCompleterRuntime()

    monkeypatch.setattr(cli_mod, "get_runtime", fake_get_runtime)

    rc = main(["--synthesize-only", str(run_dir), BASE_URL])

    assert rc == EXIT_OK
    artifact = run_dir / "artifact"
    assert (artifact / "manual.md").is_file()
    assert (artifact / "capabilities.json").is_file()
    assert (artifact / "stats.json").is_file()
    assert (artifact / "manifest.json").is_file()

    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manual_fallback"] is True
    manual_text = (artifact / "manual.md").read_text(encoding="utf-8")
    assert "placeholder body" in manual_text

    out = capsys.readouterr().out
    assert "manual_fallback=true" in out


def test_synthesize_only_routes_manual_call_through_completer_runtime(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A runtime satisfying ``LLMCompleter`` receives the manual-merge prompt.

    Asserts impl plan T6.2: the CLI's ``--synthesize-only`` path
    delegates the §5.10 LLM call to the configured runtime instead of
    the no-op fallback. The stub returns a non-empty completion so
    ``manifest.manual_fallback`` flips to ``False``.
    """
    run_dir = _seed_minimal_run_dir(tmp_path)
    captured: dict[str, object] = {}
    expected_timeout = 9.0

    sentinel_body = (
        "Real model output for the merged manual. " * 8
    )  # > 200 chars; clears spec §5.10 minimum length

    class _CompleterRuntime:
        def complete(self, prompt: str, *, timeout: float) -> str:
            captured["prompt"] = prompt
            captured["timeout"] = timeout
            return f"# Shop Manual\n\n{sentinel_body}\n"

    def fake_get_runtime(_name: str) -> _CompleterRuntime:
        return _CompleterRuntime()

    monkeypatch.setattr(cli_mod, "get_runtime", fake_get_runtime)

    rc = main(["--synthesize-only", str(run_dir), "--timeout", str(expected_timeout), BASE_URL])

    assert rc == EXIT_OK
    artifact = run_dir / "artifact"
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manual_fallback"] is False
    manual_text = (artifact / "manual.md").read_text(encoding="utf-8")
    assert "Real model output for the merged manual." in manual_text

    # The runtime really did receive the manual-merge prompt with the
    # CLI's configured per-iteration timeout.
    assert "placeholder body" in str(captured["prompt"])
    assert captured["timeout"] == expected_timeout

    out = capsys.readouterr().out
    assert "manual_fallback=false" in out


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


def _seed_prior_run_summary(
    run_dir: Path,
    *,
    url: str = BASE_URL,
    runtime: str = "claude_code",
    max_iters: int = 7,
    timeout: float = 12.5,
) -> dict[str, object]:
    """Lay down a ``run.json`` matching :class:`harness.summary.RunSummaryWriter`.

    Returns the persisted ``config_snapshot`` dict so callers can assert
    against it. Only the fields the CLI consults are populated; the
    harness's own validation lives outside this test surface.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshot: dict[str, object] = {
        "url": url,
        "runtime": runtime,
        "max_iters": max_iters,
        "timeout": timeout,
        "resume_history": [],
    }
    payload = {
        "schema_version": "1",
        "final_status": "completed",
        "config_snapshot": snapshot,
    }
    (run_dir / "run.json").write_text(json.dumps(payload), encoding="utf-8")
    return snapshot


def _stub_explore(
    monkeypatch: pytest.MonkeyPatch,
    captured: dict[str, ExploreConfig],
) -> None:
    """Replace :func:`shop_explore.cli.explore` with a config-capturing stub."""

    def fake_explore(config: ExploreConfig) -> ExploreResult:
        captured["config"] = config
        artifact = (config.out_dir or Path("/tmp/fake")) / "artifact"
        return ExploreResult(
            run_dir=config.out_dir or Path("/tmp/fake"),
            manual_path=artifact / "manual.md",
            capabilities_path=artifact / "capabilities.json",
            stats_path=artifact / "stats.json",
            manifest_path=artifact / "manifest.json",
            prefetch_dir=artifact / "prefetch",
            final_status=FinalStatus.COMPLETED,
        )

    monkeypatch.setattr(cli_mod, "explore", fake_explore)


def test_explore_resume_inherits_prior_runtime_iters_and_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "prior"
    _seed_prior_run_summary(run_dir, runtime="claude_code", max_iters=7, timeout=12.5)
    captured: dict[str, ExploreConfig] = {}
    _stub_explore(monkeypatch, captured)

    expected_max_iters = 7
    expected_timeout = 12.5
    rc = main(["--out", str(run_dir), BASE_URL])

    assert rc == EXIT_OK
    config = captured["config"]
    assert config.runtime == "claude_code"
    assert config.max_iters == expected_max_iters
    assert config.timeout == expected_timeout
    assert config.force_resume is False


def test_explore_resume_explicit_flags_override_prior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "prior"
    _seed_prior_run_summary(run_dir, runtime="claude_code", max_iters=7, timeout=12.5)
    captured: dict[str, ExploreConfig] = {}
    _stub_explore(monkeypatch, captured)

    expected_max_iters = 3
    expected_timeout = 60.0
    rc = main(
        [
            "--out",
            str(run_dir),
            "--max-iters",
            str(expected_max_iters),
            "--timeout",
            str(int(expected_timeout)),
            "--runtime",
            "claude_code",
            BASE_URL,
        ]
    )

    assert rc == EXIT_OK
    config = captured["config"]
    assert config.max_iters == expected_max_iters
    assert config.timeout == expected_timeout


def test_explore_resume_rejects_runtime_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "prior"
    _seed_prior_run_summary(run_dir, runtime="claude_code")
    captured: dict[str, ExploreConfig] = {}
    _stub_explore(monkeypatch, captured)

    rc = main(["--out", str(run_dir), "--runtime", "pi", BASE_URL])

    assert rc == EXIT_USAGE
    assert "config" not in captured
    err = capsys.readouterr().err
    assert "--runtime" in err
    assert "claude_code" in err


def test_explore_resume_rejects_url_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "prior"
    _seed_prior_run_summary(run_dir, url="https://other-shop.com")
    captured: dict[str, ExploreConfig] = {}
    _stub_explore(monkeypatch, captured)

    rc = main(["--out", str(run_dir), BASE_URL])

    assert rc == EXIT_USAGE
    assert "config" not in captured
    err = capsys.readouterr().err
    assert "url" in err
    assert "other-shop.com" in err


def test_explore_force_resume_flag_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "prior"
    _seed_prior_run_summary(run_dir)
    captured: dict[str, ExploreConfig] = {}
    _stub_explore(monkeypatch, captured)

    rc = main(["--out", str(run_dir), "--force-resume", BASE_URL])

    assert rc == EXIT_OK
    assert captured["config"].force_resume is True


def test_explore_fresh_run_uses_spec_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No prior ``run.json`` ⇒ argparse defaults fall back to spec values."""
    fresh_dir = tmp_path / "fresh"
    captured: dict[str, ExploreConfig] = {}
    _stub_explore(monkeypatch, captured)

    rc = main(["--out", str(fresh_dir), BASE_URL])

    assert rc == EXIT_OK
    config = captured["config"]
    assert config.runtime == "pi"
    assert config.max_iters == DEFAULT_MAX_ITERS
    assert config.timeout == DEFAULT_TIMEOUT_SECONDS
    assert config.force_resume is False
