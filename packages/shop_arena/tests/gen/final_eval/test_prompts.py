"""Lint-only tests for the Phase 5 ``final_eval`` prompt template.

T6.2 from ``docs/impl/shop_gen_implementation.md`` requires one prompt
file under ``packages/shop_arena/src/shop_arena/gen/final_eval/prompts/`` —
``quality_judge.md`` — feeding the post-build LLM judge that runs
after the harness loop exits and writes ``final_eval.json`` (spec
§5.5.5).

These tests are pure I/O over the in-repo prompt file; they never spawn
an LLM client and never load runtime config.
"""

from __future__ import annotations

from shop_arena.gen.final_eval import load_quality_judge_prompt, load_visual_sweep_prompt


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


def test_visual_sweep_prompt_is_non_empty() -> None:
    """The ``visual_sweep.md`` body must be present and non-empty."""
    body = load_visual_sweep_prompt()
    assert body.strip(), "visual_sweep.md: prompt file is empty"


def test_visual_sweep_prompt_carries_required_format_slots() -> None:
    """The visual-sweep template must accept the six T5.2 slots.

    Spec §9.4 mirrors §9.2 with the bucket axis: the driver renders
    ``base_url`` / ``bucket`` / ``capabilities_slice`` / ``route_list`` /
    ``verdict_schema`` / ``prior_feedback_or_empty`` per bucket. A
    missing placeholder would crash ``str.format`` at the first
    dispatch; a stray literal ``{`` would crash with a different
    error. Exercise the format call directly with placeholder values.
    """
    body = load_visual_sweep_prompt()
    rendered = body.format(
        base_url="http://localhost:3000",
        bucket="homepage",
        capabilities_slice="{}",
        route_list="- /",
        verdict_schema="{}",
        prior_feedback_or_empty="",
    )
    assert "http://localhost:3000" in rendered
    assert "homepage" in rendered
    assert "- /" in rendered


def test_visual_sweep_prompt_describes_advisory_contract() -> None:
    """The visual-sweep prompt must orient the reviewer to the advisory contract.

    Spec §9.4 distinguishes the sweep from the gating ``visual_judge``
    prompt: the verdict is recorded into ``final_eval.json`` for human
    review and never gates the run. The exact wording can drift; this
    test asserts the *intent* survives, not the verbatim quote.
    """
    body = load_visual_sweep_prompt().lower()
    assert "advisory" in body, (
        "visual_sweep.md must orient the reviewer to the advisory contract (spec §9.4)."
    )
    assert "human review" in body, (
        "visual_sweep.md must surface the human-review framing "
        "distinct from the gating visual_judge prompt (spec §9.4)."
    )


def test_visual_sweep_prompt_calls_out_per_bucket_scope() -> None:
    """The visual-sweep prompt must tell the agent it is scoped to one bucket.

    Spec §9.4 + §5.6: the driver fans one nested iteration out per
    page bucket, so the prompt must scope the agent to its bucket's
    routes only and call out that the capabilities slice has been
    pre-filtered.
    """
    body = load_visual_sweep_prompt()
    flat = " ".join(body.split()).lower()
    assert "pre-filtered" in flat, (
        "visual_sweep.md must call out that the capabilities slice has "
        "been pre-filtered for this bucket (spec §9.4)."
    )
    assert "bucket" in flat, (
        "visual_sweep.md must reference the page-bucket axis so the "
        "agent understands why the slice is narrow (spec §9.4)."
    )


def test_visual_sweep_prompt_emits_structured_verdict_schema_slot() -> None:
    """The visual-sweep prompt must keep the §9.3 structured-score schema.

    Spec §9.4 uses the same ``verdict.json`` schema as the build-loop
    ``visual_judge`` so the merged report can compare buckets on a
    common scale. The template references ``score`` / ``severity`` /
    ``pages_judged`` so the reviewer sees the contract before the
    schema block; the schema body itself flows in via the
    ``{verdict_schema}`` slot.
    """
    body = load_visual_sweep_prompt()
    assert "{verdict_schema}" in body, (
        "visual_sweep.md must include the {verdict_schema} slot so the "
        "§9.3 schema body lands in the rendered prompt."
    )
    flat = body.lower()
    for token in ("score", "severity", "pages_judged"):
        assert token in flat, (
            f"visual_sweep.md must reference `{token}` from the structured "
            "verdict contract (spec §9.3 + §9.4)."
        )


def test_visual_sweep_prompt_forbids_networkidle_and_run_code() -> None:
    """The final visual sweep must avoid known hanging browser patterns."""
    body = load_visual_sweep_prompt().lower()
    assert "networkidle" in body, (
        "visual_sweep.md must explicitly warn against networkidle waits; "
        "Hydrogen pages can keep background requests open until the sweep times out."
    )
    assert "run-code" in body, (
        "visual_sweep.md must steer the agent away from raw run-code navigation "
        "and toward the playwright skill's bounded built-in commands."
    )


def test_visual_sweep_prompt_writes_verdict_early() -> None:
    """The final sweep prompt must preserve partial verdicts on timeout."""
    body = load_visual_sweep_prompt().lower()
    assert "write a first draft" in body
    assert "./verdict.json" in body
    assert "successful render" in body


def test_load_visual_sweep_prompt_is_cached() -> None:
    """Repeated loader calls must return the same string identity (cache)."""
    first = load_visual_sweep_prompt()
    second = load_visual_sweep_prompt()
    assert first is second, (
        "load_visual_sweep_prompt: loader is not cached — "
        "expected identical object identity across calls."
    )
