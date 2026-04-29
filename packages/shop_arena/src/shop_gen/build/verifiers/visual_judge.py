"""``visual_judge`` build-loop verifier (impl plan T1.4, spec §5.2).

Per-task visual quality gate. Resolves the executor's
``selected_task_id`` to a page-bucket scope, boots the dev server,
hands a sub-workspace to ``ctx.runtime.run_iteration`` so the agent
can drive the playwright skill against the rendered pages, and
parses the structured ``verdict.json`` the agent writes back. The
score → verdict coercion rules from spec §9.3 are applied inside
:mod:`shop_gen.build.verifiers._runtime_call`.

This M1 landing covers per-task invocations only
(``gen_homepage``, ``gen_product``, …). The ``consolidate``
page-bucket fan-out and the retry-budget check land later
(T5.7 + T2.1).

The verifier reads:

* ``ctx.artifact_dir / "capabilities.json"`` — merged capabilities
  document seeded by the build loop. The slice handed to the agent
  is filtered to the active bucket(s) per spec §5.3.1 so the judge
  never sees (or penalises the absence of) features that belong to
  a different bucket.
* ``data_dir / {collections,products,pages}.json`` — supplied at
  construction time and used by
  :func:`shop_gen.build.verifiers._task_routes.routes_for_buckets`
  to materialise the route list for the active bucket(s).
* ``ctx.artifact_dir / "hydrogen"`` — the dev-server root the
  injected :class:`~shop_gen.final_eval.playwright_smoke.DevServerFactory`
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
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

from harness.verifiers import Verdict, VerifierContext, VerifierResult
from shop_gen.build.prompts import load_visual_judge_prompt
from shop_gen.build.verifiers._runtime_call import (
    VisualVerdict,
    run_visual_iteration,
)
from shop_gen.build.verifiers._task_routes import (
    DEFAULT_CAPS,
    buckets_for_task,
    capabilities_for_buckets,
    routes_for_buckets,
)
from shop_gen.final_eval.playwright_smoke import DevServerFactory

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
"""Per-task retry budget surface; M1 stores it without enforcement (T2.1 wires the check)."""

_DEFAULT_PASS_THRESHOLD: Final[float] = 7.0
"""Score floor below which an emitted ``pass`` is coerced to ``fail`` (spec §9.3)."""

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
        "visual_polish",
        # ``consolidate`` is intentionally excluded in M1; it lands
        # back in T5.7 alongside the page-bucket ThreadPoolExecutor
        # fan-out the multi-bucket merge requires.
    },
)
"""Default applicability set per spec §5.2 (minus ``consolidate``, M1 scope)."""

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
        applicable_tasks: Iterable[str] | None = None,
    ) -> None:
        """Build the verifier with optional injection seams.

        Args:
            data_dir: Directory containing the published
                ``collections.json`` / ``products.json`` /
                ``pages.json`` files. Forwarded to
                :func:`shop_gen.build.verifiers._task_routes.routes_for_buckets`
                so resolved routes carry real handles.
            dev_server_factory: Shared dev-server factory protocol;
                production wiring is the ``pnpm dev`` runner that
                lands in T6.1, tests inject a stub yielding a
                deterministic base URL.
            retry_budget: Per-task cap on consecutive ``visual_judge``
                FAILs before the verifier downgrades to ADVISORY.
                Stored in M1; the count check itself lands in T2.1.
            timeout_s: Wall-clock budget for the nested agent
                iteration. Defaults to :data:`_DEFAULT_TIMEOUT_S`.
            pass_threshold: Score floor for the §9.3 coercion rule.
                Defaults to :data:`_DEFAULT_PASS_THRESHOLD`.
            applicable_tasks: Override the default applicability set.
                Defaults to :data:`_DEFAULT_TASKS` (M1 scope, minus
                ``consolidate``).
        """
        self._data_dir = data_dir
        self._dev_server_factory = dev_server_factory
        self._retry_budget = retry_budget
        self._timeout_s = timeout_s
        self._pass_threshold = pass_threshold
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

        Spec §5.2.1 lifecycle — M1 implements steps 1, 3-7 of the
        eight-step contract; the retry-budget check (step 2) lands in
        T2.1, and the multi-bucket fan-out (the ``consolidate`` arm
        of step 5 + the merge in step 6) lands in T5.7.

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

        parent_dir = ctx.run_dir / "iters" / ctx.iter_id / "checks" / "verifiers" / self.name
        parent_dir.mkdir(parents=True, exist_ok=True)

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

            # Step 5: single nested agent iteration (consolidate fan-out lands in T5.7).
            try:
                work_dir, parsed = run_visual_iteration(
                    ctx.runtime,
                    parent_dir=parent_dir,
                    prompt=prompt,
                    routes=routes_payload,
                    timeout_s=self._timeout_s,
                    pass_threshold=self._pass_threshold,
                )
            except Exception as exc:  # pragma: no cover -- harness wraps as ERROR
                # Re-raise so dispatch records the verifier as ERROR.
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
        common_details: dict[str, Any] = {
            "task_id": ctx.selected_task_id,
            "buckets_run": buckets_run,
            "routes": list(routes),
            "retry_budget_exhausted": False,
            "prior_fails": 0,
        }

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


__all__ = ["VisualJudgeVerifier"]
