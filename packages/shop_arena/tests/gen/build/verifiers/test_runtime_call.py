"""Unit tests for ``shop_arena.gen.build.verifiers._runtime_call`` (impl plan T1.1).

The helper has three responsibilities — staging the sub-workspace,
invoking ``runtime.run_iteration``, and parsing the structured §9.3
``verdict.json`` with score → verdict coercion. The runtime call itself
is exercised by the verifier-level tests under T1.6; this file locks
down the staging layout and the verdict-parser behaviour.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

from harness.runtimes.base import RuntimeIterationResult
from harness.trajectory import Trajectory
from harness.verifiers import Verdict
from shop_arena.gen.build.verifiers._runtime_call import (
    parse_visual_verdict,
    run_visual_iteration,
    stage_sub_workspace,
)


def _write_verdict(path: Path, body: str) -> Path:
    """Write a verdict body to ``path`` and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _pass_body(*, score: float = 8.5, issues: list[dict[str, str]] | None = None) -> str:
    """Render a §9.3-shaped pass body."""
    return json.dumps(
        {
            "verdict": "pass",
            "score": score,
            "category_scores": {"structure": 8, "components": 7, "visual_tone": 9},
            "feedback": "",
            "pages_judged": 4,
            "issues": issues or [],
        },
    )


# ---------------------------------------------------------------------------
# parse_visual_verdict — the (a)-(e) coverage from the impl-plan task list.
# ---------------------------------------------------------------------------


def test_parse_visual_verdict_returns_pass_for_clean_body(tmp_path: Path) -> None:
    """(a) clean PASS verdict — no coercion, all fields propagate."""
    path = _write_verdict(tmp_path / "verdict.json", _pass_body(score=8.5))

    parsed = parse_visual_verdict(path, pass_threshold=7.0)

    assert parsed is not None
    assert parsed.verdict is Verdict.PASS
    assert parsed.score == 8.5  # noqa: PLR2004 -- mirrors fixture body
    assert parsed.pages_judged == 4  # noqa: PLR2004 -- mirrors fixture body
    assert parsed.coercion_reason is None
    assert parsed.issues == ()
    assert dict(parsed.category_scores) == {
        "structure": 8.0,
        "components": 7.0,
        "visual_tone": 9.0,
    }


def test_parse_visual_verdict_handles_fenced_json(tmp_path: Path) -> None:
    """(b) fenced ```json``` block survives the §9.3 forgiving parser."""
    fenced = "Here is the verdict.\n```json\n" + _pass_body() + "\n```\nThanks!"
    path = _write_verdict(tmp_path / "verdict.json", fenced)

    parsed = parse_visual_verdict(path, pass_threshold=7.0)

    assert parsed is not None
    assert parsed.verdict is Verdict.PASS


def test_parse_visual_verdict_returns_none_for_malformed_body(tmp_path: Path) -> None:
    """(c) malformed JSON → ``None`` (verifier maps that to FAIL)."""
    path = _write_verdict(tmp_path / "verdict.json", "{verdict: pass, ")

    assert parse_visual_verdict(path, pass_threshold=7.0) is None


def test_parse_visual_verdict_returns_none_when_file_missing(tmp_path: Path) -> None:
    """A missing file collapses to ``None`` rather than raising."""
    assert parse_visual_verdict(tmp_path / "nope.json", pass_threshold=7.0) is None


def test_parse_visual_verdict_coerces_pass_to_fail_below_threshold(
    tmp_path: Path,
) -> None:
    """(d) ``score < pass_threshold`` flips a ``pass`` token to FAIL."""
    path = _write_verdict(tmp_path / "verdict.json", _pass_body(score=5.5))

    parsed = parse_visual_verdict(path, pass_threshold=7.0)

    assert parsed is not None
    assert parsed.verdict is Verdict.FAIL
    assert parsed.coercion_reason is not None
    assert "5.50" in parsed.coercion_reason
    assert "7.00" in parsed.coercion_reason


def test_parse_visual_verdict_coerces_pass_to_fail_on_critical_issue(
    tmp_path: Path,
) -> None:
    """(e) any ``severity: critical`` issue forces FAIL even on PASS."""
    body = _pass_body(
        score=9.0,
        issues=[
            {
                "route": "/collections/outerwear",
                "viewport": "mobile",
                "screenshot": "screenshots/outerwear__mobile.png",
                "severity": "critical",
                "summary": "filter bar overflows the viewport",
                "capability": "collection.filters",
            },
        ],
    )
    path = _write_verdict(tmp_path / "verdict.json", body)

    parsed = parse_visual_verdict(path, pass_threshold=7.0)

    assert parsed is not None
    assert parsed.verdict is Verdict.FAIL
    assert parsed.coercion_reason == "critical-severity issue forces fail"
    assert len(parsed.issues) == 1
    assert parsed.issues[0].severity == "critical"


