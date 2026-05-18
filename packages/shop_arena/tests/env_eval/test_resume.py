"""Unit tests for ``shop_arena.env_eval.resume`` (impl plan M6).

Covers the artifact-existence helpers that back run-directory reuse
(spec §5.7):

* :func:`expected_artifacts` enumerates the right files per step for a
  measurable :class:`PagesDoc`, drops ``not_found`` buckets, and tolerates
  ``pages=None`` (pre-discovery) without raising.
* :func:`can_skip` returns ``True`` only when every required file is
  present, ``False`` for any missing path or empty path list, and raises
  :class:`ResumeError` for an unknown step.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shop_arena.env_eval import resume
from shop_arena.env_eval.errors import ResumeError
from shop_arena.env_eval.pages import (
    PAGES_JSON_FILENAME,
    CartAndSearch,
    PageNotFound,
    PageOk,
    PagesDoc,
    SearchPageOk,
)


def test_resume_module_is_importable() -> None:
    """M0 layout marker: ``resume`` module exists and imports."""
    assert resume.__name__ == "shop_arena.env_eval.resume"


def test_steps_literal_is_in_pipeline_order() -> None:
    """``STEPS`` enumerates the five pipeline phases in execution order."""
    assert resume.STEPS == (
        "pages",
        "transition",
        "observation",
        "action",
        "metrics",
    )


def _full_pages_doc() -> PagesDoc:
    """Return a :class:`PagesDoc` with every measurable bucket populated."""
    return PagesDoc(
        base_url="https://shop.example.com/",
        homepage=PageOk(url="/", selected_by="input"),
        collection=PageOk(
            url="/collections/men",
            canonical_url="/collections/<*>",
            selected_by="first_href",
        ),
        product=PageOk(
            url="/products/linen-shirt",
            canonical_url="/products/<*>",
            selected_by="first_href",
        ),
        policy=PageOk(
            url="/policies/privacy-policy",
            canonical_url="/policies/<*>",
            selected_by="convention",
        ),
        cart_and_search=CartAndSearch(
            cart=PageOk(url="/cart", selected_by="convention"),
            search=SearchPageOk(
                url="/search?q=linen%20shirt",
                query="linen shirt",
                selected_by="product_title",
            ),
        ),
    )


def _partial_pages_doc() -> PagesDoc:
    """Return a :class:`PagesDoc` with product + search marked ``not_found``."""
    return PagesDoc(
        base_url="https://shop.example.com/",
        homepage=PageOk(url="/", selected_by="input"),
        collection=PageOk(
            url="/collections/all",
            canonical_url="/collections/<*>",
            selected_by="fallback_path",
        ),
        product=PageNotFound(reason="no_product_link"),
        policy=PageOk(
            url="/policies/privacy-policy",
            canonical_url="/policies/<*>",
            selected_by="convention",
        ),
        cart_and_search=CartAndSearch(
            cart=PageOk(url="/cart", selected_by="convention"),
            search=PageNotFound(reason="no_search_query"),
        ),
    )


def test_measurable_buckets_full_pages_doc() -> None:
    """Every ``ok`` bucket appears, in spec §5.6 order."""
    pages = _full_pages_doc()
    assert resume.measurable_buckets(pages) == [
        "homepage",
        "collection",
        "product",
        "policy",
        "cart_and_search.cart",
        "cart_and_search.search",
    ]


def test_measurable_buckets_drops_not_found() -> None:
    """``not_found`` buckets are excluded — they have no artifacts on disk."""
    pages = _partial_pages_doc()
    assert resume.measurable_buckets(pages) == [
        "homepage",
        "collection",
        "policy",
        "cart_and_search.cart",
    ]


def test_expected_artifacts_full_pages_doc(tmp_path: Path) -> None:
    """Every step lists the §5.7 file set for a fully-discovered run."""
    pages = _full_pages_doc()
    expected = resume.expected_artifacts(tmp_path, pages, no_rubric=False)

    assert expected["pages"] == [tmp_path / PAGES_JSON_FILENAME]

    assert expected["observation"] == [tmp_path / "observation" / "index.json"]
    assert expected["action"] == [tmp_path / "action" / "index.json"]

    assert expected["transition"] == [
        tmp_path / "transition" / "graph.json",
        tmp_path / "transition" / "trace.jsonl",
        tmp_path / "transition" / "node" / "index.json",
    ]
    assert expected["metrics"] == [tmp_path / "metrics.json"]


def test_expected_artifacts_waits_for_node_layer_indexes(tmp_path: Path) -> None:
    """Observation/action reuse is keyed by node-layer indexes."""
    pages = _partial_pages_doc()
    expected = resume.expected_artifacts(tmp_path, pages, no_rubric=False)

    assert expected["observation"] == [tmp_path / "observation" / "index.json"]
    assert expected["action"] == [tmp_path / "action" / "index.json"]


def test_expected_artifacts_no_pages_returns_node_indexes(tmp_path: Path) -> None:
    """``pages=None`` still exposes node-layer index paths for skip checks."""
    expected = resume.expected_artifacts(tmp_path, None, no_rubric=False)
    assert expected["pages"] == [tmp_path / PAGES_JSON_FILENAME]
    assert expected["observation"] == [tmp_path / "observation" / "index.json"]
    assert expected["action"] == [tmp_path / "action" / "index.json"]
    assert expected["transition"] == [
        tmp_path / "transition" / "graph.json",
        tmp_path / "transition" / "trace.jsonl",
        tmp_path / "transition" / "node" / "index.json",
    ]
    assert expected["metrics"] == [tmp_path / "metrics.json"]


def test_expected_artifacts_no_rubric_keeps_rubric_path(tmp_path: Path) -> None:
    """``--no-rubric`` writes a stub rubric file; the path set is unchanged."""
    pages = _full_pages_doc()
    with_rubric = resume.expected_artifacts(tmp_path, pages, no_rubric=False)
    no_rubric = resume.expected_artifacts(tmp_path, pages, no_rubric=True)
    assert with_rubric == no_rubric


def test_can_skip_true_when_all_files_present(tmp_path: Path) -> None:
    """All required files exist → ``can_skip`` returns ``True``."""
    pages = _full_pages_doc()
    expected = resume.expected_artifacts(tmp_path, pages, no_rubric=True)
    for paths in expected.values():
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
    for step in resume.STEPS:
        assert resume.can_skip(step, expected) is True


def test_can_skip_false_when_any_file_missing(tmp_path: Path) -> None:
    """Removing one observation file flips that step's skip to ``False``."""
    pages = _full_pages_doc()
    expected = resume.expected_artifacts(tmp_path, pages, no_rubric=True)
    for paths in expected.values():
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")

    # Delete one observation artifact and verify only ``observation`` flips.
    target = expected["observation"][0]
    target.unlink()
    assert resume.can_skip("observation", expected) is False
    assert resume.can_skip("pages", expected) is True
    assert resume.can_skip("action", expected) is True


def test_can_skip_missing_node_indexes_returns_false(tmp_path: Path) -> None:
    """Missing node-layer indexes cannot be skipped."""
    expected = resume.expected_artifacts(tmp_path, None, no_rubric=False)
    assert expected["observation"] == [tmp_path / "observation" / "index.json"]
    assert resume.can_skip("observation", expected) is False
    assert resume.can_skip("action", expected) is False


def test_can_skip_directory_does_not_satisfy_path(tmp_path: Path) -> None:
    """A directory at a required path does not count as a present file."""
    pages = _full_pages_doc()
    expected = resume.expected_artifacts(tmp_path, pages, no_rubric=True)
    # Materialize the metrics path as a directory rather than a file.
    metrics_path = expected["metrics"][0]
    metrics_path.mkdir(parents=True)
    assert resume.can_skip("metrics", expected) is False


def test_can_skip_unknown_step_raises_resume_error(tmp_path: Path) -> None:
    """An invalid step name fails loud."""
    expected = resume.expected_artifacts(tmp_path, None, no_rubric=False)
    with pytest.raises(ResumeError, match="unknown step"):
        resume.can_skip("not-a-step", expected)  # type: ignore[arg-type]
