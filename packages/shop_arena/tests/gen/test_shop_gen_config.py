"""Unit tests for :mod:`shop_arena.gen.config`.

Covers the validation requirements from
``docs/impl/shop_gen_implementation.md`` T1.1:

* ``seeds`` requires at least one entry.
* ``max_iters <= 0`` is rejected.
* Unknown ``image_backend`` values are rejected.
* Unknown ``runtime`` values are rejected.
* Defaults match spec §4.1.
* :class:`ShopGenResult` round-trips and forbids unknown fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from shop_arena.gen.config import (
    DEFAULT_COLLECTIONS,
    DEFAULT_FINAL_EVAL_MAX_COLLECTIONS,
    DEFAULT_FINAL_EVAL_MAX_PAGES,
    DEFAULT_FINAL_EVAL_PRODUCTS_PER_COLLECTION,
    DEFAULT_FINAL_EVAL_VISUAL_TIMEOUT_S,
    DEFAULT_IMAGE_BACKEND,
    DEFAULT_IMAGE_CONCURRENCY,
    DEFAULT_IMAGE_SIZE,
    DEFAULT_IMAGES_PER_PRODUCT,
    DEFAULT_JUDGES,
    DEFAULT_MAX_ITERS,
    DEFAULT_MODEL_BY_RUNTIME,
    DEFAULT_PRODUCTS_PER_COLLECTION,
    DEFAULT_RUNTIME,
    DEFAULT_VISUAL_JUDGE_MAX_CONCURRENCY,
    DEFAULT_VISUAL_JUDGE_PASS_THRESHOLD,
    DEFAULT_VISUAL_RETRY_BUDGET,
    IMAGE_SIZES,
    KNOWN_JUDGES,
    CatalogConfig,
    RuntimeName,
    ShopGenConfig,
    ShopGenResult,
    default_model_for,
)


def _seed(tmp_path: Path, name: str = "seed-a") -> Path:
    """Materialise a temp directory shaped like a shop_arena.explore seed."""
    seed = tmp_path / name
    seed.mkdir()
    return seed


# --------------------------------------------------------------------------- #
# CatalogConfig
# --------------------------------------------------------------------------- #


def test_catalog_config_defaults_match_spec() -> None:
    cat = CatalogConfig()
    assert cat.collections == DEFAULT_COLLECTIONS
    assert cat.products_per_collection == DEFAULT_PRODUCTS_PER_COLLECTION
    assert cat.images_per_product == DEFAULT_IMAGES_PER_PRODUCT


@pytest.mark.parametrize(
    "field",
    ["collections", "products_per_collection", "images_per_product"],
)
@pytest.mark.parametrize("bad", [0, -1, -42])
def test_catalog_config_rejects_non_positive_counts(field: str, bad: int) -> None:
    with pytest.raises(ValidationError):
        CatalogConfig(**{field: bad})  # type: ignore[arg-type]


def test_catalog_config_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CatalogConfig(unknown=1)  # type: ignore[call-arg]


def test_catalog_config_is_frozen() -> None:
    cat = CatalogConfig()
    with pytest.raises(ValidationError):
        cat.collections = 5  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# ShopGenConfig — defaults
# --------------------------------------------------------------------------- #


def test_shop_gen_config_defaults_match_spec(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed])
    assert cfg.seeds == (seed,)
    assert cfg.out_dir is None
    assert cfg.name is None
    assert cfg.runtime == DEFAULT_RUNTIME
    assert cfg.model is None
    assert cfg.max_iters == DEFAULT_MAX_ITERS
    assert cfg.image_backend == DEFAULT_IMAGE_BACKEND
    assert cfg.image_model is None
    assert cfg.image_size == DEFAULT_IMAGE_SIZE
    assert cfg.image_concurrency == DEFAULT_IMAGE_CONCURRENCY
    assert cfg.catalog == CatalogConfig()
    assert cfg.visual_retry_budget == DEFAULT_VISUAL_RETRY_BUDGET
    assert cfg.judges == DEFAULT_JUDGES
    assert cfg.visual_judge_pass_threshold == DEFAULT_VISUAL_JUDGE_PASS_THRESHOLD
    assert cfg.visual_judge_max_concurrency == DEFAULT_VISUAL_JUDGE_MAX_CONCURRENCY
    assert cfg.final_eval_max_collections == DEFAULT_FINAL_EVAL_MAX_COLLECTIONS
    assert cfg.final_eval_products_per_collection == DEFAULT_FINAL_EVAL_PRODUCTS_PER_COLLECTION
    assert cfg.final_eval_max_pages == DEFAULT_FINAL_EVAL_MAX_PAGES
    assert cfg.final_eval_visual_timeout_s == DEFAULT_FINAL_EVAL_VISUAL_TIMEOUT_S


def test_default_model_for_returns_per_runtime_pinned_opus() -> None:
    """Per-runtime defaults pin Opus in each runtime's native grammar."""
    assert default_model_for("pi") == "anthropic/claude-opus-4-7"
    assert default_model_for("claude_code") == "opus"


