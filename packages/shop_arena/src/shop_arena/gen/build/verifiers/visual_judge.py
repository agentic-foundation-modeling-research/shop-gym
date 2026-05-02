"""``visual_judge`` build-loop verifier (impl plan T1.4, spec §5.2).

Per-task visual quality gate. Resolves the executor's
``selected_task_id`` to a page-bucket scope, boots the dev server,
hands a sub-workspace to ``ctx.runtime.run_iteration`` so the agent
can drive the playwright skill against the rendered pages, and
parses the structured ``verdict.json`` the agent writes back. The
score → verdict coercion rules from spec §9.3 are applied inside
:mod:`shop_arena.gen.build.verifiers._runtime_call`.

This M1 landing covers per-task invocations only
(``gen_homepage``, ``gen_product``, …). The ``visual_fix``
page-bucket fan-out lands later (T5.7); the per-task retry budget
(M2 / T2.2) is enforced inline via
:func:`shop_arena.gen.build.verifiers._history.count_prior_task_fails`.

The verifier reads:

* ``ctx.artifact_dir / "capabilities.json"`` — merged capabilities
  document seeded by the build loop. The slice handed to the agent
  is filtered to the active bucket(s) per spec §5.3.1 so the judge
  never sees (or penalises the absence of) features that belong to
  a different bucket.
* ``data_dir / {collections,products,pages}.json`` — supplied at
  construction time and used by
  :func:`shop_arena.gen.build.verifiers._task_routes.routes_for_buckets`
  to materialise the route list for the active bucket(s).
* ``ctx.artifact_dir / "hydrogen"`` — the dev-server root the
  injected :class:`~shop_arena.gen.final_eval.playwright_smoke.DevServerFactory`
  boots against.

The dev server is torn down on every exit (success **and**
exception). Missing artifacts (capabilities document, hydrogen
tree) and unknown task ids surface as structured FAIL / ERROR
results; the harness never deadlocks on a transient input glitch.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from harness.verifiers import Verdict, VerifierContext, VerifierResult
from shop_arena.gen.build.prompts import load_visual_judge_prompt
from shop_arena.gen.build.verifiers._history import count_prior_task_fails
from shop_arena.gen.build.verifiers._runtime_call import (
    VisualVerdict,
    parse_visual_verdict,
    run_visual_iteration,
)
from shop_arena.gen.build.verifiers._task_routes import (
    DEFAULT_CAPS,
    PAGE_WEIGHTS,
    bucket_routes,
    buckets_for_task,
    capabilities_for_buckets,
    routes_for_buckets,
)
from shop_arena.gen.final_eval.playwright_smoke import DevServerFactory

_log = logging.getLogger(__name__)

_NAME: Final[str] = "visual_judge"
"""Verifier name (filesystem-safe; matches the spec table)."""

_DEFAULT_TIMEOUT_S: Final[float] = 300.0
"""Wall-clock budget for the nested agent iteration (5 minutes).

The agent boots a browser, walks two viewports per route, takes
screenshots, and emits the structured verdict; the default leaves
headroom for cold-start latency on the configured runtime.
"""

_DEFAULT_RETRY_BUDGET: Final[int] = 3
"""Per-task cap on consecutive ``visual_judge`` FAILs (spec §5.4)."""

_DEFAULT_PASS_THRESHOLD: Final[float] = 7.0
"""Score floor below which an emitted ``pass`` is coerced to ``fail`` (spec §9.3)."""

_DEFAULT_MAX_CONCURRENCY: Final[int] = 3
"""Default page-bucket fan-out worker count (spec §5.2.1 step 5, §5.6).

