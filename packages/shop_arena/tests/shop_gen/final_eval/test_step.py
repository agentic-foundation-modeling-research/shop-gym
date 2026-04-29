"""Unit tests for :mod:`shop_gen.final_eval.step` (T6.3).

Drives :class:`FinalEvalStep` through stub implementations of the three
injection seams (``DevServerFactory``, ``BrowserDriver``,
:class:`~harness.runtimes.LLMCompleter`) so the advisory verdict shape
is locked in CI without booting Playwright or calling a real model.

Spec contract under test (``docs/specs/shop_arena/shop_gen.md`` §5.5.5):

* The step writes ``<out_dir>/final_eval.json`` with screenshot paths
  + LLM verdict.
* The step is **advisory** — a ``fail`` verdict, an LLM transport error,
  a parse error, a missing capabilities document, and a missing
  hydrogen tree never block the run.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from harness.runtimes.base import RuntimeIterationResult
from harness.trajectory import Trajectory
from shop_gen.build.verifiers._task_routes import BucketCaps
from shop_gen.config import ShopGenConfig
from shop_gen.final_eval.playwright_smoke import (
    Screenshot,
    SmokeAction,
    SmokeFailure,
    SmokeFlow,
)
from shop_gen.final_eval.step import FinalEvalStep, run_final_eval
from shop_gen.pipeline import list_steps
from shop_gen.steps.base import FileInput, StepContext, StepInput

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

_DATA_FIXTURE_DIR: Final[Path] = (
    Path(__file__).resolve().parent.parent / "data_synth" / "fixtures" / "sandbox_shop_v0"
)
"""Canonical M4 dataset fixture (re-used as the M5 substrate)."""

_BASE_URL: Final[str] = "http://127.0.0.1:54321"
"""Stub base URL the fake dev server reports."""

_EXPECTED_SCREENSHOT_COUNT: Final[int] = 10
"""Five spec §5.5.5 smoke steps x two default viewports."""

_PASS_RESPONSE: Final[str] = '```json\n{"verdict": "pass", "feedback": "looks good"}\n```\n'
_FAIL_RESPONSE: Final[str] = (
    '```json\n{"verdict": "fail", "feedback": "homepage missing hero section"}\n```\n'
)


# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def _stub_dev_server_factory(hydrogen_dir: Path) -> Iterator[str]:
    """Stub :class:`DevServerFactory` — yields :data:`_BASE_URL`, no subprocess."""
    assert hydrogen_dir.is_dir()
    yield _BASE_URL


def _stub_browser_driver(
    *,
    base_url: str,
    flow: SmokeFlow,
    screenshots_dir: Path,
) -> tuple[tuple[Screenshot, ...], tuple[SmokeFailure, ...]]:
    """Stub :class:`BrowserDriver` — fabricates one PNG per (step, viewport) pair."""
    screenshots: list[Screenshot] = []
    for step in flow.steps:
        for viewport in flow.viewports:
            path = screenshots_dir / f"{step.name}-{viewport.name}.png"
            path.write_bytes(b"PNGSTUB\n")
            final_url = (
                f"{base_url}/checkout?session=stub"
                if step.action is SmokeAction.CHECKOUT_REDIRECT
                else f"{base_url}{step.url}"
            )
            screenshots.append(
                Screenshot(
                    step=step.name,
                    viewport=viewport.name,
                    path=path,
                    url=final_url,
                ),
            )
    return tuple(screenshots), ()


def _failing_browser_driver(
    *,
    base_url: str,
    flow: SmokeFlow,
    screenshots_dir: Path,
) -> tuple[tuple[Screenshot, ...], tuple[SmokeFailure, ...]]:
    """Stub driver that fails the ``add_to_cart`` step."""
    screenshots: list[Screenshot] = []
    failures: list[SmokeFailure] = []
    for step in flow.steps:
        for viewport in flow.viewports:
            if step.name == "add_to_cart":
                failures.append(
                    SmokeFailure(
                        step=step.name,
                        viewport=viewport.name,
                        error="add-to-cart selector not found",
                    ),
                )
                continue
            path = screenshots_dir / f"{step.name}-{viewport.name}.png"
            path.write_bytes(b"PNGSTUB\n")
            screenshots.append(
                Screenshot(
                    step=step.name,
                    viewport=viewport.name,
                    path=path,
                    url=f"{base_url}{step.url}",
                ),
            )
    return tuple(screenshots), tuple(failures)


class _StubCompleter:
    """Stub :class:`LLMCompleter` that returns a canned response."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[str] = []

    def complete(self, prompt: str, *, timeout: float) -> str:
        del timeout
        self.calls.append(prompt)
        return self.response


