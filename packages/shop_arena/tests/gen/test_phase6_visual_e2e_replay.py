"""End-to-end replay test for Phase 6 ``visual_judge`` + visual-sweep wiring (T6.3).

Drives :class:`shop_arena.gen.build.loop.RunBuildHarnessLoopStep` through the
hand-crafted ``fixture_build_loop`` cassette with a
:class:`~shop_arena.gen.build.verifiers.visual_judge.VisualJudgeVerifier`
wired into the verifier tuple, and then invokes
:func:`shop_arena.gen.final_eval.visual_sweep.run_visual_sweep` against the
recorded hydrogen tree the loop produces.

The verifier-side runtime is a small adapter that

* delegates non-visual iterations to :class:`harness.runtimes.replay.ReplayRuntime`
  (so the cassette's hydrogen mutations land on disk and the surrounding
  rule verifiers see realistic inputs), and
* synthesises a deterministic ``verdict.json`` + a pair of screenshots
  for every nested ``visual_judge`` sub-iteration. Per-task, the
  synthesised verdict alternates between ``pass`` and ``fail`` so that
  the assertion "at least one PASS and one FAIL captured" is met
  without depending on the cassette's task ordering.

T6.3 acceptance:

* ``runs/build/iters/exec-*/checks/verifiers/visual_judge.json`` contains
  at least one ``"verdict": "pass"`` row and at least one ``"verdict":
  "fail"`` row.
* ``runs/build/iters/exec-*/checks/verifiers/visual_judge/screenshots/``
  is non-empty for the iterations the verifier ran against.
* The on-disk telemetry shows ``score`` + ``category_scores`` (proof
  that ``verdict.json`` was parsed by
  :func:`shop_arena.gen.build.verifiers._runtime_call.parse_visual_verdict`).
* The post-loop visual sweep returns a structured per-bucket summary
  with screenshots promoted under
  ``<out_dir>/visual_eval/screenshots/`` and ``report.md`` written.

The test reuses the canonical M4 ``sandbox_shop_v0`` data fixture and
the cassette already validated by ``test_phase4_e2e_replay.py``; only
the verifier wiring + per-iteration runtime adapter are new.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import shutil
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Final

import pytest

from harness import AgentRuntime, Verifier
from harness.runtimes.base import RuntimeIterationResult
from harness.runtimes.replay import ReplayRuntime
from harness.trajectory import Trajectory
from harness.verifiers import Verdict
from shop_arena.gen.build.loop import RunBuildHarnessLoopStep, RuntimeFactory, VerifiersFactory
from shop_arena.gen.build.sidecar import SidecarHandle
from shop_arena.gen.build.verifiers import (
    BuildVerifier,
    CrossTaskConsistencyVerifier,
    DataInUseVerifier,
    NavCoverageVerifier,
    QualityJudgeVerifier,
    SchemaIntrospection,
    TscVerifier,
    VisualJudgeVerifier,
)
from shop_arena.gen.build.verifiers._subprocess import CompletedSubprocess
from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.final_eval.prompts import load_visual_sweep_prompt
from shop_arena.gen.final_eval.visual_sweep import run_visual_sweep
from shop_arena.gen.steps.base import StepContext

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

_CASSETTE_DIR: Final[Path] = Path(__file__).resolve().parent / "cassettes" / "fixture_build_loop"
"""Hand-crafted cassette shared with T5.10 (`test_phase4_e2e_replay.py`)."""

_DATA_FIXTURE_DIR: Final[Path] = (
    Path(__file__).resolve().parent / "data_synth" / "fixtures" / "sandbox_shop_v0"
)
"""Canonical M4 dataset fixture shipped under ``data_synth/fixtures/``."""

_FIXTURE_FILES: Final[tuple[str, ...]] = (
    "store.json",
    "products.json",
    "collections.json",
    "pages.json",
    "policies.json",
    "navigation.json",
)

_PORT: Final[int] = 54321
_BASE_URL: Final[str] = f"http://127.0.0.1:{_PORT}"

_STOREFRONT_FIELDS: Final[frozenset[str]] = frozenset(
    {"shop", "product", "products", "collection", "collections", "page", "cart"},
)

_PASS_JUDGE_PAYLOAD: Final[str] = json.dumps({"verdict": "pass", "feedback": ""})

# Visual-judge applies to these two cassette tasks; restricting the set
# keeps the test focused on a single PASS / single FAIL pairing without
# pulling the multi-bucket ``visual_fix`` fan-out (covered by the
# unit-suite under ``tests/gen/build/verifiers/test_visual_judge.py``).
_VISUAL_TASKS: Final[frozenset[str]] = frozenset({"gen_navigation", "gen_homepage"})

# Per-task synthetic verdict bodies the recording runtime writes back.
# ``gen_navigation`` PASSes, ``gen_homepage`` FAILs — together they
# satisfy T6.3's "at least one PASS and one FAIL captured" check.
_VERDICT_BODIES: Final[dict[str, dict[str, Any]]] = {
    "gen_navigation": {
        "verdict": "pass",
        "score": 8.5,
        "category_scores": {"structure": 8, "components": 9, "visual_tone": 8},
        "feedback": "navigation: header reachable from every nav slot",
        "pages_judged": 2,
        "issues": [],
    },
    "gen_homepage": {
        "verdict": "fail",
        "score": 4.0,
        "category_scores": {"structure": 5, "components": 4, "visual_tone": 3},
        "feedback": "homepage: hero CTA missing on mobile viewport",
        "pages_judged": 2,
        "issues": [
            {
                "route": "/",
                "viewport": "mobile",
                "screenshot": "screenshots/home__mobile.png",
                "severity": "major",
                "summary": "hero CTA is not visible above the fold",
                "capability": "home.hero",
            },
        ],
    },
}

# Sweep verdict bodies are emitted per page bucket via the same adapter.
_SWEEP_PASS_BODY: Final[str] = json.dumps(
    {
        "verdict": "pass",
        "score": 8.0,
        "category_scores": {"structure": 8, "components": 8, "visual_tone": 8},
        "feedback": "all pages render with consistent typography",
        "pages_judged": 1,
        "issues": [],
    },
)

_PNG_HEADER: Final[bytes] = b"\x89PNG\r\n\x1a\n"


# --------------------------------------------------------------------------- #
# Stubs — runtime, sidecar, dev-server, subprocess
# --------------------------------------------------------------------------- #


class _VisualJudgeAwareRuntime:
    """Composite ``AgentRuntime`` + :class:`harness.runtimes.LLMCompleter`.

    Delegates plan / executor iterations to the wrapped
    :class:`ReplayRuntime`. When the build loop's
    :class:`VisualJudgeVerifier` invokes ``run_iteration`` against its
    sub-workspace (``run_dir`` ends in ``.../visual_judge/work``), the
    adapter writes a per-task ``verdict.json`` + a couple of placeholder
    screenshots into ``run_dir`` and returns a synthetic
    :class:`Trajectory`. The two LLM-judge verifiers (``quality_judge``
    + ``cross_task_consistency``) reach this same object via
    :meth:`complete`, which returns a canned ``"pass"`` JSON.
    """

    def __init__(
        self,
        *,
        replay: ReplayRuntime,
        verdict_bodies: dict[str, dict[str, Any]],
    ) -> None:
        """Bind the composite runtime to the cassette + per-task verdicts."""
        self._replay = replay
        self._verdict_bodies = verdict_bodies
        self.visual_calls: list[dict[str, Any]] = []

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        """Branch on whether the call is a visual sub-iteration."""
        if _is_visual_sub_iter(run_dir):
            return self._handle_visual(
                run_dir=run_dir,
                iter_dir=iter_dir,
                prompt=prompt,
                timeout=timeout,
            )
        return self._replay.run_iteration(
            run_dir=run_dir,
            iter_dir=iter_dir,
            prompt=prompt,
            timeout=timeout,
        )

    def complete(self, prompt: str, *, timeout: float) -> str:
        """Return a canned ``"pass"`` JSON verdict for the LLM-judge seam."""
        del prompt, timeout
        return _PASS_JUDGE_PAYLOAD

    def _handle_visual(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        task_id = _task_id_from_run_dir(run_dir)
        body = self._verdict_bodies.get(task_id)
        if body is None:
            msg = (
                f"_VisualJudgeAwareRuntime has no verdict body for task `{task_id}`; "
                f"add it to `_VERDICT_BODIES` or restrict `applicable_tasks`."
            )
            raise AssertionError(msg)

        # Ensure the harness-owned iter dir exists; PiRuntime would
        # create it, but the stub must not rely on that.
        iter_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "verdict.json").write_text(
            json.dumps(body, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        shots_dir = run_dir / "screenshots"
        shots_dir.mkdir(exist_ok=True)
        (shots_dir / f"{task_id}__desktop.png").write_bytes(_PNG_HEADER)
        (shots_dir / f"{task_id}__mobile.png").write_bytes(_PNG_HEADER)

        self.visual_calls.append(
            {
                "task_id": task_id,
                "run_dir": run_dir,
                "iter_dir": iter_dir,
                "verdict": body["verdict"],
            },
        )
        del prompt, timeout
        return _synthetic_iteration_result(iter_id=f"visual-{task_id}")


class _SweepRuntime:
    """Stub :class:`AgentRuntime` for the post-loop visual sweep.

    Each per-bucket sub-iteration receives a deterministic PASS verdict
    + a pair of placeholder screenshots so the sweep can promote them
    into ``visual_eval/screenshots/<bucket>/``.
    """

    def __init__(self) -> None:
        """Initialise the recording call list."""
        self.calls: list[dict[str, Any]] = []

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        """Write a PASS verdict + screenshots, mirroring the real agent."""
        del prompt, timeout
        bucket = _bucket_from_run_dir(run_dir)
        iter_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "verdict.json").write_text(_SWEEP_PASS_BODY, encoding="utf-8")
        shots_dir = run_dir / "screenshots"
        shots_dir.mkdir(exist_ok=True)
        slug = bucket.replace("_", "-")
        (shots_dir / f"{slug}__desktop.png").write_bytes(_PNG_HEADER)
        (shots_dir / f"{slug}__mobile.png").write_bytes(_PNG_HEADER)
        self.calls.append({"bucket": bucket, "run_dir": run_dir})
        return _synthetic_iteration_result(iter_id=f"sweep-{bucket}")


def _is_visual_sub_iter(run_dir: Path) -> bool:
    """Identify a visual_judge sub-workspace by its parent directory layout.

    The verifier stages ``<parent_dir>/work/`` where ``parent_dir`` ends
    in either ``.../visual_judge`` (single-bucket) or
    ``.../visual_judge/<bucket>`` (multi-bucket fan-out, T5.7). Both
    cases share the ``work`` leaf and a ``visual_judge`` ancestor.
    """
    if run_dir.name != "work":
        return False
    return any(parent.name == "visual_judge" for parent in run_dir.parents)


def _task_id_from_run_dir(run_dir: Path) -> str:
    """Recover the selected task id from the staged ``routes.json``.

    :func:`shop_arena.gen.build.verifiers._runtime_call.stage_sub_workspace`
    serialises the verifier's ``routes_payload`` (which carries
    ``task_id``) to ``<run_dir>/routes.json`` before invoking the
    runtime; reading it here is more robust than parsing the prompt
    body.
    """
    payload = json.loads((run_dir / "routes.json").read_text(encoding="utf-8"))
    task_id = payload.get("task_id")
    if not isinstance(task_id, str):
        msg = f"routes.json under {run_dir} missing string `task_id`: {payload!r}"
        raise AssertionError(msg)
    return task_id


def _bucket_from_run_dir(run_dir: Path) -> str:
    """Recover the bucket name from the sweep's staged ``routes.json``."""
    payload = json.loads((run_dir / "routes.json").read_text(encoding="utf-8"))
    bucket = payload.get("bucket")
    if not isinstance(bucket, str):
        msg = f"routes.json under {run_dir} missing string `bucket`: {payload!r}"
        raise AssertionError(msg)
    return bucket