Caps the ``ThreadPoolExecutor`` width used by the ``visual_fix`` fan-out
path (T5.7). Single-bucket invocations bypass the executor entirely so
the knob has no effect when only one bucket resolves.
"""

_HYDROGEN_DIRNAME: Final[str] = "hydrogen"
"""Subdir of ``ctx.artifact_dir`` the dev-server factory is rooted at."""

_CAPABILITIES_FILENAME: Final[str] = "capabilities.json"
"""Merged capabilities document under ``ctx.artifact_dir`` (spec §5.3.1)."""

_SCREENSHOTS_DIRNAME: Final[str] = "screenshots"
"""Sub-workspace screenshot dir promoted into ``checks/verifiers/visual_judge/``."""

_DEFAULT_TASKS: Final[frozenset[str]] = frozenset(
    {
        "gen_homepage",
        "gen_navigation",
        "gen_collections",
        "gen_product",
        "gen_cart_search",
        "gen_info_pages",
        # ``visual_fix`` is in scope as of T5.7: multi-bucket
        # invocations fan out under a ``ThreadPoolExecutor`` and the
        # per-bucket verdicts are merged per spec §5.2.1 step 6 + §9.5.
        "visual_fix",
    },
)
"""Default applicability set per spec §5.2 (now includes ``visual_fix``, T5.7)."""

_VERDICT_SCHEMA_BLOCK: Final[str] = """\
{
  "verdict": "pass | fail",                  // required; lowercase
  "score": 7.8,                               // required; 0-10 float
  "category_scores": {                        // optional; same 0-10 scale
    "structure": 8,                           // page hierarchy + section ordering
    "components": 7,                          // component types present
    "visual_tone": 8                          // colour, typography, spacing, density
  },
  "feedback": "markdown body",                // required on fail; "" allowed on pass
  "pages_judged": 4,                          // required; (route, viewport) pairs judged
  "issues": [                                 // optional
    {
      "route": "/collections/outerwear",
      "viewport": "mobile",
      "screenshot": "screenshots/collections-outerwear__mobile.png",
      "severity": "critical | major | minor",
      "summary": "filter bar overflows the viewport",
      "capability": "collection.filters"
    }
  ]
}\
"""
"""Static §9.3 schema body rendered into the ``{verdict_schema}`` slot."""


class VisualJudgeVerifier:
    """Per-task visual quality verifier (spec §5.2 + §9.3).

    Attributes:
        name: ``"visual_judge"`` — used as the per-verifier telemetry
            filename and the markdown section heading in
            ``feedback.md``.
    """

    name: str = _NAME

    def __init__(
        self,
        *,
        data_dir: Path,
        dev_server_factory: DevServerFactory,
        retry_budget: int = _DEFAULT_RETRY_BUDGET,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        pass_threshold: float = _DEFAULT_PASS_THRESHOLD,
        max_concurrency: int = _DEFAULT_MAX_CONCURRENCY,
        applicable_tasks: Iterable[str] | None = None,
    ) -> None:
        """Build the verifier with optional injection seams.

        Args:
            data_dir: Directory containing the published
                ``collections.json`` / ``products.json`` /
                ``pages.json`` files. Forwarded to
                :func:`shop_arena.gen.build.verifiers._task_routes.routes_for_buckets`
                so resolved routes carry real handles.
            dev_server_factory: Shared dev-server factory protocol;
                production wiring is the ``pnpm dev`` runner that
                lands in T6.1, tests inject a stub yielding a
                deterministic base URL.
            retry_budget: Per-task cap on consecutive ``visual_judge``
                FAILs before the verifier downgrades to ADVISORY.
                ``0`` disables the budget entirely (spec §5.4).
            timeout_s: Wall-clock budget for the nested agent
                iteration. Defaults to :data:`_DEFAULT_TIMEOUT_S`.
            pass_threshold: Score floor for the §9.3 coercion rule.
                Defaults to :data:`_DEFAULT_PASS_THRESHOLD`.
            max_concurrency: Page-bucket fan-out worker count (spec
                §5.2.1 step 5, §5.6). Defaults to
                :data:`_DEFAULT_MAX_CONCURRENCY`. Stored for the M5
                fan-out arm; M1 invokes a single bucket per call.
            applicable_tasks: Override the default applicability set.
                Defaults to :data:`_DEFAULT_TASKS` (M1 scope plus
                ``visual_fix``).
        """
        self._data_dir = data_dir
        self._dev_server_factory = dev_server_factory
        self._retry_budget = retry_budget
        self._timeout_s = timeout_s
        self._pass_threshold = pass_threshold
        self._max_concurrency = max_concurrency
        self._applicable_tasks: frozenset[str] = (
            _DEFAULT_TASKS if applicable_tasks is None else frozenset(applicable_tasks)
        )

    def applies_to(self, task_id: str) -> bool:
        """Match the configured applicability set.

        Args:
            task_id: Selected task id.

        Returns:
            ``True`` when this verifier should run for ``task_id``.
        """
        return task_id in self._applicable_tasks

    def run(  # noqa: PLR0911 -- one early-return per §5.2.1 precondition
        self,
        ctx: VerifierContext,
    ) -> VerifierResult:
        """Render the visual-judge prompt, run the nested iteration, parse the verdict.

        Spec §5.2.1 lifecycle — implements steps 1-7 of the
        eight-step contract (the multi-bucket fan-out arm of step 5
        + the merge in step 6 lands in T5.7). The retry-budget check
        is interposed between step 1 and step 3 per spec §5.4.

        Args:
            ctx: Verifier context. Reads ``ctx.artifact_dir`` for the
                hydrogen tree + ``capabilities.json``; uses
                ``ctx.runtime`` for the nested ``run_iteration`` call.

        Returns:
            ``PASS`` when the agent's structured verdict survives the
            §9.3 coercion rules; ``FAIL`` when the verdict is ``fail``,
            below the score threshold, or contains a critical-severity
            issue. Workspace problems (missing capabilities / hydrogen
            tree, unknown task id) and runtime crashes surface as
            ``FAIL`` / ``ERROR`` with explanatory feedback rather than
            propagating.
        """
        # Step 1: resolve task scope.
        buckets = buckets_for_task(ctx.selected_task_id)
        if not buckets:
            return VerifierResult(
                verdict=Verdict.ERROR,
                feedback=(
                    f"`visual_judge` does not know how to scope task "
                    f"`{ctx.selected_task_id}`; no page-bucket mapping is registered."
                ),
                details={"task_id": ctx.selected_task_id, "buckets_run": []},
            )

        capabilities_path = ctx.artifact_dir / _CAPABILITIES_FILENAME
        if not capabilities_path.is_file():
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"`visual_judge` could not read `{_CAPABILITIES_FILENAME}` "
                    "from the run's artifact directory; the build loop is expected "
                    "to seed it via `PlanExecLoopConfig.artifact_seed_dir`."
                ),
                details={"capabilities_path": str(capabilities_path), "exists": False},
            )

        try:
            capabilities_payload = json.loads(
                capabilities_path.read_text(encoding="utf-8"),
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"`visual_judge` could not parse `{_CAPABILITIES_FILENAME}`: "
                    f"{type(exc).__name__}: {exc}"
                ),
                details={
                    "capabilities_path": str(capabilities_path),
                    "error": str(exc),
                },
            )
        if not isinstance(capabilities_payload, dict):
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"`visual_judge` expected `{_CAPABILITIES_FILENAME}` to be a "
                    "JSON object; got a different top-level type."
                ),
                details={"capabilities_path": str(capabilities_path)},
            )

        hydrogen_dir = ctx.artifact_dir / _HYDROGEN_DIRNAME
        if not hydrogen_dir.is_dir():
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"`visual_judge` could not find the hydrogen tree at "
                    f"`{_HYDROGEN_DIRNAME}/`. Did `clone_template` run?"
                ),
                details={"hydrogen_dir": str(hydrogen_dir), "exists": False},
            )

        routes = routes_for_buckets(buckets, self._data_dir, caps=DEFAULT_CAPS)
        capability_slice = capabilities_for_buckets(buckets, capabilities_payload)
        buckets_run = sorted(buckets)

        if not routes:
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"`visual_judge` resolved no routes for task "
                    f"`{ctx.selected_task_id}` (buckets={buckets_run}); the "
                    "data directory may be empty or the bucket map is out of "
                    "sync with the dataset."
                ),
                details={
                    "task_id": ctx.selected_task_id,
                    "buckets_run": buckets_run,
                    "data_dir": str(self._data_dir),
                },
            )

        # Step 2: per-task retry budget (spec §5.4). When the budget
        # is non-zero and the configured number of prior FAILs is
        # already on disk, downgrade to ADVISORY without booting the
        # dev server or invoking the runtime.
        prior_fails = count_prior_task_fails(
            run_dir=ctx.run_dir,
            iter_id=ctx.iter_id,
            verifier_name=self.name,
            task_id=ctx.selected_task_id,
        )
        if self._retry_budget > 0 and prior_fails >= self._retry_budget:
            return VerifierResult(
                verdict=Verdict.ADVISORY,
                feedback=(
                    f"`visual_judge` has FAILed {prior_fails} time(s) against "
                    f"task `{ctx.selected_task_id}`, meeting the configured "
                    f"retry budget ({self._retry_budget}). Downgrading to "
                    "ADVISORY to break the loop. See prior "
                    "`visual_judge.json` records under "
                    "`iters/exec-*/checks/verifiers/` for the per-iteration "
                    "feedback."
                ),
                details={
                    "task_id": ctx.selected_task_id,
                    "buckets_run": buckets_run,
                    "routes": list(routes),
                    "retry_budget": self._retry_budget,
                    "retry_budget_exhausted": True,
                    "prior_fails": prior_fails,
                },
            )

        parent_dir = ctx.run_dir / "iters" / ctx.iter_id / "checks" / "verifiers" / self.name
        parent_dir.mkdir(parents=True, exist_ok=True)

        common_details: dict[str, Any] = {
            "task_id": ctx.selected_task_id,
            "buckets_run": buckets_run,
            "routes": list(routes),
            "retry_budget_exhausted": False,
            "prior_fails": prior_fails,
        }

        # Step 5+6: dispatch single-bucket vs multi-bucket fan-out
        # (T5.7). The single-bucket path stays a one-shot ``run_iteration``
        # call; multi-bucket invocations (``visual_fix``) fan out per
        # bucket under a ``ThreadPoolExecutor`` and merge the per-bucket
        # verdicts per spec §5.2.1 step 6 + §9.5.
        if len(buckets) > 1:
            return self._run_fanout(
                ctx=ctx,
                hydrogen_dir=hydrogen_dir,
                parent_dir=parent_dir,
                buckets=buckets_run,
                capabilities=capabilities_payload,
                common_details=common_details,
            )

        # Step 3: boot dev server. The context manager owns teardown
        # on success *and* on exception.
        with self._dev_server_factory(hydrogen_dir) as base_url:
            # Step 4: stage sub-workspace + render the prompt.
            prompt = load_visual_judge_prompt().format(
                base_url=base_url,
                task_id=ctx.selected_task_id,
                capabilities_slice=json.dumps(
                    capability_slice,
                    indent=2,
                    sort_keys=True,
                ),
                route_list=_render_route_list(routes),
                verdict_schema=_VERDICT_SCHEMA_BLOCK,
                prior_feedback_or_empty="",
            )
            routes_payload = {
                "base_url": base_url,
                "task_id": ctx.selected_task_id,
                "buckets": buckets_run,
                "routes": list(routes),
                "viewports": ["desktop", "mobile"],
            }

            # Step 5: single nested agent iteration. ``stage_sub_workspace``
            # always materialises ``parent_dir/work`` before the runtime
            # call, so we know where to look for partial artifacts even
            # if the iteration raises before binding ``work_dir``.
            work_dir = parent_dir / "work"
            parsed: VisualVerdict | None = None
            timeout_reason: str | None = None
            try:
                work_dir, parsed = run_visual_iteration(
                    ctx.runtime,
                    parent_dir=parent_dir,
                    prompt=prompt,
                    routes=routes_payload,
                    timeout_s=self._timeout_s,
                    pass_threshold=self._pass_threshold,
                )
            except subprocess.TimeoutExpired:
                # Spec §5.4: the agent burned its wall-clock budget.
                # Don't propagate — try to recover whatever the agent did
                # capture so the next iteration sees actionable feedback
                # instead of the harness recording an opaque ERROR.
                _log.warning(
                    "visual_judge runtime invocation timed out after %.1fs",
                    self._timeout_s,
                )
                timeout_reason = (
                    f"agent iteration exceeded the {self._timeout_s:.0f}s budget"
                )
                parsed = parse_visual_verdict(
                    work_dir / "verdict.json",
                    pass_threshold=self._pass_threshold,
                )
            except Exception as exc:  # pragma: no cover -- harness wraps as ERROR
                # Non-timeout runtime crash. Re-raise so dispatch records
                # the verifier as ERROR — the failure mode is opaque to us.
                _log.warning(
                    "visual_judge runtime invocation raised: %s: %s",
                    type(exc).__name__,
                    exc,
                )
                raise

        # Step 7: promote screenshots regardless of verdict so failures
        # remain debuggable.
        _promote_screenshots(work_dir, parent_dir / _SCREENSHOTS_DIRNAME)

        # Step 6: parse + emit VerifierResult.
        if timeout_reason is not None:
            return self._timeout_result(
                ctx=ctx,
                parent_dir=parent_dir,
                common_details=common_details,
                parsed=parsed,
                timeout_reason=timeout_reason,
            )

        if parsed is None:
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    "`visual_judge` could not parse `verdict.json` from the "
                    "nested agent iteration. The agent must emit the §9.3 schema "
                    "(see prompt). Inspect `"
                    f"{(work_dir / 'verdict.json').relative_to(ctx.run_dir)}"
                    "` for the raw body."
                ),
                details={
                    **common_details,
                    "verdict_path": str(work_dir / "verdict.json"),
                    "phase": "parse",
                },
            )

        return VerifierResult(
            verdict=parsed.verdict,
            feedback=_compose_feedback(parsed),
            details={
                **common_details,
                "score": parsed.score,
                "category_scores": dict(parsed.category_scores),
                "pages_judged": parsed.pages_judged,
                "issue_count": len(parsed.issues),
                "coercion_reason": parsed.coercion_reason,
            },
        )

    def _timeout_result(
        self,
        *,
        ctx: VerifierContext,
        parent_dir: Path,
        common_details: dict[str, Any],
        parsed: VisualVerdict | None,
        timeout_reason: str,
    ) -> VerifierResult:
        """Render the FAIL surfaced when the nested agent iteration timed out.

        Always returns :attr:`Verdict.FAIL` — the budget overrun is the
        failure signal regardless of whether a partial ``verdict.json``
        was recovered. The feedback enumerates whatever evidence
        survived (parsed verdict body, on-disk screenshots) so the next
        iteration's executor sees what the judge actually saw before
        the timeout fired.
        """
        screenshots_dir = parent_dir / _SCREENSHOTS_DIRNAME
        screenshot_count = (
            sum(1 for entry in screenshots_dir.rglob("*") if entry.is_file())
            if screenshots_dir.is_dir()
            else 0
        )
        screenshots_rel = (
            str(screenshots_dir.relative_to(ctx.run_dir))
            if screenshots_dir.is_dir()
            else None
        )

        lines: list[str] = [f"`visual_judge` timed out: {timeout_reason}."]
        if parsed is not None:
            lines.append(
                f"Recovered a partial verdict (score={parsed.score:.2f}, "
                f"pages_judged={parsed.pages_judged}). The timeout is itself "
                "the FAIL — the partial body is included below for debugging.",
            )
            if parsed.feedback:
                lines.append("")
                lines.append(parsed.feedback)
        elif screenshot_count > 0 and screenshots_rel is not None:
            lines.append(
                f"No `verdict.json` was emitted, but {screenshot_count} "
                f"screenshot(s) survived under `{screenshots_rel}/` for inspection.",
            )
        else:
            lines.append(
                "No `verdict.json` and no screenshots were produced. The agent "
                "likely timed out before any page rendered — confirm the dev "
                "server is reachable and that routes return 2xx (the "
                "`routes_200` verifier is the cheap gate for this).",
            )
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback="\n".join(lines),
            details={
                **common_details,
                "phase": "timeout",
                "timeout_s": self._timeout_s,
                "screenshot_count": screenshot_count,
                "partial_verdict": parsed is not None,
                "score": parsed.score if parsed is not None else None,
                "pages_judged": parsed.pages_judged if parsed is not None else 0,
            },
        )

    def _run_fanout(
        self,
        *,
        ctx: VerifierContext,
        hydrogen_dir: Path,
        parent_dir: Path,
        buckets: list[str],
        capabilities: Mapping[str, Any],
        common_details: dict[str, Any],
    ) -> VerifierResult:
        """Multi-bucket fan-out path (spec §5.2.1 step 5-6, T5.7).

        For each active bucket: stage a ``parent_dir/<bucket>/work/``
        sub-workspace, render a per-bucket prompt scoped to that bucket's
        routes + capability slice, then submit one
        :func:`run_visual_iteration` call to a
        :class:`~concurrent.futures.ThreadPoolExecutor`. Per-bucket
        verdicts are merged into a single :class:`VerifierResult` per
        spec §5.2.1 step 6 + §9.5: weighted overall score via
        :data:`PAGE_WEIGHTS`, averaged ``category_scores``, severity-sorted
        concatenated issues. A single bucket FAIL or runtime error
        propagates to a merged FAIL.
        """
        # Pre-flight: per-bucket route + capability slice resolution.
        bucket_specs: list[_BucketSpec] = []
        for bucket in buckets:
            b_routes = bucket_routes(bucket, self._data_dir, caps=DEFAULT_CAPS)
            b_parent = parent_dir / bucket
            if not b_routes:
                # Empty bucket (e.g. dataset has no info pages). Drop
                # it from numerator and denominator per §9.5 rather than
                # FAILing the entire merge.
                bucket_specs.append(
                    _BucketSpec(
                        bucket=bucket,
                        routes=(),
                        parent_dir=b_parent,
                        skip_reason="no routes resolved for bucket",
                    ),
                )
                continue
            bucket_specs.append(
                _BucketSpec(
                    bucket=bucket,
                    routes=b_routes,
                    parent_dir=b_parent,
                    capability_slice=capabilities_for_buckets((bucket,), capabilities),
                ),
            )

        with self._dev_server_factory(hydrogen_dir) as base_url:
            # Render per-bucket prompts now that we have the dev-server URL.
            template = load_visual_judge_prompt()
            for spec in bucket_specs:
                if spec.skip_reason is not None:
                    continue
                assert spec.capability_slice is not None
                spec.rendered_prompt = template.format(
                    base_url=base_url,
                    task_id=ctx.selected_task_id,
                    capabilities_slice=json.dumps(
                        spec.capability_slice,
                        indent=2,
                        sort_keys=True,
                    ),
                    route_list=_render_route_list(spec.routes),
                    verdict_schema=_VERDICT_SCHEMA_BLOCK,
                    prior_feedback_or_empty="",
                )
                spec.routes_payload = {
                    "base_url": base_url,
                    "task_id": ctx.selected_task_id,
                    "bucket": spec.bucket,
                    "routes": list(spec.routes),
                    "viewports": ["desktop", "mobile"],
                }

            outcomes = _fan_out_buckets(
                specs=bucket_specs,
                runtime=ctx.runtime,
                timeout_s=self._timeout_s,
                max_concurrency=self._max_concurrency,
                pass_threshold=self._pass_threshold,
            )

        # Step 7 (per-bucket): promote screenshots into per-bucket subdirs
        # so reviewers can browse evidence even when a single bucket failed.
        for outcome in outcomes:
            _promote_screenshots(
                outcome.work_dir,
                parent_dir / _SCREENSHOTS_DIRNAME / outcome.bucket,
            )

        # Step 6: merge per-bucket verdicts.
        merged = _merge_bucket_outcomes(outcomes)

        # Persist a merged ``verdict.json`` next to the per-bucket subdirs
        # so the human reviewer (and replay traces) can inspect the rolled-up
        # numbers without re-running the merge.
        (parent_dir / "verdict.json").write_text(
            json.dumps(merged.payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        return VerifierResult(
            verdict=merged.verdict,
            feedback=merged.feedback,
            details={
                **common_details,
                "score": merged.score,
                "category_scores": merged.category_scores,
                "pages_judged": merged.pages_judged,
                "issue_count": merged.issue_count,
                "coercion_reason": None,
                "per_bucket": merged.per_bucket,
            },
        )


def _render_route_list(routes: Iterable[str]) -> str:
    """Render the resolved routes as a markdown bullet list."""
    return "\n".join(f"- `{route}`" for route in routes)


def _compose_feedback(parsed: VisualVerdict) -> str:
    """Build the markdown feedback body surfaced to the next iteration.

    Includes the agent's free-form ``feedback`` plus a short header
    naming the score and (when present) the coercion reason. Empty
    feedback on PASS is fine — the harness only renders feedback for
    FAIL / ADVISORY anyway.
    """
    if parsed.verdict is Verdict.PASS and not parsed.feedback:
        return ""
    lines: list[str] = [
        f"score: {parsed.score:.2f} (pages judged: {parsed.pages_judged})",
    ]
    if parsed.coercion_reason is not None:
        lines.append(f"coercion: {parsed.coercion_reason}")
    if parsed.feedback:
        lines.append("")
        lines.append(parsed.feedback)
    return "\n".join(lines)


def _promote_screenshots(work_dir: Path, dest: Path) -> None:
    """Hard-link (or copy) the agent's screenshots into the verifier's tree.

    Screenshots are looked for under ``work_dir/screenshots/`` (the
    location the prompt instructs the agent to write to). When the
    directory is absent — e.g. the agent never rendered anything, or
    the runtime stub omitted the step — the function is a no-op. The
    originals stay in place so replay-runtime traces remain
    self-contained.
    """
    src = work_dir / _SCREENSHOTS_DIRNAME
    if not src.is_dir():
        return
    dest.mkdir(parents=True, exist_ok=True)
    for entry in src.rglob("*"):
        if not entry.is_file():
            continue
        target = dest / entry.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            continue
        try:
            target.hardlink_to(entry)
        except OSError:
            # Cross-device or unsupported filesystem; fall back to copy.
            shutil.copy2(entry, target)


# --------------------------------------------------------------------------- #
# Multi-bucket fan-out helpers (T5.7)
# --------------------------------------------------------------------------- #


_SEVERITY_ORDER: Final[dict[str, int]] = {"critical": 0, "major": 1, "minor": 2}
"""Severity ordering for issue concatenation (spec §5.2.1 step 6)."""


@dataclass
class _BucketSpec:
    """Mutable scratch record for one bucket's pre-flight resolution.

    Mirrors the equivalent type in
    :mod:`shop_arena.gen.final_eval.visual_sweep`; kept private here so the
    build-loop verifier owns its own per-iteration sub-workspace layout.
    """

    bucket: str
    routes: tuple[str, ...]
    parent_dir: Path
    capability_slice: Mapping[str, Any] | None = None
    rendered_prompt: str = ""
    routes_payload: Mapping[str, Any] | None = None
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _BucketOutcome:
    """One bucket's outcome inside a fan-out run."""

    bucket: str
    routes: tuple[str, ...]
    work_dir: Path
    verdict: VisualVerdict | None
    error: str | None


