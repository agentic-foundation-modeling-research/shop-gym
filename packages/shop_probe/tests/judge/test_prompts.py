"""Frozen fixture tests for ``judge/prompts/v1/`` (T4.7 — spec §5.5, §8.3, §5.8).

The shipped prompt template is the contract every :class:`JudgeCall`
references via ``prompt_hash`` per spec §5.8. These tests pin:

* the version string,
* the SHA-256 over the canonical byte form of the two prompt files,
* the required placeholders on the pairwise template,
* the spec §5.5 step 5 invariant that the prompt is *identical* for
  experimental ``(sandbox, source)`` and control ``(real, real)`` pair
  conditions (no condition-conditional branching in the template
  body).

Edits to ``judge/prompts/v1/*.md`` MUST bump the version directory AND
update the ``EXPECTED_V1_HASH`` constant below — that is the whole
point of pinning per spec §5.8.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from shop_probe.judge.prompts import (
    REQUIRED_PAIRWISE_PLACEHOLDERS,
    JudgePromptLoadError,
    JudgePromptSet,
    compute_content_hash,
    load_judge_prompts,
)
from shop_probe.report import JudgeCall

# --------------------------------------------------------------------------- #
# Pinned fixture — bump together with judge/prompts/v1/*.md.
# --------------------------------------------------------------------------- #

V1_DIR: Path = (
    Path(__file__).resolve().parent.parent.parent
    / "src"
    / "shop_probe"
    / "judge"
    / "prompts"
    / "v1"
)

EXPECTED_V1_HASH: str = "7b212e41f4146a18dea69b4c237781183d06dee1f20401bd539278b9765b6fc6"
"""SHA-256 of ``judge/prompts/v1/`` canonical byte form. Pin per spec §5.8."""

EXPECTED_V1_VERSION: str = "v1"


# --------------------------------------------------------------------------- #
# Pinned shape — version, hash, files present.
# --------------------------------------------------------------------------- #


def test_v1_files_exist() -> None:
    assert (V1_DIR / "system.md").is_file(), f"missing prompt file under {V1_DIR}"
    assert (V1_DIR / "pairwise.md").is_file(), f"missing prompt file under {V1_DIR}"


def test_v1_pinned_hash() -> None:
    system_bytes = (V1_DIR / "system.md").read_bytes()
    pairwise_bytes = (V1_DIR / "pairwise.md").read_bytes()
    actual = compute_content_hash("v1", system_bytes, pairwise_bytes)
    assert actual == EXPECTED_V1_HASH, (
        "judge/prompts/v1 hash drifted. Bump the version directory AND update EXPECTED_V1_HASH."
    )


def test_v1_loads_and_pins_metadata() -> None:
    prompts = load_judge_prompts()
    assert prompts.version == EXPECTED_V1_VERSION
    assert prompts.content_hash == EXPECTED_V1_HASH
    assert prompts.system_template.strip() != ""
    assert prompts.pairwise_template.strip() != ""


def test_v1_hash_matches_judgecall_pattern() -> None:
    """The shipped hash must satisfy :class:`JudgeCall.prompt_hash`'s regex.

    ``JudgeCall.prompt_hash`` is the field that pins this template per
    pairwise call (spec §5.6). If the loader ever returned a hash with
    the wrong shape, every report would fail validation.
    """
    pattern = JudgeCall.model_fields["prompt_hash"].metadata
    # Pattern lives in the Field metadata; assert directly against the regex
    # the schema enforces at validation time.
    assert re.fullmatch(r"[0-9a-f]{64}", EXPECTED_V1_HASH) is not None
    # Smoke: also build a JudgeCall using this hash to prove the schema accepts it.
    JudgeCall(
        task_id="t",
        pair_label=("a", "b"),
        judge_pick="A",
        truth="A",
        swap_consistent=True,
        evidence_cited=True,
        confidence=0.5,
        prompt_hash=EXPECTED_V1_HASH,
        response_text="{}",
    )
    assert pattern is not None  # pattern metadata is non-empty in pydantic v2


# --------------------------------------------------------------------------- #
# Required placeholders (spec §8.3).
# --------------------------------------------------------------------------- #


def test_v1_pairwise_template_has_required_placeholders() -> None:
    prompts = load_judge_prompts()
    for placeholder in REQUIRED_PAIRWISE_PLACEHOLDERS:
        assert f"${placeholder}" in prompts.pairwise_template or (
            "${" + placeholder + "}" in prompts.pairwise_template
        ), f"pairwise template missing placeholder ${placeholder}"


def test_v1_render_pairwise_substitutes_placeholders() -> None:
    prompts = load_judge_prompts()
    rendered = prompts.render_pairwise(
        task_description="TASK_DESC_MARKER",
        anonymized_trajectory_a="TRAJ_A_MARKER",
        anonymized_trajectory_b="TRAJ_B_MARKER",
    )
    assert "TASK_DESC_MARKER" in rendered
    assert "TRAJ_A_MARKER" in rendered
    assert "TRAJ_B_MARKER" in rendered
    # The literal JSON braces from spec §8.3 must survive substitution.
    assert '"pick"' in rendered
    assert '"confidence"' in rendered


# --------------------------------------------------------------------------- #
# Spec §5.5 step 5: prompt is identical across pair conditions.
# --------------------------------------------------------------------------- #


def test_v1_template_body_does_not_branch_on_pair_condition() -> None:
    """The judge must not see whether a pair is experimental or control.

    Spec §5.5 step 5: *"the prompt is identical for experimental and
    control pairs, and the judge does not know which condition it is
    in."* The structural form of the blinding is that
    :meth:`JudgePromptSet.render_pairwise` has no ``condition``
    argument and the template body itself never names the cohort
    bookkeeping fields. The system prompt does still describe the task
    as *"exactly one is real; the other is synthetic"* — that framing
    is the same across all pairs and is what the spec §8.3 SYSTEM
    block requires.
    """
    prompts = load_judge_prompts()
    forbidden_substrings = (
        "experimental",
        "control pair",
        "real_unpaired",
        "pair_id",
    )
    combined = (prompts.system_template + prompts.pairwise_template).lower()
    for token in forbidden_substrings:
        assert token not in combined, (
            f"prompt template leaks pair condition via {token!r}; "
            "spec §5.5 step 5 requires the judge to be blind to condition."
        )


def test_v1_render_identical_for_swapped_trajectory_inputs() -> None:
    """Rendering with two different trajectories must differ only in the slots.

    Reinforces the §5.5 step 5 blinding: the only condition-specific
    state the judge sees is which trajectory landed in slot A vs B,
    not any extra prompt text.
    """
    prompts = load_judge_prompts()
    rendered_one = prompts.render_pairwise(
        task_description="task",
        anonymized_trajectory_a="alpha",
        anonymized_trajectory_b="beta",
    )
    rendered_two = prompts.render_pairwise(
        task_description="task",
        anonymized_trajectory_a="beta",
        anonymized_trajectory_b="alpha",
    )
    # The two renderings differ only by swapping the two trajectory bodies.
    assert rendered_one != rendered_two
    assert rendered_one.replace("alpha", "X").replace("beta", "Y") == rendered_two.replace(
        "beta", "X"
    ).replace("alpha", "Y")


# --------------------------------------------------------------------------- #
# Loader error paths.
# --------------------------------------------------------------------------- #


def test_load_missing_version_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(JudgePromptLoadError, match="judge prompt directory not found"):
        load_judge_prompts(version="v999", root=tmp_path)


def test_load_missing_system_file_raises(tmp_path: Path) -> None:
    version_dir = tmp_path / "v1"
    version_dir.mkdir()
    (version_dir / "pairwise.md").write_text(
        "$task_description $anonymized_trajectory_a $anonymized_trajectory_b\n"
    )
    with pytest.raises(JudgePromptLoadError, match=r"missing prompt file.*system\.md"):
        load_judge_prompts(version="v1", root=tmp_path)


def test_load_missing_pairwise_file_raises(tmp_path: Path) -> None:
    version_dir = tmp_path / "v1"
    version_dir.mkdir()
    (version_dir / "system.md").write_text("system body\n")
    with pytest.raises(JudgePromptLoadError, match=r"missing prompt file.*pairwise\.md"):
        load_judge_prompts(version="v1", root=tmp_path)


def test_load_pairwise_missing_placeholder_raises(tmp_path: Path) -> None:
    version_dir = tmp_path / "v1"
    version_dir.mkdir()
    (version_dir / "system.md").write_text("system body\n")
    # Drop $anonymized_trajectory_b deliberately.
    (version_dir / "pairwise.md").write_text(
        "Task: $task_description\nA: $anonymized_trajectory_a\n"
    )
    with pytest.raises(JudgePromptLoadError, match="missing required placeholder"):
        load_judge_prompts(version="v1", root=tmp_path)


# --------------------------------------------------------------------------- #
# Schema invariants (round-trip + extra=forbid).
# --------------------------------------------------------------------------- #


def test_schema_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        JudgePromptSet(
            version="v1",
            content_hash="0" * 64,
            system_template="system",
            pairwise_template=(
                "$task_description $anonymized_trajectory_a $anonymized_trajectory_b"
            ),
            note="not allowed",  # type: ignore[call-arg]
        )


def test_schema_rejects_malformed_hash() -> None:
    with pytest.raises(ValidationError):
        JudgePromptSet(
            version="v1",
            content_hash="not-a-sha256",
            system_template="system",
            pairwise_template=(
                "$task_description $anonymized_trajectory_a $anonymized_trajectory_b"
            ),
        )


def test_compute_content_hash_is_deterministic() -> None:
    a = compute_content_hash("v1", b"system\n", b"pairwise\n")
    b = compute_content_hash("v1", b"system\n", b"pairwise\n")
    assert a == b
    # Sensitivity: any input change flips the digest.
    assert compute_content_hash("v2", b"system\n", b"pairwise\n") != a
    assert compute_content_hash("v1", b"system!\n", b"pairwise\n") != a
    assert compute_content_hash("v1", b"system\n", b"pairwise!\n") != a


def test_compute_content_hash_swap_files_changes_digest() -> None:
    """Framing must distinguish ``system.md`` bytes from ``pairwise.md`` bytes."""
    a = compute_content_hash("v1", b"alpha", b"beta")
    b = compute_content_hash("v1", b"beta", b"alpha")
    assert a != b