def _synthetic_iteration_result(*, iter_id: str) -> RuntimeIterationResult:
    """Build a synthetic :class:`RuntimeIterationResult` for stub runtimes."""
    now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    return RuntimeIterationResult(
        trajectory=Trajectory(
            iter_id=iter_id,
            runtime="stub",
            started_at=now,
            ended_at=now,
            exit_code=0,
            prompt_sha256="0" * 64,
        ),
    )


def _stub_handle() -> SidecarHandle:
    """Return a :class:`SidecarHandle` for the stub sidecar lifecycle."""
    return SidecarHandle(pid=12345, port=_PORT, base_url=_BASE_URL, store_name="Stub")


@contextlib.contextmanager
def _stub_sidecar_factory(*, argv: Sequence[str], port: int) -> Iterator[SidecarHandle]:
    """Sidecar factory that never spawns a subprocess."""
    del argv
    assert port == _PORT
    yield _stub_handle()


@contextlib.contextmanager
def _stub_dev_server(hydrogen_dir: Path) -> Iterator[str]:
    """Stub :class:`DevServerFactory` — yields a deterministic URL, no boot."""
    assert hydrogen_dir.is_dir(), f"dev server expected hydrogen tree at {hydrogen_dir}"
    yield _BASE_URL


def _passing_subprocess_runner(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
) -> CompletedSubprocess:
    """Stub :class:`SubprocessRunner` that always reports ``returncode=0``."""
    del argv, cwd, timeout
    return CompletedSubprocess(returncode=0, stdout="", stderr="")