@dataclass(frozen=True, slots=True)
class _MergedVerdict:
    """Merged outcome handed back to the verifier from the fan-out path."""

    verdict: Verdict
    feedback: str
    score: float
    category_scores: dict[str, float]
    pages_judged: int
    issue_count: int
    per_bucket: list[dict[str, Any]]
    payload: dict[str, Any]


def _fan_out_buckets(
    *,
    specs: list[_BucketSpec],
    runtime: Any,
    timeout_s: float,
    max_concurrency: int,
    pass_threshold: float,
) -> list[_BucketOutcome]:
    """Submit one ``run_iteration`` per spec under a thread pool.

    Skipped specs (``skip_reason is not None``) bypass the runtime call
    and surface as a :class:`_BucketOutcome` with ``verdict=None`` and
    the skip reason recorded as ``error``. Per-bucket runtime
    exceptions are captured rather than propagated so the merge step
    can record the failure against the bucket without losing the
    other buckets' verdicts.
    """
    workers = max(1, min(max_concurrency, len(specs))) if specs else 1
    results: list[_BucketOutcome | None] = [None] * len(specs)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _run_bucket,
                spec=spec,
                runtime=runtime,
                timeout_s=timeout_s,
                pass_threshold=pass_threshold,
            ): index
            for index, spec in enumerate(specs)
        }
        for future, index in futures.items():
            results[index] = future.result()
    return [r for r in results if r is not None]


