"""Phase 5 visual-sweep driver (impl plan T5.1, spec §5.6 + §9.4).

The post-loop visual sweep walks every page bucket of the published
storefront, asks the agent runtime to render each bucket's routes via
the playwright skill, and captures structured per-bucket verdicts that
the :mod:`shop_arena.gen.final_eval.step` driver merges into
``final_eval.json`` under the ``visual`` subtree (T5.3, spec §5.6
step 6).

T5.1 lands the **driver** only:

* Resolve the all-pages route set via
  :func:`shop_arena.gen.build.verifiers._task_routes.routes_for_buckets`
  with the wider :data:`SWEEP_CAPS` profile.
* Boot the dev server through the injected
  :class:`~shop_arena.gen.final_eval.playwright_smoke.DevServerFactory`.
* Stage one sub-workspace per page bucket under
  ``<out_dir>/visual_eval/work/<bucket>/`` and fan out
  ``runtime.run_iteration(...)`` calls under a
  :class:`~concurrent.futures.ThreadPoolExecutor` so wall-clock scales
  with the longest bucket, not the sum (spec §5.2.1 step 5, §5.6
  step 4).
* Parse each bucket's ``verdict.json`` via
  :func:`shop_arena.gen.build.verifiers._runtime_call.parse_visual_verdict`.
* Promote screenshots into ``<out_dir>/visual_eval/screenshots/<bucket>/<page>/``.
* Write a markdown summary to ``<out_dir>/visual_eval/report.md``.

Subsequent tasks (T5.3 / T5.4 / T5.6) wire this driver into the
``final_eval`` step, add config knobs, and gate the sweep behind the
playwright skill probe. The driver itself is **non-raising by
contract** for per-bucket failures: a missing or malformed
``verdict.json`` is recorded against the bucket and the other buckets
still run. Wiring failures (missing hydrogen tree, dev-server boot
errors) propagate so the caller can record them in the
``visual.error`` field of ``final_eval.json``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from harness.runtimes.base import AgentRuntime
from harness.verifiers import Verdict
from shop_arena.gen.build.verifiers._runtime_call import (
    VisualVerdict,
    parse_visual_verdict,
    stage_sub_workspace,
)
from shop_arena.gen.build.verifiers._skills import is_playwright_skill_available
from shop_arena.gen.build.verifiers._task_routes import (
    BUCKET_CAPABILITY_KEYS,
    PAGE_WEIGHTS,
    SWEEP_CAPS,
    TASK_BUCKETS,
    BucketCaps,
    bucket_routes,
    capabilities_for_buckets,
)
from shop_arena.gen.final_eval.playwright_smoke import DevServerFactory

_log = logging.getLogger(__name__)

_VISUAL_EVAL_DIRNAME: Final[str] = "visual_eval"
"""Top-level dir under ``out_dir`` published by the sweep (spec §5.7)."""

_WORK_DIRNAME: Final[str] = "work"
"""Sub-workspace root under ``visual_eval/``; one subdir per bucket."""

_SCREENSHOTS_DIRNAME: Final[str] = "screenshots"
"""Promoted-screenshot root under ``visual_eval/`` (per-bucket subdirs)."""

_REPORT_FILENAME: Final[str] = "report.md"
"""Markdown summary written under ``visual_eval/`` (spec §5.6 step 5)."""

_DEFAULT_TIMEOUT_S: Final[float] = 900.0
"""Wall-clock budget per per-bucket nested iteration (spec §5.6 step 4)."""

_DEFAULT_MAX_CONCURRENCY: Final[int] = 3
"""Default ``ThreadPoolExecutor`` width (spec §5.2.1 step 5)."""

_DEFAULT_PASS_THRESHOLD: Final[float] = 7.0
"""Score floor reused from §9.3 for the per-bucket coercion rule."""

_VISUAL_FIX_TASK_ID: Final[str] = "visual_fix"
"""Source key in :data:`TASK_BUCKETS` for the all-pages bucket set."""

_SKILL_UNAVAILABLE_ERROR: Final[str] = "playwright skill not available"
"""Diagnostic written into ``visual.error`` when the skill probe fails (spec §5.5.1)."""

_VERDICT_SCHEMA_BLOCK: Final[str] = """\
{
  "verdict": "pass | fail",                  // required; lowercase (advisory only)
  "score": 7.8,                               // required; 0-10 float
  "category_scores": {                        // optional; same 0-10 scale
    "structure": 8,
    "components": 7,
    "visual_tone": 8
  },
  "feedback": "markdown body",                // required on fail; "" allowed on pass
  "pages_judged": 4,                          // required; (route, viewport) pairs judged
  "issues": [
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
"""§9.3 schema body shared with the build-loop ``visual_judge`` prompt."""


class PlaywrightSkillUnavailableError(RuntimeError):
    """Raised when the playwright skill is not installed (spec §5.5.1).

    The visual sweep depends on the ``pi-playwright`` skill to render
    each page bucket. When the skill probe
    (:func:`shop_arena.gen.build.verifiers._skills.is_playwright_skill_available`)
    fails, :func:`run_visual_sweep` raises this exception **before** any
    on-disk artifact is created so callers can record a clean
    ``visual.error`` entry without leaving an empty ``visual_eval/``
    directory behind.
    """


@dataclass(frozen=True, slots=True)
class BucketResult:
    """One bucket's outcome inside a visual-sweep run.

    Attributes:
        bucket: Page-bucket name (e.g. ``"homepage"``).
        routes: Routes resolved for the bucket (sorted source order).
        verdict: Parsed structured verdict, or ``None`` when the agent
            did not emit a usable ``verdict.json`` for this bucket.
        error: Short diagnostic when ``verdict`` is ``None`` (missing
            file, parse failure, runtime exception); ``None`` otherwise.
        work_dir: Per-bucket sub-workspace under
            ``<out_dir>/visual_eval/work/<bucket>/`` (always created so
            failures remain debuggable).
    """

    bucket: str
    routes: tuple[str, ...]
    verdict: VisualVerdict | None
    error: str | None
    work_dir: Path


def run_visual_sweep(
    *,
    out_dir: Path,
    data_dir: Path,
    hydrogen_dir: Path,
    runtime: AgentRuntime,
    dev_server_factory: DevServerFactory,
    capabilities: Mapping[str, Any],
    prompt_template: str,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    max_concurrency: int = _DEFAULT_MAX_CONCURRENCY,
    pass_threshold: float = _DEFAULT_PASS_THRESHOLD,
    caps: BucketCaps = SWEEP_CAPS,
) -> dict[str, Any]:
    """Drive the all-pages visual sweep and return a per-bucket summary.

    Spec §5.6 lifecycle: resolve the page set, boot the dev server, fan
    out one ``runtime.run_iteration`` per page bucket under a thread
    pool, parse the per-bucket ``verdict.json`` documents, promote
    screenshots, and write the markdown summary. The returned mapping
    is JSON-serialisable so :mod:`shop_arena.gen.final_eval.step` can lift
    fields directly into ``final_eval.json`` (T5.3) without re-running
    the driver.

    Args:
        out_dir: Run workspace. The sweep writes its artifacts under
            ``<out_dir>/visual_eval/``.
        data_dir: Directory containing the published
            ``collections.json`` / ``products.json`` / ``pages.json``
            files. Forwarded to :func:`bucket_routes` so resolved
            routes carry real handles.
        hydrogen_dir: Hydrogen tree the dev-server factory roots at.
        runtime: Agent runtime instance. The same instance the build
            loop drove executor iterations with.
        dev_server_factory: Boots the transient dev server; one boot
            shared across every bucket in the fan-out.
        capabilities: Merged ``capabilities.json`` body. Sliced
            per-bucket via :func:`capabilities_for_buckets` before
            being rendered into each bucket's prompt.
        prompt_template: ``str.format()`` template carrying the slots
            ``{base_url}``, ``{bucket}``, ``{capabilities_slice}``,
            ``{route_list}``, ``{verdict_schema}``, and
            ``{prior_feedback_or_empty}``. T5.2 lands the production
            template; tests inject a stub.
        timeout_s: Wall-clock budget per nested iteration.
        max_concurrency: ``ThreadPoolExecutor`` width.
        pass_threshold: Score floor for the §9.3 coercion rule.
        caps: Sampling caps; defaults to :data:`SWEEP_CAPS`.

    Returns:
        Mapping with keys:

        * ``base_url`` — dev-server URL the buckets were judged against.
        * ``buckets`` — sorted list of bucket names walked.
        * ``per_bucket`` — list of per-bucket dicts (``verdict``,
          ``score``, ``category_scores``, ``pages_judged``, ``feedback``,
          ``issues``, ``routes``, ``error``).
        * ``pages_judged`` — sum of per-bucket ``pages_judged`` across
          buckets that emitted a usable verdict.
        * ``report_path`` — POSIX path (relative to ``out_dir``) of the
          markdown summary.

    Raises:
        PlaywrightSkillUnavailableError: The ``pi-playwright`` skill probe
            failed (spec §5.5.1). Raised before any on-disk artifact
            is created so the caller can record ``visual.error`` and
            leave the run free of empty ``visual_eval/`` directories.
    """
    if not is_playwright_skill_available():
        _log.warning(
            "visual sweep skipped: pi-playwright skill not found. "
            "Install with `pnpm add -g pi-playwright` (or "
            "`npm i -g pi-playwright`) to enable.",
        )
        raise PlaywrightSkillUnavailableError(_SKILL_UNAVAILABLE_ERROR)
    visual_eval_dir = out_dir / _VISUAL_EVAL_DIRNAME
    work_root = visual_eval_dir / _WORK_DIRNAME
    screenshots_root = visual_eval_dir / _SCREENSHOTS_DIRNAME
    visual_eval_dir.mkdir(parents=True, exist_ok=True)

    visual_fix_buckets = TASK_BUCKETS[_VISUAL_FIX_TASK_ID]
    buckets_sorted = sorted(visual_fix_buckets)

    bucket_specs: list[_BucketSpec] = []
    for bucket in buckets_sorted:
        routes = tuple(bucket_routes(bucket, data_dir, caps=caps))
        if not routes:
            # Bucket resolved to no routes (empty dataset, e.g. no info
            # pages). Record it as a no-op rather than fanning out a
            # render with nothing to judge.
            bucket_specs.append(
                _BucketSpec(
                    bucket=bucket,
                    routes=routes,
                    work_dir=work_root / bucket,
                    skip_reason="no routes resolved for bucket",
                ),
            )
            continue
        bucket_specs.append(
            _BucketSpec(
                bucket=bucket,
                routes=routes,
                work_dir=work_root / bucket,
                capability_slice=capabilities_for_buckets((bucket,), capabilities),
            ),
        )

    with dev_server_factory(hydrogen_dir) as base_url:
        # Render the per-bucket prompts now that we have the dev-server
        # URL; bucket / route_list / capability_slice are already
        # resolved from the pre-flight pass above.
        for spec in bucket_specs:
            if spec.skip_reason is not None:
                continue
            assert spec.capability_slice is not None
            spec.rendered_prompt = prompt_template.format(
                base_url=base_url,
                bucket=spec.bucket,
                capabilities_slice=json.dumps(
                    spec.capability_slice,
                    indent=2,
                    sort_keys=True,
                ),
                route_list=_render_route_list(spec.routes),
                verdict_schema=_VERDICT_SCHEMA_BLOCK,
                prior_feedback_or_empty="",
            )

        results = _fan_out(
            specs=bucket_specs,
            runtime=runtime,
            timeout_s=timeout_s,
            max_concurrency=max_concurrency,
            pass_threshold=pass_threshold,
        )

    # Promote screenshots out of every bucket's sub-workspace, even on
    # failure — the human reviewer needs the on-disk evidence.
    for result in results:
        _promote_bucket_screenshots(
            work_dir=result.work_dir,
            dest=screenshots_root / result.bucket,
        )

    report_path = visual_eval_dir / _REPORT_FILENAME
    report_path.write_text(_render_report(results, base_url=base_url), encoding="utf-8")

    pages_judged = sum(r.verdict.pages_judged for r in results if r.verdict is not None)

    return {
        "base_url": base_url,
        "buckets": buckets_sorted,
        "per_bucket": [_serialise_result(r) for r in results],
        "pages_judged": pages_judged,
        "report_path": report_path.relative_to(out_dir).as_posix(),
    }


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


@dataclass
class _BucketSpec:
    """Mutable scratch record for one bucket's pre-flight resolution."""

    bucket: str
    routes: tuple[str, ...]
    work_dir: Path
    capability_slice: Mapping[str, Any] | None = None
    rendered_prompt: str = ""
    skip_reason: str | None = None


def _fan_out(
    *,
    specs: list[_BucketSpec],
    runtime: AgentRuntime,
    timeout_s: float,
    max_concurrency: int,
    pass_threshold: float,
) -> list[BucketResult]:
    """Fan out one ``run_iteration`` per spec under a thread pool.

    Skipped specs (``skip_reason is not None``) bypass the runtime call
    and surface as :class:`BucketResult` with ``verdict=None`` and the
    skip reason recorded as ``error``. The result list mirrors the
    input order so the caller can reason about per-bucket positions.
    """
    workers = max(1, min(max_concurrency, len(specs))) if specs else 1
    results: list[BucketResult | None] = [None] * len(specs)
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
    # All slots filled by the executor join above.
    return [r for r in results if r is not None]


def _run_bucket(
    *,
    spec: _BucketSpec,
    runtime: AgentRuntime,
    timeout_s: float,
    pass_threshold: float,
) -> BucketResult:
    """Run one bucket's nested iteration and parse its verdict."""
    if spec.skip_reason is not None:
        spec.work_dir.mkdir(parents=True, exist_ok=True)
        return BucketResult(
            bucket=spec.bucket,
            routes=spec.routes,
            verdict=None,
            error=spec.skip_reason,
            work_dir=spec.work_dir,
        )

    work = stage_sub_workspace(
        spec.work_dir,
        prompt=spec.rendered_prompt,
        routes={
            "bucket": spec.bucket,
            "routes": list(spec.routes),
            "viewports": ["desktop", "mobile"],
        },
    )
    try:
        runtime.run_iteration(
            run_dir=work,
            iter_dir=work / "iter",
            prompt=spec.rendered_prompt,
            timeout=timeout_s,
        )
    except Exception as exc:  # pragma: no cover - exercised via stub raising path
        _log.warning(
            "visual_sweep: bucket %s runtime invocation raised: %s: %s",
            spec.bucket,
            type(exc).__name__,
            exc,
        )
        return BucketResult(
            bucket=spec.bucket,
            routes=spec.routes,
            verdict=None,
            error=f"runtime raised {type(exc).__name__}: {exc}",
            work_dir=work,
        )

    verdict = parse_visual_verdict(
        work / "verdict.json",
        pass_threshold=pass_threshold,
    )
    error: str | None = None
    if verdict is None:
        error = "missing or malformed verdict.json"
    return BucketResult(
        bucket=spec.bucket,
        routes=spec.routes,
        verdict=verdict,
        error=error,
        work_dir=work,
    )


def _render_route_list(routes: tuple[str, ...]) -> str:
    """Render the resolved routes as a markdown bullet list."""
    return "\n".join(f"- `{route}`" for route in routes)


def _promote_bucket_screenshots(*, work_dir: Path, dest: Path) -> None:
    """Promote ``work_dir/screenshots/`` into ``dest`` per page subdir.

    The agent writes screenshots into ``./screenshots/`` using the
    ``<slug>__<viewport>.png`` naming convention from the visual-judge
    prompt; the sweep promotes each file under
    ``<dest>/<slug>/<viewport>.png`` so reviewers can browse per-page
    folders. Filenames that do not match the pattern are dropped at
    the bucket root so nothing is silently lost.
    """
    src = work_dir / _SCREENSHOTS_DIRNAME
    if not src.is_dir():
        return
    for entry in sorted(src.rglob("*")):
        if not entry.is_file():
            continue
        stem = entry.stem
        if "__" in stem:
            slug, _, viewport = stem.rpartition("__")
            target = dest / slug / f"{viewport}{entry.suffix}"
        else:
            target = dest / entry.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            continue
        try:
            target.hardlink_to(entry)
        except OSError:
            shutil.copy2(entry, target)


def _serialise_result(result: BucketResult) -> dict[str, Any]:
    """Project a :class:`BucketResult` onto a JSON-serialisable dict."""
    if result.verdict is None:
        return {
            "bucket": result.bucket,
            "routes": list(result.routes),
            "verdict": None,
            "score": None,
            "category_scores": {},
            "pages_judged": 0,
            "feedback": "",
            "issues": [],
            "error": result.error,
        }
    return {
        "bucket": result.bucket,
        "routes": list(result.routes),
        "verdict": "pass" if result.verdict.verdict is Verdict.PASS else "fail",
        "score": result.verdict.score,
        "category_scores": dict(result.verdict.category_scores),
        "pages_judged": result.verdict.pages_judged,
        "feedback": result.verdict.feedback,
        "issues": [
            {
                "route": issue.route,
                "viewport": issue.viewport,
                "screenshot": issue.screenshot,
                "severity": issue.severity,
                "summary": issue.summary,
                "capability": issue.capability,
            }
            for issue in result.verdict.issues
        ],
        "error": None,
    }


def _render_report(results: list[BucketResult], *, base_url: str) -> str:
    """Render the human-readable ``report.md`` body.

    Spec §5.6 step 5: a markdown summary surfaced for human review.
    The report carries one section per bucket with the parsed verdict,
    score, route list, and any issues. Failures (missing
    ``verdict.json``, runtime crashes) are recorded so the reviewer
    sees which bucket short-circuited.
    """
    lines: list[str] = [
        "# Visual sweep report",
        "",
        f"Base URL: `{base_url}`",
        "",
        f"Buckets walked: {len(results)}",
        "",
    ]
    for result in results:
        lines.append(f"## `{result.bucket}`")
        lines.append("")
        if result.verdict is None:
            lines.append(f"- verdict: **error** — {result.error or 'unknown'}")
            lines.append(f"- routes: {len(result.routes)}")
            lines.append("")
            continue
        verdict_token = "pass" if result.verdict.verdict is Verdict.PASS else "fail"
        lines.append(f"- verdict: **{verdict_token}**")
        lines.append(f"- score: {result.verdict.score:.2f}")
        lines.append(f"- pages judged: {result.verdict.pages_judged}")
        lines.append(f"- routes: {len(result.routes)}")
        if result.verdict.category_scores:
            categories = ", ".join(
                f"{k}={v:.1f}" for k, v in sorted(result.verdict.category_scores.items())
            )
            lines.append(f"- category scores: {categories}")
        if result.verdict.coercion_reason is not None:
            lines.append(f"- coercion: {result.verdict.coercion_reason}")
        if result.verdict.issues:
            lines.append("")
            lines.append("Issues:")
            for issue in result.verdict.issues:
                lines.append(
                    f"- [{issue.severity}] `{issue.route}` ({issue.viewport}): {issue.summary}",
                )
        if result.verdict.feedback:
            lines.append("")
            lines.append(result.verdict.feedback)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Merge driver — projects the per-bucket payload onto the `visual` subtree
# --------------------------------------------------------------------------- #


_VERDICT_PASS: Final[str] = "pass"
_VERDICT_FAIL: Final[str] = "fail"

_SEVERITY_ORDER: Final[dict[str, int]] = {"critical": 0, "major": 1, "minor": 2}
"""Severity ordering for issue concatenation (spec §5.2.1 step 6)."""

_NO_ROUTES_SKIP_REASON: Final[str] = "no routes resolved for bucket"
"""Per-bucket ``error`` value emitted when a bucket has no routes; dropped from the merge."""


def merge_sweep_to_visual_subtree(report: Mapping[str, Any]) -> dict[str, Any]:
    """Project a :func:`run_visual_sweep` payload onto the ``visual`` subtree.

    Implements the spec §5.2.1 step 6 + §9.5 merge:

    * Weighted overall ``score`` via :data:`PAGE_WEIGHTS`. Buckets absent
      from a fan-out (no routes) are dropped from both numerator and
      denominator so the weighted average stays well-defined (§9.5).
    * ``category_scores`` averaged per key across the buckets that
      emitted that key.
    * Issues concatenated across buckets, severity-sorted
      (``critical`` → ``major`` → ``minor``), bucket name as the
      stable secondary key.
    * Merged verdict is ``"fail"`` if any usable bucket failed **or**
      any bucket errored (missing / malformed verdict, runtime crash);
      ``"pass"`` only when every usable bucket passed and no errors
      surfaced.

    Args:
        report: The mapping returned by :func:`run_visual_sweep`. Must
            carry a ``per_bucket`` list and a ``report_path`` string.

    Returns:
        JSON-serialisable mapping with the §4.1 ``visual`` subtree
        keys: ``ok``, ``verdict``, ``score``, ``category_scores``,
        ``pages_judged``, ``feedback``, ``report_path``, plus an
        ``error`` field that is ``None`` on a clean run and a short
        diagnostic enumerating the errored buckets otherwise.
    """
    per_bucket = list(report.get("per_bucket", []))

    usable: list[Mapping[str, Any]] = []
    errored: list[Mapping[str, Any]] = []
    for entry in per_bucket:
        if entry.get("verdict") is not None:
            usable.append(entry)
        elif entry.get("error") == _NO_ROUTES_SKIP_REASON:
            # Empty dataset — drop from numerator and denominator (§9.5).
            continue
        else:
            errored.append(entry)

    weighted_score = _weighted_score(usable)
    category_scores = _average_category_scores(usable)
    pages_judged = sum(int(entry["pages_judged"]) for entry in usable)

    has_fail = any(entry["verdict"] == _VERDICT_FAIL for entry in usable)
    has_error = bool(errored)
    merged_verdict = _VERDICT_FAIL if (has_fail or has_error) else _VERDICT_PASS

    feedback = _render_merged_feedback(usable=usable, errored=errored)
    error_msg = _render_error_summary(errored) if errored else None

    return {
        "ok": merged_verdict == _VERDICT_PASS and not has_error,
        "verdict": merged_verdict,
        "score": round(weighted_score, 2),
        "category_scores": {k: round(v, 2) for k, v in category_scores.items()},
        "pages_judged": pages_judged,
        "feedback": feedback,
        "report_path": report.get("report_path"),
        "error": error_msg,
    }


def _weighted_score(usable: list[Mapping[str, Any]]) -> float:
    """Compute the §9.5 weighted score over usable buckets only."""
    score_num = 0.0
    weight_sum = 0.0
    for entry in usable:
        weight = PAGE_WEIGHTS.get(entry["bucket"], 0.0)
        if weight <= 0.0:
            continue
        score_num += weight * float(entry["score"])
        weight_sum += weight
    if weight_sum <= 0.0:
        return 0.0
    return score_num / weight_sum


def _average_category_scores(
    usable: list[Mapping[str, Any]],
) -> dict[str, float]:
    """Average per-category scores across the buckets that emitted each key."""
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for entry in usable:
        cats: Mapping[str, Any] = entry.get("category_scores") or {}
        for key, value in cats.items():
            sums[key] = sums.get(key, 0.0) + float(value)
            counts[key] = counts.get(key, 0) + 1
    return {key: sums[key] / counts[key] for key in sums}


def _render_merged_feedback(
    *,
    usable: list[Mapping[str, Any]],
    errored: list[Mapping[str, Any]],
) -> str:
    """Render the merged feedback body (severity-sorted issues + per-bucket bodies)."""
    issues: list[tuple[str, Mapping[str, Any]]] = []
    for entry in usable:
        for issue in entry.get("issues") or ():
            issues.append((entry["bucket"], issue))
    issues.sort(
        key=lambda pair: (
            _SEVERITY_ORDER.get(pair[1].get("severity", ""), 99),
            pair[0],
            pair[1].get("route", ""),
        ),
    )

    lines: list[str] = []
    if errored:
        lines.append("## Bucket errors")
        for entry in errored:
            lines.append(f"- `{entry['bucket']}`: {entry.get('error') or 'unknown error'}")
        lines.append("")
    if issues:
        lines.append("## Issues")
        for bucket, issue in issues:
            lines.append(
                f"- [{issue.get('severity', '?')}] `{bucket}` "
                f"`{issue.get('route', '?')}` ({issue.get('viewport', '?')}): "
                f"{issue.get('summary', '')}",
            )
        lines.append("")
    for entry in usable:
        body = (entry.get("feedback") or "").strip()
        if not body:
            continue
        lines.append(f"## `{entry['bucket']}`")
        lines.append("")
        lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_error_summary(errored: list[Mapping[str, Any]]) -> str:
    """Short diagnostic enumerating the errored bucket names."""
    parts = [f"{entry['bucket']}: {entry.get('error') or 'unknown'}" for entry in errored]
    return "; ".join(parts)


# Re-export the bucket capability key map so callers that want to
# render a custom prompt slice do not need to reach into
# :mod:`shop_arena.gen.build.verifiers._task_routes` directly.
__all__ = [
    "BUCKET_CAPABILITY_KEYS",
    "BucketResult",
    "PlaywrightSkillUnavailableError",
    "merge_sweep_to_visual_subtree",
    "run_visual_sweep",
]