def _shop_backend_cli_stub() -> Path:
    """Return a path the loop step accepts as the bundled ``shop-backend`` CLI."""
    return Path(__file__).resolve()


def _stub_introspector() -> SchemaIntrospection:
    """Return a static :class:`SchemaIntrospection` covering Storefront roots."""
    return SchemaIntrospection(
        root_fields={
            "Query": _STOREFRONT_FIELDS,
            "Mutation": frozenset(
                {"cartCreate", "cartLinesAdd", "cartLinesUpdate", "cartLinesRemove"},
            ),
        },
    )


# --------------------------------------------------------------------------- #
# Verifier wiring
# --------------------------------------------------------------------------- #


def _build_verifiers_factory(*, data_dir: Path) -> VerifiersFactory:
    """Return a verifiers factory wiring the v0.1 set + ``visual_judge`` (T6.3).

    ``visual_judge`` is restricted to :data:`_VISUAL_TASKS` so the test
    pairs a single PASS (``gen_navigation``) with a single FAIL
    (``gen_homepage``) without pulling the multi-bucket fan-out.
    The retry budget is disabled so a per-task FAIL never downgrades to
    ADVISORY mid-loop.
    """

    def _factory(
        *,
        out_dir: Path,
        sidecar: SidecarHandle,
        judges: frozenset[str] = frozenset(),
        visual_retry_budget: int = 0,
        visual_judge_pass_threshold: float = 7.0,
        visual_judge_max_concurrency: int = 3,
    ) -> tuple[Verifier, ...]:
        del out_dir, sidecar, judges, visual_retry_budget
        del visual_judge_max_concurrency
        return (
            TscVerifier(runner=_passing_subprocess_runner),
            BuildVerifier(runner=_passing_subprocess_runner),
            DataInUseVerifier(introspect=_stub_introspector),
            NavCoverageVerifier(data_dir=data_dir),
            QualityJudgeVerifier(),
            VisualJudgeVerifier(
                data_dir=data_dir,
                dev_server_factory=_stub_dev_server,
                retry_budget=0,
                pass_threshold=visual_judge_pass_threshold,
                applicable_tasks=_VISUAL_TASKS,
            ),
            CrossTaskConsistencyVerifier(),
        )

    return _factory