def _run_bucket(
    *,
    spec: _BucketSpec,
    runtime: Any,
    timeout_s: float,
    pass_threshold: float,
) -> _BucketOutcome:
    """Run one bucket's nested iteration and parse its verdict."""
    if spec.skip_reason is not None:
        spec.parent_dir.mkdir(parents=True, exist_ok=True)
        return _BucketOutcome(
            bucket=spec.bucket,
            routes=spec.routes,
            work_dir=spec.parent_dir / "work",
            verdict=None,
            error=spec.skip_reason,
        )
    assert spec.routes_payload is not None
    try:
        work_dir, verdict = run_visual_iteration(
            runtime,
            parent_dir=spec.parent_dir,
            prompt=spec.rendered_prompt,
            routes=spec.routes_payload,
            timeout_s=timeout_s,
            pass_threshold=pass_threshold,
        )
    except Exception as exc:
        _log.warning(
            "visual_judge: bucket %s runtime invocation raised: %s: %s",
            spec.bucket,
            type(exc).__name__,
            exc,
        )
        return _BucketOutcome(
            bucket=spec.bucket,
            routes=spec.routes,
            work_dir=spec.parent_dir / "work",
            verdict=None,
            error=f"runtime raised {type(exc).__name__}: {exc}",
        )
    error: str | None = None
    if verdict is None:
        error = "missing or malformed verdict.json"
    return _BucketOutcome(
        bucket=spec.bucket,
        routes=spec.routes,
        work_dir=work_dir,
        verdict=verdict,
        error=error,
    )


