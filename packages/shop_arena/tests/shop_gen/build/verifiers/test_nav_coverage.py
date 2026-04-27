"""Unit tests for :class:`shop_gen.build.verifiers.nav_coverage.NavCoverageVerifier`.

Covers T5.4 + spec §5.5.3: every collection handle in
``data/collections.json`` must appear textually somewhere under
``hydrogen/app/**/*.{tsx,ts}``. Tests cover passing, failing,
malformed-data, and missing-tree paths.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from harness.verifiers import Verdict, VerifierContext
from shop_gen.build.verifiers.nav_coverage import NavCoverageVerifier


def _write_collections(data_dir: Path, handles: list[str]) -> Path:
    """Write a minimal ``data/collections.json`` with ``handles`` and return it."""
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = [{"handle": h, "title": h.replace("-", " ").title()} for h in handles]
    target = data_dir / "collections.json"
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def test_name_and_applicability(tmp_path: Path) -> None:
    verifier = NavCoverageVerifier(data_dir=tmp_path)
    assert verifier.name == "nav_coverage"
    assert verifier.applies_to("gen_navigation") is True
    assert verifier.applies_to("gen_homepage") is False
    assert verifier.applies_to("consolidate") is False


def test_passes_when_every_handle_is_referenced(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    _write_collections(data_dir, ["new-arrivals", "best-sellers"])
    write_app_file(
        "components/Header.tsx",
        """
        export const NAV = [
          { to: '/collections/new-arrivals', label: 'New' },
          { to: '/collections/best-sellers', label: 'Bestsellers' },
        ];
        """.strip(),
    )

    verifier = NavCoverageVerifier(data_dir=data_dir)
    result = verifier.run(make_ctx(selected_task_id="gen_navigation"))

    assert result.verdict is Verdict.PASS
    assert result.details == {"collections": 2, "missing": 0}


def test_fails_when_handle_is_not_referenced(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    _write_collections(data_dir, ["new-arrivals", "secret-stash"])
    write_app_file(
        "components/Header.tsx",
        "export const NAV = [{ to: '/collections/new-arrivals' }];",
    )

    verifier = NavCoverageVerifier(data_dir=data_dir)
    result = verifier.run(make_ctx(selected_task_id="gen_navigation"))

    assert result.verdict is Verdict.FAIL
    assert result.details["missing"] == 1
    assert result.details["missing_handles"] == ["secret-stash"]
    assert "secret-stash" in result.feedback
    assert "1 of 2" in result.feedback


def test_fails_when_collections_file_is_absent(
    make_ctx: Callable[..., VerifierContext],
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    verifier = NavCoverageVerifier(data_dir=data_dir)
    result = verifier.run(make_ctx(selected_task_id="gen_navigation"))
    assert result.verdict is Verdict.FAIL
    assert "could not read" in result.feedback


def test_fails_when_collections_file_is_malformed(
    make_ctx: Callable[..., VerifierContext],
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "collections.json").write_text("not json", encoding="utf-8")
    verifier = NavCoverageVerifier(data_dir=data_dir)
    result = verifier.run(make_ctx(selected_task_id="gen_navigation"))
    assert result.verdict is Verdict.FAIL
    assert "is not valid JSON" in result.feedback


def test_fails_when_collections_file_is_not_array(
    make_ctx: Callable[..., VerifierContext],
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "collections.json").write_text('{"handle": "alone"}', encoding="utf-8")
    verifier = NavCoverageVerifier(data_dir=data_dir)
    result = verifier.run(make_ctx(selected_task_id="gen_navigation"))
    assert result.verdict is Verdict.FAIL
    assert "must be a JSON array" in result.feedback


def test_fails_when_collection_lacks_handle(
    make_ctx: Callable[..., VerifierContext],
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "collections.json").write_text('[{"title": "no handle"}]', encoding="utf-8")
    verifier = NavCoverageVerifier(data_dir=data_dir)
    result = verifier.run(make_ctx(selected_task_id="gen_navigation"))
    assert result.verdict is Verdict.FAIL
    assert "missing string 'handle'" in result.feedback


def test_fails_when_collections_file_is_empty_array(
    make_ctx: Callable[..., VerifierContext],
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "collections.json").write_text("[]", encoding="utf-8")
    verifier = NavCoverageVerifier(data_dir=data_dir)
    result = verifier.run(make_ctx(selected_task_id="gen_navigation"))
    assert result.verdict is Verdict.FAIL
    assert "no collections to check" in result.feedback


def test_fails_when_hydrogen_tree_missing(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    _write_collections(data_dir, ["only-one"])
    # Strip the app/ subtree to simulate a clone failure.
    app_dir = artifact_dir / "hydrogen" / "app"
    for child in sorted(app_dir.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        else:
            child.rmdir()
    app_dir.rmdir()
    (artifact_dir / "hydrogen").rmdir()

    verifier = NavCoverageVerifier(data_dir=data_dir)
    result = verifier.run(make_ctx(selected_task_id="gen_navigation"))
    assert result.verdict is Verdict.FAIL
    assert "could not find the hydrogen app tree" in result.feedback


def test_handle_match_is_case_sensitive_and_exact(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
    tmp_path: Path,
) -> None:
    """A handle that only appears with different casing should fail."""
    data_dir = tmp_path / "data"
    _write_collections(data_dir, ["mens-shoes"])
    write_app_file(
        "components/Header.tsx",
        "// Mens-Shoes is mentioned but not the exact handle.",
    )
    verifier = NavCoverageVerifier(data_dir=data_dir)
    result = verifier.run(make_ctx(selected_task_id="gen_navigation"))
    assert result.verdict is Verdict.FAIL


def test_only_ts_and_tsx_are_inspected(
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
    tmp_path: Path,
) -> None:
    """A handle hidden in JSON or CSS does not count as nav coverage."""
    data_dir = tmp_path / "data"
    _write_collections(data_dir, ["limited-edition"])
    write_app_file(
        "data/manifest.json",
        '{"links": ["/collections/limited-edition"]}',
    )
    write_app_file("styles/app.css", '.banner::before { content: "limited-edition"; }')
    verifier = NavCoverageVerifier(data_dir=data_dir)
    result = verifier.run(make_ctx(selected_task_id="gen_navigation"))
    assert result.verdict is Verdict.FAIL
    assert "limited-edition" in result.details["missing_handles"]