# --------------------------------------------------------------------------- #
# Workspace helpers (mirror test_phase4_e2e_replay.py)
# --------------------------------------------------------------------------- #


def _materialise_workspace(out_dir: Path) -> None:
    """Lay the manual + data + hydrogen sub-trees the loop step requires."""
    manual_dir = out_dir / "manual"
    manual_dir.mkdir(parents=True)
    # ``visual_judge`` reads ``capabilities.json`` from the
    # post-seed-copy artifact dir; populate the bucket keys so the
    # filtered slice is non-empty even though the cassette never edits
    # capabilities directly.
    capabilities = {
        "home.hero": {"present": True},
        "navigation.header": {"depth": 1},
        "footer": {"present": True},
        "collection.filters": ["price"],
        "product.variant_selectors": [],
        "search.predictive_types": [],
    }
    (manual_dir / "capabilities.json").write_text(
        json.dumps(capabilities),
        encoding="utf-8",
    )
    (manual_dir / "manual.md").write_text("# manual\n", encoding="utf-8")
    (manual_dir / "stats.json").write_text("{}", encoding="utf-8")
    (manual_dir / "manifest.json").write_text("{}", encoding="utf-8")

    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True)
    for name in _FIXTURE_FILES:
        shutil.copy(_DATA_FIXTURE_DIR / name, data_dir / name)

    hydrogen_dir = out_dir / "hydrogen"
    (hydrogen_dir / "app").mkdir(parents=True)
    (hydrogen_dir / "package.json").write_text(
        '{"name":"hydrogen"}\n',
        encoding="utf-8",
    )
    (hydrogen_dir / "app" / "root.tsx").write_text("// root\n", encoding="utf-8")
    (hydrogen_dir / ".env").write_text(
        f"PUBLIC_STORE_DOMAIN=http://localhost:{_PORT}\n",
        encoding="utf-8",
    )