def _merge_bucket_outcomes(outcomes: list[_BucketOutcome]) -> _MergedVerdict:
    """Merge per-bucket outcomes per spec §5.2.1 step 6 + §9.5.

    * Weighted overall ``score`` via :data:`PAGE_WEIGHTS`. Buckets with
      no routes (``skip_reason``) drop from both numerator and
      denominator so the weighted average stays well-defined.
    * ``category_scores`` averaged per key across the buckets that
      emitted that key.
    * Issues concatenated across buckets, severity-sorted
      (``critical`` → ``major`` → ``minor``), bucket name as the
      stable secondary key.
    * Merged verdict is :attr:`Verdict.FAIL` if any usable bucket
      failed **or** any bucket errored (missing verdict.json, runtime
      crash); :attr:`Verdict.PASS` only when every usable bucket
      passed and no errors surfaced.
    """
    usable: list[_BucketOutcome] = []
    errored: list[_BucketOutcome] = []
    skipped: list[_BucketOutcome] = []
    for outcome in outcomes:
        if outcome.verdict is not None:
            usable.append(outcome)
        elif outcome.error == "no routes resolved for bucket":
            skipped.append(outcome)
        else:
            errored.append(outcome)

    score = _weighted_score(usable)
    category_scores = _average_category_scores(usable)
    pages_judged = sum(o.verdict.pages_judged for o in usable if o.verdict is not None)
    issue_count = sum(len(o.verdict.issues) for o in usable if o.verdict is not None)

    has_fail = any(o.verdict is not None and o.verdict.verdict is Verdict.FAIL for o in usable)
    has_error = bool(errored)
    final_verdict = Verdict.FAIL if (has_fail or has_error) else Verdict.PASS

    feedback = _render_merged_feedback(
        usable=usable,
        errored=errored,
        score=score,
        pages_judged=pages_judged,
    )

    per_bucket = [_serialise_outcome(o) for o in outcomes]
    payload: dict[str, Any] = {
        "verdict": "pass" if final_verdict is Verdict.PASS else "fail",
        "score": round(score, 2),
        "category_scores": {k: round(v, 2) for k, v in category_scores.items()},
        "pages_judged": pages_judged,
        "feedback": feedback,
        "per_bucket": per_bucket,
    }

    return _MergedVerdict(
        verdict=final_verdict,
        feedback=feedback,
        score=round(score, 2),
        category_scores={k: round(v, 2) for k, v in category_scores.items()},
        pages_judged=pages_judged,
        issue_count=issue_count,
        per_bucket=per_bucket,
        payload=payload,
    )