def test_parse_visual_verdict_preserves_fail_token(tmp_path: Path) -> None:
    """An emitted ``fail`` token is preserved; coercion only tightens."""
    body = json.dumps(
        {
            "verdict": "fail",
            "score": 9.5,  # high score does not upgrade fail
            "category_scores": {},
            "feedback": "homepage hero is missing the primary CTA",
            "pages_judged": 2,
            "issues": [],
        },
    )
    path = _write_verdict(tmp_path / "verdict.json", body)

    parsed = parse_visual_verdict(path, pass_threshold=7.0)

    assert parsed is not None
    assert parsed.verdict is Verdict.FAIL
    assert parsed.coercion_reason is None  # no coercion — agent emitted fail


def test_parse_visual_verdict_rejects_unknown_severity(tmp_path: Path) -> None:
    """An issue with a non-allowlisted severity tokenises to ``None``."""
    body = _pass_body(
        issues=[
            {
                "route": "/",
                "viewport": "desktop",
                "screenshot": "screenshots/home__desktop.png",
                "severity": "blocker",  # not in {critical, major, minor}
                "summary": "x",
                "capability": "home.hero",
            },
        ],
    )
    path = _write_verdict(tmp_path / "verdict.json", body)

    assert parse_visual_verdict(path, pass_threshold=7.0) is None


def test_parse_visual_verdict_rejects_non_numeric_score(tmp_path: Path) -> None:
    """``score`` must be a real number; booleans (``int`` subclass) are rejected."""
    body = json.dumps(
        {
            "verdict": "pass",
            "score": True,
            "category_scores": {},
            "feedback": "",
            "pages_judged": 1,
            "issues": [],
        },
    )
    path = _write_verdict(tmp_path / "verdict.json", body)

    assert parse_visual_verdict(path, pass_threshold=7.0) is None


# ---------------------------------------------------------------------------
# stage_sub_workspace — layout invariants per spec §5.2.1 step 4.
# ---------------------------------------------------------------------------


def test_stage_sub_workspace_lays_out_work_tree(tmp_path: Path) -> None:
    routes = {"base_url": "http://localhost:3000", "routes": ["/", "/collections"]}

    work = stage_sub_workspace(tmp_path, prompt="render the homepage", routes=routes)

    assert work == tmp_path / "work"
    assert (work / "iter").is_dir()
    assert (work / "prompt.md").read_text(encoding="utf-8") == "render the homepage"
    parsed_routes = json.loads((work / "routes.json").read_text(encoding="utf-8"))
    assert parsed_routes == routes


# ---------------------------------------------------------------------------
# run_visual_iteration — wires staging + runtime + parse together.
# ---------------------------------------------------------------------------


@dataclass
class _RecordingRuntime:
    """Stub runtime that records the call args and writes a verdict body."""

    verdict_body: str
    calls: list[dict[str, object]] = field(default_factory=list)

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        self.calls.append(
            {
                "run_dir": run_dir,
                "iter_dir": iter_dir,
                "prompt": prompt,
                "timeout": timeout,
            },
        )
        (run_dir / "verdict.json").write_text(self.verdict_body, encoding="utf-8")
        # The trajectory is opaque to the helper; tests only inspect the
        # recorded call args + the parsed verdict.
        now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        return RuntimeIterationResult(
            trajectory=Trajectory(
                iter_id="visual-stub",
                runtime="stub",
                started_at=now,
                ended_at=now,
                exit_code=0,
                prompt_sha256="0" * 64,
            ),
        )


def test_run_visual_iteration_dispatches_runtime_and_parses_verdict(
    tmp_path: Path,
) -> None:
    runtime = _RecordingRuntime(verdict_body=_pass_body(score=8.0))

    work, verdict = run_visual_iteration(
        runtime,
        parent_dir=tmp_path,
        prompt="judge the homepage",
        routes={"base_url": "http://localhost:3000", "routes": ["/"]},
        timeout_s=42.0,
        pass_threshold=7.0,
    )

    assert work == tmp_path / "work"
    assert verdict is not None
    assert verdict.verdict is Verdict.PASS
    assert len(runtime.calls) == 1
    call = runtime.calls[0]
    assert call["run_dir"] == work
    assert call["iter_dir"] == work / "iter"
    assert call["prompt"] == "judge the homepage"
    assert call["timeout"] == 42.0  # noqa: PLR2004 -- mirrors test arg