def _stub_visual_sweep_runner(
    *,
    out_dir: Path,
    data_dir: Path,
    hydrogen_dir: Path,
    runtime: Any,
    dev_server_factory: Any,
    capabilities: Any,
    prompt_template: str,
    timeout_s: float,
    max_concurrency: int,
    pass_threshold: float,
    caps: Any,
) -> dict[str, Any]:
    """Stub :class:`VisualSweepRunner` that fabricates a clean per-bucket payload."""
    del (
        data_dir,
        hydrogen_dir,
        runtime,
        dev_server_factory,
        capabilities,
        prompt_template,
        timeout_s,
        max_concurrency,
        pass_threshold,
        caps,
    )
    visual_eval = out_dir / "visual_eval"
    (visual_eval / "screenshots" / "homepage" / "home").mkdir(parents=True)
    (visual_eval / "screenshots" / "homepage" / "home" / "desktop.png").write_bytes(
        b"PNGSTUB\n",
    )
    report_path = visual_eval / "report.md"
    report_path.write_text("# Visual sweep report\n\nstub body\n", encoding="utf-8")
    return {
        "base_url": _BASE_URL,
        "buckets": ["homepage"],
        "per_bucket": [
            {
                "bucket": "homepage",
                "routes": ["/"],
                "verdict": "pass",
                "score": 8.5,
                "category_scores": {"structure": 8, "components": 9},
                "pages_judged": 2,
                "feedback": "homepage looks good",
                "issues": [],
                "error": None,
            },
        ],
        "pages_judged": 2,
        "report_path": "visual_eval/report.md",
    }


class _StubAgentRuntime:
    """Stub :class:`AgentRuntime` for the visual sweep injection seam."""

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        del run_dir, iter_dir, prompt, timeout
        now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        return RuntimeIterationResult(
            trajectory=Trajectory(
                iter_id="stub",
                runtime="stub",
                started_at=now,
                ended_at=now,
                exit_code=0,
                prompt_sha256="0" * 64,
            ),
        )


class _StubFullRuntime(_StubCompleter, _StubAgentRuntime):
    """Composite stub that satisfies both ``LLMCompleter`` and ``AgentRuntime``."""