def test_default_model_by_runtime_covers_every_runtime_name() -> None:
    """Every ``RuntimeName`` literal has an entry in the defaults map."""
    assert set(DEFAULT_MODEL_BY_RUNTIME.keys()) == set(get_args(RuntimeName))


def test_shop_gen_config_rejects_pi_grammar_model_with_claude_code_runtime(
    tmp_path: Path,
) -> None:
    """Provider-prefixed IDs (``anthropic/...``) are pi grammar; reject for claude_code."""
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError, match="provider-prefixed"):
        ShopGenConfig(
            seeds=[seed],
            runtime="claude_code",
            model="anthropic/claude-opus-4-7",
        )


def test_shop_gen_config_accepts_claude_code_aliases(tmp_path: Path) -> None:
    """Bare aliases like ``opus`` are valid `claude` CLI grammar."""
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed], runtime="claude_code", model="opus")
    assert cfg.model == "opus"


def test_shop_gen_config_default_max_iters_is_30() -> None:
    """Spec §4.1: build-loop budget defaults to 30."""
    assert DEFAULT_MAX_ITERS == 30


def test_shop_gen_config_default_image_backend_is_placeholder() -> None:
    """Spec §4.1: v0.1 ships ``placeholder`` as the default backend."""
    assert DEFAULT_IMAGE_BACKEND == "placeholder"


# --------------------------------------------------------------------------- #
# ShopGenConfig — seeds validation
# --------------------------------------------------------------------------- #


def test_shop_gen_config_rejects_empty_seeds() -> None:
    with pytest.raises(ValidationError):
        ShopGenConfig(seeds=[])


def test_shop_gen_config_accepts_single_seed_path(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=seed)  # type: ignore[arg-type]
    assert cfg.seeds == (seed,)


def test_shop_gen_config_accepts_single_seed_string(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=str(seed))  # type: ignore[arg-type]
    assert cfg.seeds == (seed,)


def test_shop_gen_config_accepts_multiple_seeds(tmp_path: Path) -> None:
    a = _seed(tmp_path, "a")
    b = _seed(tmp_path, "b")
    c = _seed(tmp_path, "c")
    cfg = ShopGenConfig(seeds=[a, b, c])
    assert cfg.seeds == (a, b, c)


def test_shop_gen_config_coerces_string_seeds_to_paths(tmp_path: Path) -> None:
    a = _seed(tmp_path, "a")
    b = _seed(tmp_path, "b")
    cfg = ShopGenConfig(seeds=[str(a), str(b)])
    assert cfg.seeds == (a, b)
    assert all(isinstance(s, Path) for s in cfg.seeds)


def test_shop_gen_config_accepts_missing_seed_path(tmp_path: Path) -> None:
    """A non-existent seed path is accepted at construction time.

    The orchestrator re-checks before reading; constructing the config
    is purely a typed-validation step.
    """
    missing = tmp_path / "no-such-seed"
    cfg = ShopGenConfig(seeds=[missing])
    assert cfg.seeds == (missing,)