def _weighted_score(usable: list[_BucketOutcome]) -> float:
    """Compute the §9.5 weighted score over usable buckets only."""
    score_num = 0.0
    weight_sum = 0.0
    for outcome in usable:
        if outcome.verdict is None:
            continue
        weight = PAGE_WEIGHTS.get(outcome.bucket, 0.0)
        if weight <= 0.0:
            continue
        score_num += weight * outcome.verdict.score
        weight_sum += weight
    if weight_sum <= 0.0:
        return 0.0
    return score_num / weight_sum


def _average_category_scores(usable: list[_BucketOutcome]) -> dict[str, float]:
    """Average per-category scores across the buckets that emitted each key."""
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for outcome in usable:
        if outcome.verdict is None:
            continue
        for key, value in outcome.verdict.category_scores.items():
            sums[key] = sums.get(key, 0.0) + float(value)
            counts[key] = counts.get(key, 0) + 1
    return {key: sums[key] / counts[key] for key in sums}


def _render_merged_feedback(
    *,
    usable: list[_BucketOutcome],
    errored: list[_BucketOutcome],
    score: float,
    pages_judged: int,
) -> str:
    """Render merged markdown feedback (severity-sorted issues + per-bucket bodies)."""
    issues: list[tuple[str, Any]] = []
    for outcome in usable:
        if outcome.verdict is None:
            continue
        for issue in outcome.verdict.issues:
            issues.append((outcome.bucket, issue))
    issues.sort(
        key=lambda pair: (
            _SEVERITY_ORDER.get(pair[1].severity, 99),
            pair[0],
            pair[1].route,
        ),
    )

    lines: list[str] = [
        f"score: {score:.2f} (pages judged: {pages_judged})",
    ]
    if errored:
        lines.append("")
        lines.append("## Bucket errors")
        for outcome in errored:
            lines.append(f"- `{outcome.bucket}`: {outcome.error or 'unknown error'}")
    if issues:
        lines.append("")
        lines.append("## Issues")
        for bucket, issue in issues:
            lines.append(
                f"- [{issue.severity}] `{bucket}` `{issue.route}` "
                f"({issue.viewport}): {issue.summary}",
            )
    for outcome in usable:
        if outcome.verdict is None:
            continue
        body = outcome.verdict.feedback.strip()
        if not body:
            continue
        lines.append("")
        lines.append(f"## `{outcome.bucket}`")
        lines.append("")
        lines.append(body)
    return "\n".join(lines).rstrip()


def _serialise_outcome(outcome: _BucketOutcome) -> dict[str, Any]:
    """Project a :class:`_BucketOutcome` onto a JSON-serialisable dict."""
    if outcome.verdict is None:
        return {
            "bucket": outcome.bucket,
            "routes": list(outcome.routes),
            "verdict": None,
            "score": None,
            "category_scores": {},
            "pages_judged": 0,
            "issue_count": 0,
            "error": outcome.error,
        }
    return {
        "bucket": outcome.bucket,
        "routes": list(outcome.routes),
        "verdict": "pass" if outcome.verdict.verdict is Verdict.PASS else "fail",
        "score": outcome.verdict.score,
        "category_scores": dict(outcome.verdict.category_scores),
        "pages_judged": outcome.verdict.pages_judged,
        "issue_count": len(outcome.verdict.issues),
        "error": None,
    }


__all__ = ["VisualJudgeVerifier"]
