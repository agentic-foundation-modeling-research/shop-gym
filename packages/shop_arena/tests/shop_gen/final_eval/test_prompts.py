"""Lint-only tests for the Phase 5 ``final_eval`` prompt template.

T6.2 from ``docs/impl/shop_gen_implementation.md`` requires one prompt
file under ``packages/shop_arena/src/shop_gen/final_eval/prompts/`` —
``quality_judge.md`` — feeding the post-build LLM judge that runs
after the harness loop exits and writes ``final_eval.json`` (spec
§5.5.5).

These tests are pure I/O over the in-repo prompt file; they never spawn
an LLM client and never load runtime config.
"""

from __future__ import annotations

from shop_gen.final_eval import load_quality_judge_prompt


def test_quality_judge_prompt_is_non_empty() -> None:
    """The ``quality_judge.md`` body must be present and non-empty."""
    body = load_quality_judge_prompt()
    assert body.strip(), "quality_judge.md: prompt file is empty"


def test_quality_judge_prompt_carries_required_format_slots() -> None:
    """The template must accept the slots T6.3 will fill in.

    The ``final_eval`` step renders ``base_url`` / ``capabilities`` /
    ``screenshots_table`` / ``failures_table`` via ``str.format()``;
    a missing placeholder would crash with ``KeyError`` at the first
    dispatch. The test exercises the format call directly with
    placeholder values to lock the contract.
    """
    body = load_quality_judge_prompt()
    rendered = body.format(
        base_url="http://127.0.0.1:54321",
        capabilities="{}",
        screenshots_table=(
            "| step | viewport | url | path |\n"
            "| --- | --- | --- | --- |\n"
            "| home | desktop | / | screenshots/home-desktop.png |"
        ),
        failures_table="_(none)_",
    )
    assert "http://127.0.0.1:54321" in rendered
    assert "screenshots/home-desktop.png" in rendered
    assert "_(none)_" in rendered


def test_quality_judge_prompt_describes_advisory_contract() -> None:
    """The prompt must orient the judge to the advisory, quality-only contract.

    Spec §5.5.5 fixes the post-build judge as:

    * **advisory** — never gates the run; the harness loop is the gate.
    * **quality-only** — no seed cross-comparison, no visual fidelity
      score; capabilities.json is the only ground truth.

    The exact wording can drift; this test asserts the *intent*
    survives, not the verbatim quote.
    """
    body = load_quality_judge_prompt().lower()
    must_mention = (
        "advisory",
        "quality-only",
        "capabilities",
    )
    missing = [token for token in must_mention if token not in body]
    assert not missing, (
        f"quality_judge.md must orient the judge to the spec §5.5.5 contract. "
        f"Missing key concept(s): {missing}."
    )


def test_quality_judge_prompt_emits_json_verdict_contract() -> None:
    """The prompt must instruct the judge to emit a ``pass``/``fail`` JSON verdict.

    T6.3 will parse ``{"verdict": "pass" | "fail", "feedback": "..."}``
    out of the LLM response (mirroring the build-loop ``quality_judge``
    parser); the prompt must lock that contract so the parser is not
    fighting the prompt.
    """
    body = load_quality_judge_prompt()
    assert '"verdict"' in body, (
        "quality_judge.md must instruct the judge to emit a `verdict` field."
    )
    assert "pass" in body and "fail" in body, (
        "quality_judge.md must spell out the `pass` / `fail` verdict alternatives."
    )


def test_load_quality_judge_prompt_is_cached() -> None:
    """Repeated loader calls must return the same string identity (cache).

    The loader is decorated with ``functools.cache``; the ``final_eval``
    step calls it once per run, but tests and ad-hoc callers should
    not re-read disk.
    """
    first = load_quality_judge_prompt()
    second = load_quality_judge_prompt()
    assert first is second, (
        "load_quality_judge_prompt: loader is not cached — "
        "expected identical object identity across calls."
    )