def _build_ctx(out_dir: Path, *, max_iters: int) -> StepContext:
    """Build a :class:`StepContext` rooted at ``out_dir``."""
    seed = out_dir.parent / "seed"
    seed.mkdir(exist_ok=True)
    cfg = ShopGenConfig(seeds=(seed,), out_dir=out_dir, max_iters=max_iters)
    return StepContext(config=cfg, out_dir=out_dir)


def _runtime_factory_for(runtime: AgentRuntime) -> RuntimeFactory:
    """Wrap ``runtime`` in a :class:`RuntimeFactory`."""

    def _factory(config: ShopGenConfig) -> AgentRuntime:
        del config
        return runtime

    return _factory


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_phase6_visual_judge_replay_captures_pass_and_fail_with_screenshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T6.3: ``visual_judge`` records both verdicts with on-disk evidence.

    Drives the cassette under :class:`ReplayRuntime` with
    :class:`VisualJudgeVerifier` wired into the verifier tuple. The
    composite runtime synthesises a per-task ``verdict.json`` for every
    visual sub-iteration (PASS for ``gen_navigation``, FAIL for
    ``gen_homepage``). After the loop completes the test asserts:

    * the per-iteration ``visual_judge.json`` telemetry contains at
      least one PASS row and at least one FAIL row (T6.3 acceptance
      sentence "at least one PASS and one FAIL captured");
    * each row carries ``score`` + ``category_scores`` (proof that the
      §9.3 ``verdict.json`` body was parsed by
      :func:`shop_arena.gen.build.verifiers._runtime_call.parse_visual_verdict`);
    * promoted screenshots exist under
      ``checks/verifiers/visual_judge/screenshots/`` for every
      iteration the verifier ran against.
    """
    monkeypatch.setattr(
        "shop_arena.gen.build.loop.find_shop_backend_cli",
        _shop_backend_cli_stub,
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    replay = ReplayRuntime(scenario_dir=_CASSETTE_DIR)
    runtime = _VisualJudgeAwareRuntime(
        replay=replay,
        verdict_bodies=_VERDICT_BODIES,
    )

    step = RunBuildHarnessLoopStep(
        runtime_factory=_runtime_factory_for(runtime),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_build_verifiers_factory(data_dir=out_dir / "data"),
        install_runner=_passing_subprocess_runner,
    )

    step.run(_build_ctx(out_dir, max_iters=6))

    run_dir = out_dir / "runs" / "build"
    summary = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    visual_runs = [r for r in summary["verifier_runs"] if r["name"] == "visual_judge"]
    assert visual_runs, "visual_judge was never dispatched — wiring regression"

    # T6.3 check: at least one PASS and one FAIL captured.
    verdicts = {r["verdict"] for r in visual_runs}
    assert Verdict.PASS.value in verdicts, f"no visual_judge PASS row captured; runs={visual_runs}"
    assert Verdict.FAIL.value in verdicts, f"no visual_judge FAIL row captured; runs={visual_runs}"

    # Per-iteration verdict.json was actually parsed (score + category
    # scores landed in the on-disk telemetry).
    for run in visual_runs:
        per_path = run_dir / run["path"]
        per_payload = json.loads(per_path.read_text(encoding="utf-8"))
        details = per_payload["details"]
        assert "score" in details, f"score missing from {per_path}: {details}"
        assert "category_scores" in details, f"category_scores missing from {per_path}: {details}"
        assert details["score"] is not None, f"score is None on parsed verdict: {details}"

    # Screenshots promoted into the verifier-owned subtree for each
    # dispatched visual_judge iteration.
    visual_iter_ids = {run["iter_id"] for run in visual_runs}
    for iter_id in visual_iter_ids:
        screenshots = (
            run_dir / "iters" / iter_id / "checks" / "verifiers" / "visual_judge" / "screenshots"
        )
        assert screenshots.is_dir(), (
            f"missing promoted screenshots dir for iter `{iter_id}`: {screenshots}"
        )
        files = [p for p in screenshots.rglob("*") if p.is_file()]
        assert files, f"no screenshots promoted for iter `{iter_id}` under {screenshots}"

    # Sanity: the runtime stub was actually exercised by the verifier
    # for every applicable cassette task (`gen_navigation`,
    # `gen_homepage`).
    visual_tasks_seen = {call["task_id"] for call in runtime.visual_calls}
    assert visual_tasks_seen == _VISUAL_TASKS, (
        f"unexpected visual task coverage: {visual_tasks_seen} vs {_VISUAL_TASKS}"
    )


def test_phase6_visual_sweep_replay_promotes_screenshots_against_recorded_hydrogen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T6.3: post-loop visual sweep against the recorded hydrogen tree.

    Boots the same cassette + verifier wiring as the
    ``visual_judge`` test, then drives
    :func:`shop_arena.gen.final_eval.visual_sweep.run_visual_sweep` against
    the artifact tree the loop produced. Asserts that the sweep

    * fans out one nested ``run_iteration`` call per page bucket;
    * parses every per-bucket ``verdict.json`` (the report payload
      reflects the structured score);
    * promotes screenshots into
      ``<out_dir>/visual_eval/screenshots/<bucket>/``;
    * writes a non-empty ``<out_dir>/visual_eval/report.md``.
    """
    monkeypatch.setattr(
        "shop_arena.gen.build.loop.find_shop_backend_cli",
        _shop_backend_cli_stub,
    )
    # The sweep guards on the playwright skill probe; force it to
    # ``True`` so the replay test exercises the success arm.
    monkeypatch.setattr(
        "shop_arena.gen.final_eval.visual_sweep.is_playwright_skill_available",
        lambda: True,
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _materialise_workspace(out_dir)

    replay = ReplayRuntime(scenario_dir=_CASSETTE_DIR)
    runtime = _VisualJudgeAwareRuntime(
        replay=replay,
        verdict_bodies=_VERDICT_BODIES,
    )

    step = RunBuildHarnessLoopStep(
        runtime_factory=_runtime_factory_for(runtime),
        sidecar_factory=_stub_sidecar_factory,
        verifiers_factory=_build_verifiers_factory(data_dir=out_dir / "data"),
        install_runner=_passing_subprocess_runner,
    )
    step.run(_build_ctx(out_dir, max_iters=6))

    run_dir = out_dir / "runs" / "build"
    artifact = run_dir / "artifact"
    hydrogen_dir = artifact / "hydrogen"
    data_dir = artifact / "data"
    capabilities = json.loads(
        (artifact / "capabilities.json").read_text(encoding="utf-8"),
    )

    sweep_runtime = _SweepRuntime()
    report = run_visual_sweep(
        out_dir=out_dir,
        data_dir=data_dir,
        hydrogen_dir=hydrogen_dir,
        runtime=sweep_runtime,
        dev_server_factory=_stub_dev_server,
        capabilities=capabilities,
        prompt_template=load_visual_sweep_prompt(),
    )

    visual_eval_dir = out_dir / "visual_eval"
    assert visual_eval_dir.is_dir(), "visual_eval/ was not created"

    # Every bucket reported in the sweep must have:
    #   * a parsed verdict (score + category scores landed in the
    #     summary, proving `parse_visual_verdict` ran);
    #   * a promoted screenshots dir under
    #     ``visual_eval/screenshots/<bucket>/``.
    assert report["per_bucket"], "sweep returned no per-bucket entries"
    for entry in report["per_bucket"]:
        bucket = entry["bucket"]
        if entry.get("error") is not None:
            # Empty buckets are recorded with `error="no routes ..."`
            # and never reach the runtime; nothing to assert here.
            continue
        assert entry["score"] is not None, f"bucket `{bucket}` missing parsed score: {entry}"
        assert "category_scores" in entry, (
            f"bucket `{bucket}` missing parsed category_scores: {entry}"
        )
        bucket_shots = visual_eval_dir / "screenshots" / bucket
        assert bucket_shots.is_dir(), (
            f"missing promoted sweep screenshots for `{bucket}`: {bucket_shots}"
        )
        files = [p for p in bucket_shots.rglob("*") if p.is_file()]
        assert files, f"no screenshots promoted for sweep bucket `{bucket}` under {bucket_shots}"

    # The sweep wrote a non-empty markdown report adjacent to the
    # screenshots tree.
    report_path = visual_eval_dir / "report.md"
    assert report_path.is_file(), f"sweep report missing: {report_path}"
    assert report_path.stat().st_size > 0, f"sweep report is empty: {report_path}"
    # The driver returns the report path relative to ``out_dir``; the
    # value must round-trip back to the on-disk file.
    assert (out_dir / report["report_path"]).is_file()

    # Sanity: the sweep runtime was invoked exactly once per
    # non-skipped bucket.
    invoked_buckets = {call["bucket"] for call in sweep_runtime.calls}
    expected_buckets = {
        entry["bucket"] for entry in report["per_bucket"] if entry.get("error") is None
    }
    assert invoked_buckets == expected_buckets, (
        f"sweep runtime invocations diverged from non-skipped buckets: "
        f"{invoked_buckets} vs {expected_buckets}"
    )