class _RaisingCompleter:
    """Stub :class:`LLMCompleter` that raises a transport error."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def complete(self, prompt: str, *, timeout: float) -> str:
        del prompt, timeout
        raise self._exc


# --------------------------------------------------------------------------- #
# Workspace helpers
# --------------------------------------------------------------------------- #


def _materialise_workspace(out_dir: Path) -> Path:
    """Lay down the post-build artifact tree the final-eval step reads.

    Mirrors the spec §5.5 layout:

    * ``manual/capabilities.json`` — capabilities ground truth.
    * ``data/{products,collections,...}.json`` — published dataset
      :func:`resolve_smoke_flow` reads first handles from.
    * ``runs/build/artifact/hydrogen/`` — the post-build mutated tree
      the smoke flow walks the dev server against.
    """
    manual_dir = out_dir / "manual"
    manual_dir.mkdir(parents=True)
    (manual_dir / "capabilities.json").write_text(
        json.dumps({"homepage": {"section_types": ["hero"]}}),
        encoding="utf-8",
    )

    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True)
    for name in (
        "store.json",
        "products.json",
        "collections.json",
        "pages.json",
        "policies.json",
        "navigation.json",
    ):
        shutil.copy(_DATA_FIXTURE_DIR / name, data_dir / name)

    hydrogen_dir = out_dir / "runs" / "build" / "artifact" / "hydrogen"
    (hydrogen_dir / "app").mkdir(parents=True)
    (hydrogen_dir / "package.json").write_text('{"name":"hydrogen"}\n', encoding="utf-8")
    (hydrogen_dir / "app" / "root.tsx").write_text("// root\n", encoding="utf-8")

    return out_dir


def _build_ctx(
    out_dir: Path,
    *,
    runtime: object | None = None,
) -> StepContext:
    """Build a :class:`StepContext` rooted at ``out_dir``."""
    seed = out_dir.parent / "seed"
    seed.mkdir(exist_ok=True)
    cfg = ShopGenConfig(seeds=(seed,), out_dir=out_dir)
    return StepContext(config=cfg, out_dir=out_dir, runtime=runtime)  # type: ignore[arg-type]


def _read_report(out_dir: Path) -> dict[str, Any]:
    """Read ``<out_dir>/final_eval.json`` and return the parsed body."""
    raw: Any = json.loads((out_dir / "final_eval.json").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Step contract
# --------------------------------------------------------------------------- #


def test_final_eval_step_declares_expected_contract() -> None:
    """Step exposes the spec §5.7.1 contract fields."""
    step = FinalEvalStep()
    assert step.id == "final_eval"
    assert step.phase == "final_eval"
    assert step.depends_on == ["run_build_harness_loop"]
    assert step.outputs == [Path("final_eval.json")]
    assert StepInput(step_id="run_build_harness_loop") in step.inputs
    assert FileInput(path=Path("manual") / "capabilities.json") in step.inputs


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_final_eval_step_writes_pass_verdict(tmp_path: Path) -> None:
    """A clean smoke + ``pass`` LLM verdict yields ``ok=true`` in the report."""
    out_dir = _materialise_workspace(tmp_path / "out")
    completer = _StubCompleter(_PASS_RESPONSE)
    step = FinalEvalStep(
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=_stub_browser_driver,
        visual_sweep_runner=_stub_visual_sweep_runner,
    )

    step.run(_build_ctx(out_dir, runtime=completer))

    report = _read_report(out_dir)
    assert report["ok"] is True
    assert report["judge"]["verdict"] == "pass"
    assert report["judge"]["error"] is None
    assert report["smoke"]["base_url"] == _BASE_URL
    assert report["smoke"]["failures"] == []
    # One screenshot per (step, viewport) pair on the canonical 5-step flow x 2 viewports.
    assert len(report["smoke"]["screenshots"]) == _EXPECTED_SCREENSHOT_COUNT
    # Paths are recorded relative to out_dir.
    for shot in report["smoke"]["screenshots"]:
        assert shot["path"].startswith("runs/build/final_eval/screenshots/")

    # The LLM judge was called exactly once with the rendered prompt.
    assert len(completer.calls) == 1
    rendered = completer.calls[0]
    assert _BASE_URL in rendered
    # Capabilities body is embedded verbatim.
    assert '"section_types"' in rendered


# --------------------------------------------------------------------------- #
# Advisory contract — non-blocking failures
# --------------------------------------------------------------------------- #


def test_final_eval_step_does_not_raise_on_fail_verdict(tmp_path: Path) -> None:
    """T6.3 check: a ``fail`` verdict is recorded but never raises.

    Spec §5.5.5: a passing build harness loop is the gating signal; the
    final-eval verdict is **advisory** and surfaces issues for human
    review without blocking the run.
    """
    out_dir = _materialise_workspace(tmp_path / "out")
    completer = _StubCompleter(_FAIL_RESPONSE)
    step = FinalEvalStep(
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=_stub_browser_driver,
        visual_sweep_runner=_stub_visual_sweep_runner,
    )

    # The step.run() call must NOT raise — that is the entire advisory contract.
    step.run(_build_ctx(out_dir, runtime=completer))

    report = _read_report(out_dir)
    assert report["judge"]["verdict"] == "fail"
    assert report["judge"]["feedback"] == "homepage missing hero section"
    assert report["judge"]["error"] is None
    assert report["ok"] is False  # fail verdict ⇒ overall ok=False, but no raise.


def test_final_eval_step_records_smoke_failures(tmp_path: Path) -> None:
    """Driver-reported smoke failures land on ``report["smoke"]["failures"]``."""
    out_dir = _materialise_workspace(tmp_path / "out")
    completer = _StubCompleter(_PASS_RESPONSE)
    step = FinalEvalStep(
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=_failing_browser_driver,
        visual_sweep_runner=_stub_visual_sweep_runner,
    )

    step.run(_build_ctx(out_dir, runtime=completer))

    report = _read_report(out_dir)
    failure_steps = {f["step"] for f in report["smoke"]["failures"]}
    assert failure_steps == {"add_to_cart"}
    # ``ok`` collapses to False whenever the smoke flow recorded any failure,
    # even when the LLM judge said pass.
    assert report["ok"] is False
    assert report["judge"]["verdict"] == "pass"


def test_final_eval_step_records_llm_transport_error(tmp_path: Path) -> None:
    """A transport error is captured as ``verdict=error``; the step does not raise."""
    out_dir = _materialise_workspace(tmp_path / "out")
    completer = _RaisingCompleter(
        subprocess.TimeoutExpired(cmd="claude", timeout=180.0),
    )
    step = FinalEvalStep(
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=_stub_browser_driver,
        visual_sweep_runner=_stub_visual_sweep_runner,
    )

    step.run(_build_ctx(out_dir, runtime=completer))

    report = _read_report(out_dir)
    assert report["judge"]["verdict"] == "error"
    assert report["judge"]["error"] is not None
    assert "timeout" in report["judge"]["error"].lower()


def test_final_eval_step_records_parse_error(tmp_path: Path) -> None:
    """A malformed LLM response is captured as ``verdict=error``."""
    out_dir = _materialise_workspace(tmp_path / "out")
    completer = _StubCompleter("not even close to JSON")
    step = FinalEvalStep(
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=_stub_browser_driver,
        visual_sweep_runner=_stub_visual_sweep_runner,
    )

    step.run(_build_ctx(out_dir, runtime=completer))

    report = _read_report(out_dir)
    assert report["judge"]["verdict"] == "error"
    assert report["judge"]["error"] is not None
    assert "parse" in report["judge"]["error"].lower()


def test_final_eval_step_records_missing_capabilities(tmp_path: Path) -> None:
    """A missing ``manual/capabilities.json`` is captured rather than raised."""
    out_dir = _materialise_workspace(tmp_path / "out")
    (out_dir / "manual" / "capabilities.json").unlink()
    completer = _StubCompleter(_PASS_RESPONSE)
    step = FinalEvalStep(
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=_stub_browser_driver,
        visual_sweep_runner=_stub_visual_sweep_runner,
    )

    step.run(_build_ctx(out_dir, runtime=completer))

    report = _read_report(out_dir)
    assert report["judge"]["verdict"] == "error"
    assert "capabilities" in report["judge"]["error"]
    # Smoke still ran fine and is recorded.
    assert report["smoke"]["base_url"] == _BASE_URL


def test_final_eval_step_records_missing_hydrogen_tree(tmp_path: Path) -> None:
    """A missing post-build hydrogen tree is captured rather than raised."""
    out_dir = _materialise_workspace(tmp_path / "out")
    shutil.rmtree(out_dir / "runs" / "build" / "artifact")
    completer = _StubCompleter(_PASS_RESPONSE)
    step = FinalEvalStep(
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=_stub_browser_driver,
        visual_sweep_runner=_stub_visual_sweep_runner,
    )

    step.run(_build_ctx(out_dir, runtime=completer))

    report = _read_report(out_dir)
    assert report["smoke"]["base_url"] is None
    assert report["smoke"]["error"] is not None
    assert "hydrogen tree not found" in report["smoke"]["error"]
    # Judge still runs against the captured (empty) smoke payload — the LLM
    # is asked to react to the smoke failure list as part of its verdict.
    assert report["judge"]["verdict"] in {"pass", "fail", "error"}


def test_final_eval_step_records_missing_completer(tmp_path: Path) -> None:
    """No LLM completer in the runtime ⇒ ``verdict=error``; never raises."""
    out_dir = _materialise_workspace(tmp_path / "out")
    step = FinalEvalStep(
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=_stub_browser_driver,
        visual_sweep_runner=_stub_visual_sweep_runner,
    )

    step.run(_build_ctx(out_dir, runtime=None))

    report = _read_report(out_dir)
    assert report["judge"]["verdict"] == "error"
    assert "LLMCompleter" in report["judge"]["error"]


# --------------------------------------------------------------------------- #
# Visual subtree (T5.3 / SC6)
# --------------------------------------------------------------------------- #


def test_final_eval_step_writes_visual_subtree_on_pass(tmp_path: Path) -> None:
    """SC6: a clean sweep populates the full ``visual.{ok,...,report_path}`` subtree."""
    out_dir = _materialise_workspace(tmp_path / "out")
    runtime = _StubFullRuntime(_PASS_RESPONSE)
    step = FinalEvalStep(
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=_stub_browser_driver,
        visual_sweep_runner=_stub_visual_sweep_runner,
    )

    step.run(_build_ctx(out_dir, runtime=runtime))

    report = _read_report(out_dir)
    visual = report["visual"]
    assert visual["ok"] is True
    assert visual["verdict"] == "pass"
    assert visual["score"] == 8.5  # noqa: PLR2004 -- mirrors stub payload
    assert visual["category_scores"] == {"structure": 8.0, "components": 9.0}
    assert visual["pages_judged"] == 2  # noqa: PLR2004 -- mirrors stub payload
    assert visual["report_path"] == "visual_eval/report.md"
    assert visual["error"] is None
    # The advisory artifacts are on disk where reviewers expect them.
    assert (out_dir / "visual_eval" / "report.md").is_file()
    assert (out_dir / "visual_eval" / "screenshots" / "homepage" / "home" / "desktop.png").is_file()


def test_final_eval_step_threads_visual_caps_into_sweep_runner(tmp_path: Path) -> None:
    """Impl plan T5.4: ``visual_caps`` flow through to the sweep runner."""
    captured: dict[str, Any] = {}

    def capturing_sweep_runner(
        *,
        out_dir: Path,
        data_dir: Path,
        hydrogen_dir: Path,
        runtime: Any,
        dev_server_factory: Any,
        capabilities: Any,
        prompt_template: str,
        timeout_s: float,
        max_concurrency: int,
        pass_threshold: float,
        caps: BucketCaps,
    ) -> dict[str, Any]:
        del (
            data_dir,
            hydrogen_dir,
            runtime,
            dev_server_factory,
            capabilities,
            prompt_template,
        )
        captured["timeout_s"] = timeout_s
        captured["max_concurrency"] = max_concurrency
        captured["pass_threshold"] = pass_threshold
        captured["caps"] = caps
        return _stub_visual_sweep_runner(
            out_dir=out_dir,
            data_dir=Path("."),
            hydrogen_dir=Path("."),
            runtime=None,
            dev_server_factory=None,
            capabilities=None,
            prompt_template="",
            timeout_s=timeout_s,
            max_concurrency=max_concurrency,
            pass_threshold=pass_threshold,
            caps=caps,
        )

    out_dir = _materialise_workspace(tmp_path / "out")
    runtime = _StubFullRuntime(_PASS_RESPONSE)
    custom_caps = BucketCaps(max_collections=2, products_per_collection=3, max_pages=4)
    step = FinalEvalStep(
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=_stub_browser_driver,
        visual_sweep_runner=capturing_sweep_runner,
        visual_caps=custom_caps,
        visual_timeout_s=42.0,
    )

    step.run(_build_ctx(out_dir, runtime=runtime))

    assert captured["caps"] == custom_caps
    assert captured["timeout_s"] == 42.0  # noqa: PLR2004 -- explicit override


def test_final_eval_step_writes_visual_error_when_runtime_lacks_agent_runtime(
    tmp_path: Path,
) -> None:
    """T5.3: a runtime without ``run_iteration`` collapses to ``visual.error``."""
    out_dir = _materialise_workspace(tmp_path / "out")
    completer = _StubCompleter(_PASS_RESPONSE)
    # No visual_sweep_runner override — the default factory will be invoked
    # but the runtime probe in ``_run_visual_sweep`` short-circuits because
    # ``_StubCompleter`` does not implement ``AgentRuntime``.
    step = FinalEvalStep(
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=_stub_browser_driver,
    )

    step.run(_build_ctx(out_dir, runtime=completer))

    report = _read_report(out_dir)
    visual = report["visual"]
    assert visual["verdict"] == "error"
    assert visual["error"]
    assert "AgentRuntime" in visual["error"]
    # Top-level ok unaffected by visual error — sweep is advisory.
    assert report["ok"] is True


# --------------------------------------------------------------------------- #
# Pure-driver shape (run_final_eval)
# --------------------------------------------------------------------------- #


def test_run_final_eval_returns_serialisable_payload(tmp_path: Path) -> None:
    """``run_final_eval`` returns a JSON-serialisable mapping with the documented keys."""
    out_dir = _materialise_workspace(tmp_path / "out")
    completer = _StubCompleter(_PASS_RESPONSE)

    payload = run_final_eval(
        out_dir=out_dir,
        completer=completer,
        dev_server_factory=_stub_dev_server_factory,
        browser_driver=_stub_browser_driver,
        visual_sweep_runner=_stub_visual_sweep_runner,
    )

    # Round-trip through json.dumps to guarantee serialisability.
    body = json.loads(json.dumps(payload))
    assert set(body.keys()) == {"ok", "smoke", "judge", "visual"}
    assert set(body["smoke"].keys()) == {"base_url", "screenshots", "failures", "error"}
    assert set(body["judge"].keys()) == {"verdict", "feedback", "error"}
    assert set(body["visual"].keys()) == {
        "ok",
        "verdict",
        "score",
        "category_scores",
        "pages_judged",
        "feedback",
        "report_path",
        "error",
    }


# --------------------------------------------------------------------------- #
# Pipeline registration
# --------------------------------------------------------------------------- #


def test_final_eval_step_is_registered_in_pipeline() -> None:
    """``shop-gen --list-steps`` surfaces the ``final_eval`` step in its phase."""
    grouped = list_steps()
    assert "final_eval" in grouped
    assert "final_eval" in grouped["final_eval"]
