"""Unit tests for :mod:`shop_explore.config`.

Covers the validation requirements from
``docs/impl/shop_explore_implementation.md`` T1.2 and the
relaxation introduced by ``docs/specs/harness/resume.md`` §5.6:

* Non-http URLs are rejected.
* ``max_iters <= 0`` is rejected.
* ``out_dir`` accepts missing, empty, or a prior workspace (resume);
  only a regular file is rejected.
* Defaults match the spec §4.1.
* ``ExploreResult`` round-trips and forbids unknown fields.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.config import FinalStatus
from shop_explore.config import (
    DEFAULT_MAX_ITERS,
    DEFAULT_TIMEOUT_SECONDS,
    ExploreConfig,
    ExploreResult,
)


def test_explore_config_defaults_match_spec() -> None:
    cfg = ExploreConfig(url="https://example-shop.com")
    assert cfg.url == "https://example-shop.com"
    assert cfg.out_dir is None
    assert cfg.runtime == "pi"
    assert cfg.max_iters == DEFAULT_MAX_ITERS
    assert cfg.timeout == DEFAULT_TIMEOUT_SECONDS


def test_explore_config_accepts_http_and_https() -> None:
    ExploreConfig(url="http://example-shop.com")
    ExploreConfig(url="https://example-shop.com/path?q=1")


@pytest.mark.parametrize(
    "bad_url",
    [
        "example-shop.com",
        "ftp://example-shop.com",
        "file:///etc/passwd",
        "https://",
        "https:///no-host",
        "",
    ],
)
def test_explore_config_rejects_non_http_url(bad_url: str) -> None:
    with pytest.raises(ValidationError):
        ExploreConfig(url=bad_url)


@pytest.mark.parametrize("bad", [0, -1, -100])
def test_explore_config_rejects_non_positive_max_iters(bad: int) -> None:
    with pytest.raises(ValidationError):
        ExploreConfig(url="https://example-shop.com", max_iters=bad)


@pytest.mark.parametrize("bad", [0.0, -1.0, -0.001])
def test_explore_config_rejects_non_positive_timeout(bad: float) -> None:
    with pytest.raises(ValidationError):
        ExploreConfig(url="https://example-shop.com", timeout=bad)


def test_explore_config_rejects_unknown_runtime() -> None:
    with pytest.raises(ValidationError):
        ExploreConfig(url="https://example-shop.com", runtime="gpt")  # type: ignore[arg-type]


def test_explore_config_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ExploreConfig(  # type: ignore[call-arg]
            url="https://example-shop.com", unknown="x"
        )


def test_explore_config_accepts_missing_out_dir(tmp_path: Path) -> None:
    cfg = ExploreConfig(url="https://example-shop.com", out_dir=tmp_path / "does-not-exist")
    assert cfg.out_dir is not None
    assert not cfg.out_dir.exists()


def test_explore_config_accepts_empty_out_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    cfg = ExploreConfig(url="https://example-shop.com", out_dir=empty)
    assert cfg.out_dir == empty


def test_explore_config_accepts_non_empty_out_dir_for_resume(tmp_path: Path) -> None:
    """Non-empty `out_dir` is accepted; the harness validates resume identity."""
    nonempty = tmp_path / "prior-run"
    nonempty.mkdir()
    (nonempty / "marker").write_text("hi")
    cfg = ExploreConfig(url="https://example-shop.com", out_dir=nonempty)
    assert cfg.out_dir == nonempty


def test_explore_config_rejects_out_dir_pointing_at_file(tmp_path: Path) -> None:
    file_path = tmp_path / "a.txt"
    file_path.write_text("hi")
    with pytest.raises(ValidationError, match="non-existent"):
        ExploreConfig(url="https://example-shop.com", out_dir=file_path)


def test_explore_config_force_resume_defaults_to_false() -> None:
    cfg = ExploreConfig(url="https://example-shop.com")
    assert cfg.force_resume is False


def test_explore_config_force_resume_can_be_set_true() -> None:
    cfg = ExploreConfig(url="https://example-shop.com", force_resume=True)
    assert cfg.force_resume is True


def test_explore_config_is_frozen() -> None:
    cfg = ExploreConfig(url="https://example-shop.com")
    with pytest.raises(ValidationError):
        cfg.max_iters = 5  # type: ignore[misc]


def test_explore_result_round_trip(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    result = ExploreResult(
        run_dir=tmp_path,
        manual_path=artifact / "manual.md",
        capabilities_path=artifact / "capabilities.json",
        stats_path=artifact / "stats.json",
        manifest_path=artifact / "manifest.json",
        prefetch_dir=artifact / "prefetch",
        final_status=FinalStatus.COMPLETED,
    )
    assert result.final_status is FinalStatus.COMPLETED
    again = ExploreResult.model_validate(result.model_dump())
    assert again == result


def test_explore_result_rejects_extra_fields(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ExploreResult(  # type: ignore[call-arg]
            run_dir=tmp_path,
            manual_path=tmp_path / "manual.md",
            capabilities_path=tmp_path / "capabilities.json",
            stats_path=tmp_path / "stats.json",
            manifest_path=tmp_path / "manifest.json",
            prefetch_dir=tmp_path / "prefetch",
            final_status=FinalStatus.COMPLETED,
            extra="x",
        )