def test_shop_gen_config_rejects_seed_pointing_at_file(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hi")
    with pytest.raises(ValidationError, match="must be a directory"):
        ShopGenConfig(seeds=[f])


def test_shop_gen_config_makes_relative_seed_absolute_against_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relative seed paths are made absolute against cwd at construction time.

    Storing them absolute is what keeps
    :func:`shop_arena.gen.steps.state._resolve_input_path` from later
    re-rooting them under ``out_dir`` and crashing at fingerprint time.
    """
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    cfg = ShopGenConfig(seeds=[Path("seed")])
    assert cfg.seeds[0].is_absolute()
    assert cfg.seeds[0] == (tmp_path / "seed").absolute()


def test_shop_gen_config_preserves_absolute_seed_paths(tmp_path: Path) -> None:
    """Already-absolute seed paths are stored verbatim (no resolve symlinks)."""
    seed = tmp_path / "seed"
    seed.mkdir()
    cfg = ShopGenConfig(seeds=[seed])
    assert cfg.seeds[0] == seed


# --------------------------------------------------------------------------- #
# ShopGenConfig — scalar validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", [0, -1, -100])
def test_shop_gen_config_rejects_non_positive_max_iters(tmp_path: Path, bad: int) -> None:
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError):
        ShopGenConfig(seeds=[seed], max_iters=bad)


def test_shop_gen_config_rejects_unknown_image_backend(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError):
        ShopGenConfig(seeds=[seed], image_backend="dalle")  # type: ignore[arg-type]


def test_shop_gen_config_rejects_unknown_image_size(tmp_path: Path) -> None:
    """Closed-set ``image_size`` rejects values outside :data:`IMAGE_SIZES`."""
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError, match="image_size"):
        ShopGenConfig(seeds=[seed], image_size="999x999")


@pytest.mark.parametrize("good", sorted(IMAGE_SIZES))
def test_shop_gen_config_accepts_every_known_image_size(
    tmp_path: Path,
    good: str,
) -> None:
    """Every value in :data:`IMAGE_SIZES` round-trips."""
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed], image_size=good)
    assert cfg.image_size == good


@pytest.mark.parametrize("bad", [0, -1, -42])
def test_shop_gen_config_rejects_non_positive_image_concurrency(
    tmp_path: Path,
    bad: int,
) -> None:
    """``image_concurrency`` must be strictly positive (semaphore precondition)."""
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError):
        ShopGenConfig(seeds=[seed], image_concurrency=bad)


def test_shop_gen_config_accepts_image_model_string(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed], image_model="gpt-image-2")
    assert cfg.image_model == "gpt-image-2"


def test_shop_gen_config_openai_backend_requires_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``image_backend='openai'`` without ``OPENAI_API_KEY`` is rejected at config time."""
    seed = _seed(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        ShopGenConfig(seeds=[seed], image_backend="openai")


def test_shop_gen_config_openai_backend_accepts_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``OPENAI_API_KEY`` set, the openai backend passes validation."""
    seed = _seed(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = ShopGenConfig(seeds=[seed], image_backend="openai")
    assert cfg.image_backend == "openai"


def test_shop_gen_config_rejects_unknown_runtime(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError):
        ShopGenConfig(seeds=[seed], runtime="gpt")  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [-1, -3, -42])
def test_shop_gen_config_rejects_negative_visual_retry_budget(
    tmp_path: Path,
    bad: int,
) -> None:
    """Spec §5.4: ``visual_retry_budget`` is non-negative; ``0`` is a valid disable."""
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError):
        ShopGenConfig(seeds=[seed], visual_retry_budget=bad)


@pytest.mark.parametrize("good", [0, 1, 5, 100])
def test_shop_gen_config_accepts_non_negative_visual_retry_budget(
    tmp_path: Path,
    good: int,
) -> None:
    """Spec §5.4: ``0`` disables the budget; positive values cap retries."""
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed], visual_retry_budget=good)
    assert cfg.visual_retry_budget == good


@pytest.mark.parametrize("bad", [-0.1, -1.0, -42.0])
def test_shop_gen_config_rejects_negative_visual_judge_pass_threshold(
    tmp_path: Path,
    bad: float,
) -> None:
    """Impl plan T3.6 / spec §9.3: pass threshold must be non-negative."""
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError):
        ShopGenConfig(seeds=[seed], visual_judge_pass_threshold=bad)


@pytest.mark.parametrize("good", [0.0, 5.5, 7.0, 9.9, 10.0])
def test_shop_gen_config_accepts_non_negative_visual_judge_pass_threshold(
    tmp_path: Path,
    good: float,
) -> None:
    """Impl plan T3.6: any non-negative score floor round-trips."""
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed], visual_judge_pass_threshold=good)
    assert cfg.visual_judge_pass_threshold == good


@pytest.mark.parametrize("bad", [0, -1, -3])
def test_shop_gen_config_rejects_non_positive_visual_judge_max_concurrency(
    tmp_path: Path,
    bad: int,
) -> None:
    """Impl plan T3.6 / spec §5.6: fan-out worker count must be strictly positive."""
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError):
        ShopGenConfig(seeds=[seed], visual_judge_max_concurrency=bad)


@pytest.mark.parametrize("good", [1, 3, 6, 16])
def test_shop_gen_config_accepts_positive_visual_judge_max_concurrency(
    tmp_path: Path,
    good: int,
) -> None:
    """Impl plan T3.6: positive worker counts round-trip."""
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed], visual_judge_max_concurrency=good)
    assert cfg.visual_judge_max_concurrency == good



# --------------------------------------------------------------------------- #
# ShopGenConfig — final-eval visual sweep caps (impl plan T5.4, spec §5.6.1)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "field",
    [
        "final_eval_max_collections",
        "final_eval_products_per_collection",
        "final_eval_max_pages",
    ],
)
@pytest.mark.parametrize("bad", [0, -1, -42])
def test_shop_gen_config_rejects_non_positive_final_eval_caps(
    tmp_path: Path,
    field: str,
    bad: int,
) -> None:
    """Impl plan T5.4 / spec §5.6.1: per-bucket caps must be strictly positive."""
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError):
        ShopGenConfig(seeds=[seed], **{field: bad})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    [
        "final_eval_max_collections",
        "final_eval_products_per_collection",
        "final_eval_max_pages",
    ],
)
@pytest.mark.parametrize("good", [1, 3, 8, 64])
def test_shop_gen_config_accepts_positive_final_eval_caps(
    tmp_path: Path,
    field: str,
    good: int,
) -> None:
    """Impl plan T5.4: positive cap values round-trip."""
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed], **{field: good})  # type: ignore[arg-type]
    assert getattr(cfg, field) == good


@pytest.mark.parametrize("bad", [0.0, -0.1, -42.0])
def test_shop_gen_config_rejects_non_positive_final_eval_visual_timeout(
    tmp_path: Path,
    bad: float,
) -> None:
    """Impl plan T5.4 / spec §5.6: per-bucket timeout must be strictly positive."""
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError):
        ShopGenConfig(seeds=[seed], final_eval_visual_timeout_s=bad)


@pytest.mark.parametrize("good", [0.5, 60.0, 900.0, 3600.0])
def test_shop_gen_config_accepts_positive_final_eval_visual_timeout(
    tmp_path: Path,
    good: float,
) -> None:
    """Impl plan T5.4: positive timeouts round-trip."""
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed], final_eval_visual_timeout_s=good)
    assert cfg.final_eval_visual_timeout_s == good

# --------------------------------------------------------------------------- #
# ShopGenConfig — judges validation (impl plan T3.1, spec §5.5)
# --------------------------------------------------------------------------- #


def test_known_judges_matches_spec_section_5_5() -> None:
    """Spec §5.5: closed set of three LLM judges."""
    assert (
        frozenset(
            {"visual_judge", "quality_judge", "cross_task_consistency"},
        )
        == KNOWN_JUDGES
    )


def test_default_judges_is_full_known_set() -> None:
    """Spec §5.5: defaults to the full LLM-judge set (every known judge)."""
    assert DEFAULT_JUDGES == KNOWN_JUDGES


def test_shop_gen_config_default_judges_match_spec(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed])
    assert cfg.judges == DEFAULT_JUDGES


def test_shop_gen_config_accepts_subset_of_judges(tmp_path: Path) -> None:
    """Spec §5.5: a subset of known judges is a valid selection."""
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(
        seeds=[seed],
        judges=frozenset({"visual_judge", "quality_judge"}),
    )
    assert cfg.judges == frozenset({"visual_judge", "quality_judge"})


def test_shop_gen_config_accepts_empty_judges(tmp_path: Path) -> None:
    """Spec §5.5 + CLI ``--judges none``: empty set disables every LLM judge."""
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed], judges=frozenset())
    assert cfg.judges == frozenset()


def test_shop_gen_config_coerces_set_judges_to_frozenset(tmp_path: Path) -> None:
    """Mutable ``set`` inputs coerce to ``frozenset`` (frozen-config requirement)."""
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed], judges={"visual_judge"})  # type: ignore[arg-type]
    assert isinstance(cfg.judges, frozenset)
    assert cfg.judges == frozenset({"visual_judge"})


def test_shop_gen_config_coerces_list_judges_to_frozenset(tmp_path: Path) -> None:
    """List inputs coerce to ``frozenset`` and de-duplicate."""
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(
        seeds=[seed],
        judges=["visual_judge", "visual_judge", "quality_judge"],  # type: ignore[arg-type]
    )
    assert cfg.judges == frozenset({"visual_judge", "quality_judge"})


def test_shop_gen_config_rejects_unknown_judge_name(tmp_path: Path) -> None:
    """T3.1: unknown judge name raises with the offending token in the message."""
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError, match="bogus"):
        ShopGenConfig(
            seeds=[seed],
            judges=frozenset({"visual_judge", "bogus"}),
        )


def test_shop_gen_config_rejects_rule_verifier_in_judges(tmp_path: Path) -> None:
    """Spec §5.5: rule verifiers are not selectable; only LLM judges."""
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError, match="tsc"):
        ShopGenConfig(
            seeds=[seed],
            judges=frozenset({"tsc", "visual_judge"}),
        )


def test_shop_gen_config_unknown_judge_error_lists_known_set(tmp_path: Path) -> None:
    """Error message should help the user by enumerating valid names."""
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError) as excinfo:
        ShopGenConfig(seeds=[seed], judges=frozenset({"nope"}))
    msg = str(excinfo.value)
    assert "nope" in msg
    assert "visual_judge" in msg


def test_shop_gen_config_rejects_empty_name(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError, match="non-empty"):
        ShopGenConfig(seeds=[seed], name="   ")


def test_shop_gen_config_accepts_explicit_name(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed], name="lumen-thread")
    assert cfg.name == "lumen-thread"


def test_shop_gen_config_accepts_none_model_to_use_runtime_default(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed], model=None)
    assert cfg.model is None


def test_shop_gen_config_accepts_explicit_catalog(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    n_collections = 4
    n_products = 5
    n_images = 1
    cfg = ShopGenConfig(
        seeds=[seed],
        catalog=CatalogConfig(
            collections=n_collections,
            products_per_collection=n_products,
            images_per_product=n_images,
        ),
    )
    assert cfg.catalog.collections == n_collections
    assert cfg.catalog.products_per_collection == n_products
    assert cfg.catalog.images_per_product == n_images


def test_shop_gen_config_rejects_extra_fields(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    with pytest.raises(ValidationError):
        ShopGenConfig(seeds=[seed], unknown="x")  # type: ignore[call-arg]


def test_shop_gen_config_is_frozen(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    cfg = ShopGenConfig(seeds=[seed])
    with pytest.raises(ValidationError):
        cfg.max_iters = 5  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# ShopGenResult
# --------------------------------------------------------------------------- #


def _result(out_dir: Path) -> ShopGenResult:
    return ShopGenResult(
        out_dir=out_dir,
        manual_dir=out_dir / "manual",
        identity_path=out_dir / "identity.json",
        data_dir=out_dir / "data",
        hydrogen_dir=out_dir / "hydrogen",
        data_validation_path=out_dir / "data_validation.json",
        final_eval_path=out_dir / "final_eval.json",
        build_run_dir=out_dir / "runs" / "build",
    )


def test_shop_gen_result_round_trip(tmp_path: Path) -> None:
    result = _result(tmp_path)
    again = ShopGenResult.model_validate(result.model_dump())
    assert again == result


def test_shop_gen_result_rejects_extra_fields(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ShopGenResult(  # type: ignore[call-arg]
            out_dir=tmp_path,
            manual_dir=tmp_path / "manual",
            identity_path=tmp_path / "identity.json",
            data_dir=tmp_path / "data",
            hydrogen_dir=tmp_path / "hydrogen",
            data_validation_path=tmp_path / "data_validation.json",
            final_eval_path=tmp_path / "final_eval.json",
            build_run_dir=tmp_path / "runs" / "build",
            extra="x",
        )


def test_shop_gen_result_is_frozen(tmp_path: Path) -> None:
    result = _result(tmp_path)
    with pytest.raises(ValidationError):
        result.out_dir = tmp_path / "other"  # type: ignore[misc]
