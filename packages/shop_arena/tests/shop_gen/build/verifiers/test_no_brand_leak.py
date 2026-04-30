"""Unit tests for :class:`shop_gen.build.verifiers.no_brand_leak.NoBrandLeakVerifier`.

Covers T5.4 + spec §5.6: the verifier walks ``hydrogen/app/**`` and
runs the canonical allowlist scanner. Tests cover passing, failing,
multi-hit, missing-tree, and feedback-content paths.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from harness.verifiers import Verdict, VerifierContext
from shop_gen.brands.allowlist import Allowlist
from shop_gen.build.verifiers.no_brand_leak import NoBrandLeakVerifier


def test_name_and_applicability() -> None:
    verifier = NoBrandLeakVerifier()
    assert verifier.name == "no_brand_leak"
    assert verifier.applies_to("gen_theme") is True
    assert verifier.applies_to("gen_homepage") is True
    # Spec §5.5.4 lists visual_fix's gating set explicitly; no_brand_leak
    # is not on it.
    assert verifier.applies_to("visual_fix") is False
    assert verifier.applies_to("plan") is False


def test_passes_on_clean_tree(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    write_app_file(
        "components/Header.tsx",
        "export const greeting = 'shop with us today';\n",
    )
    write_app_file(
        "styles/app.css",
        ".btn { color: red; }\n",
    )
    verifier = NoBrandLeakVerifier()
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.PASS
    assert result.details["leaks"] == 0
    assert result.details["files_scanned"] == 2  # noqa: PLR2004


def test_passes_when_only_allowlisted_brands_present(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    write_app_file(
        "components/Footer.tsx",
        "export const vendor = 'AisleArena';\nconst label = 'Shopliseum picks';\n",
    )
    verifier = NoBrandLeakVerifier()
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.PASS


def test_fails_when_brand_leak_found(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    write_app_file(
        "routes/index.tsx",
        "// recommended by Patagonia for the spring drop.\n",
    )
    verifier = NoBrandLeakVerifier()
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert result.details["leaks"] == 1
    assert "Patagonia" in result.feedback
    assert "Allowed brands:" in result.feedback
    # The full allowlist is embedded so the next iteration has the
    # vocabulary in scope (sample two tokens from the canonical set).
    assert "AisleArena" in result.feedback
    assert "Cartanvil" in result.feedback


def test_fails_with_multi_hit_summary(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    write_app_file(
        "routes/products.tsx",
        "const partners = ['Patagonia', 'Adidas', 'Lululemon'];\n",
    )
    write_app_file(
        "components/Hero.css",
        "/* uses the Nike palette today. */\n",
    )
    verifier = NoBrandLeakVerifier()
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert result.details["leaks"] == 4  # noqa: PLR2004
    for brand in ("Patagonia", "Adidas", "Lululemon", "Nike"):
        assert brand in result.feedback


def test_fails_when_hydrogen_tree_missing(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
) -> None:
    # Strip the app/ subtree to simulate a clone failure.
    app_dir = artifact_dir / "hydrogen" / "app"
    for child in sorted(app_dir.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        else:
            child.rmdir()
    app_dir.rmdir()
    (artifact_dir / "hydrogen").rmdir()

    verifier = NoBrandLeakVerifier()
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert "could not find the hydrogen app tree" in result.feedback
    assert result.details["exists"] is False


def test_skips_files_with_unsupported_suffix(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """A leak hidden in a `.json` file should not flip the verdict."""
    write_app_file("data/manifest.json", '{"vendor": "Patagonia"}\n')
    verifier = NoBrandLeakVerifier()
    result = verifier.run(make_ctx())
    # The verifier only scans `.tsx`/`.ts`/`.css`/`.md`; the `.json`
    # file is owned by the data-synth pipeline.
    assert result.verdict is Verdict.PASS


def test_caps_feedback_to_50_leaks(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """Feedback markdown elides leaks beyond the 50-hit cap."""
    body = "\n".join(f"const brand{i} = 'BrandToken{i}';" for i in range(60))
    write_app_file("components/Massive.tsx", body + "\n")
    verifier = NoBrandLeakVerifier()
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    assert result.details["leaks"] == 60  # noqa: PLR2004
    assert "and 10 more leak(s) elided." in result.feedback


def test_accepts_pre_loaded_allowlist(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    """An injected allowlist with extra entries lets a token slip through."""
    custom = Allowlist(
        version="0.0.0-test",
        brands=frozenset({"AisleArena", "Patagonia"}),
        safe_nouns=frozenset({"The"}),
    )
    write_app_file("routes/index.tsx", "// curated by Patagonia\n")
    verifier = NoBrandLeakVerifier(allowlist=custom)
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.PASS


def test_reports_relative_paths_in_feedback(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    write_app_file("routes/leaks.tsx", "const brand = 'Patagonia';\n")
    verifier = NoBrandLeakVerifier()
    result = verifier.run(make_ctx())
    assert result.verdict is Verdict.FAIL
    # The path in the feedback markdown should be human-readable
    # (relative to the artifact root) rather than absolute.
    assert "hydrogen/app/routes/leaks.tsx" in result.feedback
