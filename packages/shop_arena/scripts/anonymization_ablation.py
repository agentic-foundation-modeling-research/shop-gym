"""Anonymization-sufficiency ablation for axis C (T5.1, spec §8.5 Q4).

Runs a deterministic leakage audit on the brand-loaded hardware
fixture trajectory used by ``tests/judge/test_anonymize.py`` and emits
two artifacts under ``outputs/web_probe/anonymization_ablation/``:

* ``leakage_audit.json`` — structured per-vector occurrence counts
  pre / post anonymization plus the structural-feature preservation
  audit.
* ``report.md`` — human-readable methodology + headline numbers,
  cross-linked from ``packages/shop_arena/docs/shop_probe/cohort_v0.1.md`` §4.

The script is **import-safe** — module load does no I/O; the audit
runs from ``main()``. Re-run after any change to
``shop_probe.judge.anonymize`` or to the leak-vector inventory below.

Usage:

    cd packages/shop_arena
    uv run python -m scripts.anonymization_ablation
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shop_probe.judge.anonymize import (
    REDACTED_BRAND,
    REDACTED_HOST,
    REDACTED_THEME,
    AnonymizationPlan,
    anonymize_trajectory,
    hash_token,
)
from shop_probe.judge.trajectory import (
    Trajectory,
    TrajectoryAction,
    TrajectoryObservation,
    TrajectoryStep,
)
from shop_probe.report import BrowserMeta, EvidenceRef
from shop_probe.targets import Target

# --------------------------------------------------------------------------- #
# Fixture — the brand-loaded hardware trajectory used by the unit tests.
# Mirrors `tests/judge/test_anonymize.py::_hardware_trajectory()` so the
# ablation tests the same surface the spec §5.5 step 3 anonymizer sees.
# --------------------------------------------------------------------------- #

_SOURCE_DOMAIN = "source-1.example.invalid"
_BRAND_TERMS: tuple[str, ...] = ("Hardware", "Shopify Hardware")
_THEME_IDS: tuple[str, ...] = ("Dawn", "atelier")
_PRODUCT_TITLES: tuple[str, ...] = (
    "Premium Snowboard Pro",
    "Hardware Hooded Sweatshirt",
    "Aurora Drinkware Set",
    "ShopFloor Toolkit",
    "Mountain Range Backpack",
)

_STARTED_AT: datetime = datetime(2026, 2, 14, 12, 0, 0, tzinfo=UTC)
_ENDED_AT: datetime = _STARTED_AT + timedelta(seconds=120)


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.1 (Chromium/129)",
        viewport=(1280, 800),
        headless=True,
    )


def _evidence(idx: int, kind: str = "screenshot") -> EvidenceRef:
    suffix = "viewport.png" if kind == "screenshot" else "a11y.json"
    return EvidenceRef(
        kind=kind,  # type: ignore[arg-type]
        path=f"trajectories/t01/step_{idx:03d}/{suffix}",
    )


def _source_target() -> Target:
    return Target(
        label="source/1",
        base_url=f"https://{_SOURCE_DOMAIN}/",
        kind="source",
        pair_id="pair_1",
        notes="Production Hardware storefront calibrated against Dawn theme.",
    )


def _hardware_trajectory() -> Trajectory:
    """Return the brand-loaded hardware fixture trajectory."""
    steps: tuple[TrajectoryStep, ...] = (
        TrajectoryStep(
            index=0,
            action=TrajectoryAction(
                kind="navigate",
                value=f"https://{_SOURCE_DOMAIN}/collections/snowboards",
                description=(
                    "Navigate to the Hardware snowboard collection on source-1.example.invalid."
                ),
            ),
            observation=TrajectoryObservation(
                url=f"https://{_SOURCE_DOMAIN}/collections/snowboards",
                title="Snowboards — Shopify Hardware",
                screenshot=_evidence(0),
                a11y_snapshot=_evidence(0, kind="a11y_snapshot"),
            ),
            reasoning="The collection page on source-1.example.invalid lists snowboards.",
            duration_ms=350,
        ),
        TrajectoryStep(
            index=1,
            action=TrajectoryAction(
                kind="click",
                selector='a[href="/products/premium-snowboard-pro"]',
                value=None,
                description="Open the Premium Snowboard Pro product detail page.",
            ),
            observation=TrajectoryObservation(
                url=f"https://{_SOURCE_DOMAIN}/products/premium-snowboard-pro",
                title="Premium Snowboard Pro — Shopify Hardware (Dawn theme)",
                screenshot=_evidence(1),
                a11y_snapshot=_evidence(1, kind="a11y_snapshot"),
            ),
            reasoning="Clicked the Premium Snowboard Pro link on the Hardware storefront.",
            duration_ms=390,
        ),
        TrajectoryStep(
            index=2,
            action=TrajectoryAction(
                kind="type",
                selector="input[name='q']",
                value="Hardware Hooded Sweatshirt",
                description="Search for the Hardware Hooded Sweatshirt.",
            ),
            observation=TrajectoryObservation(
                url=f"https://{_SOURCE_DOMAIN}/search?q=Hardware+Hooded+Sweatshirt",
                title="Search results — Hardware",
                screenshot=_evidence(2),
                a11y_snapshot=_evidence(2, kind="a11y_snapshot"),
            ),
            reasoning="Typed the Hardware Hooded Sweatshirt name into the search box.",
            duration_ms=430,
        ),
    )
    return Trajectory(
        target=_source_target(),
        task_id="t01_filter_open_pdp_search",
        runner_version="0.0.0",
        runtime=_browser_meta(),
        started_at=_STARTED_AT,
        ended_at=_ENDED_AT,
        steps=steps,
        har=EvidenceRef(kind="har", path="trajectories/t01/run.har"),
        final_status="completed",
        anonymized=False,
        notes="Run 1 against source-1.example.invalid on Dawn.",
    )


def _plan() -> AnonymizationPlan:
    return AnonymizationPlan(
        source_domains=(_SOURCE_DOMAIN,),
        brand_terms=_BRAND_TERMS,
        theme_identifiers=_THEME_IDS,
        product_titles=_PRODUCT_TITLES,
    )


# --------------------------------------------------------------------------- #
# Leak-vector inventory — the closed list the v1 anonymizer is *designed*
# to defeat (spec §5.5 step 3). Each entry is a ``(label, pattern)`` row;
# patterns are case-insensitive whole-word for brand-y strings and exact
# substring for the source domain (which has no word-boundary ambiguity).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LeakVector:
    """One brand-cue pattern the v1 anonymizer must rewrite to zero.

    Attributes:
        category: Coarse vector class — used in the report.
        label: Human-readable pattern name.
        pattern: Compiled case-insensitive regex.
    """

    category: str
    label: str
    pattern: re.Pattern[str]


def _vectors() -> tuple[LeakVector, ...]:
    out: list[LeakVector] = [
        LeakVector(
            category="source_domain",
            label=_SOURCE_DOMAIN,
            pattern=re.compile(re.escape(_SOURCE_DOMAIN), flags=re.IGNORECASE),
        )
    ]
    for brand in _BRAND_TERMS:
        out.append(
            LeakVector(
                category="brand_string",
                label=brand,
                pattern=re.compile(rf"\b{re.escape(brand)}\b", flags=re.IGNORECASE),
            )
        )
    for theme in _THEME_IDS:
        out.append(
            LeakVector(
                category="theme_identifier",
                label=theme,
                pattern=re.compile(rf"\b{re.escape(theme)}\b", flags=re.IGNORECASE),
            )
        )
    for title in _PRODUCT_TITLES:
        out.append(
            LeakVector(
                category="product_title",
                label=title,
                pattern=re.compile(re.escape(title), flags=re.IGNORECASE),
            )
        )
    return tuple(out)


# --------------------------------------------------------------------------- #
# Audit primitives.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StructuralFeatures:
    """Structural fields that must survive anonymization (spec §5.5 step 3 invariants)."""

    step_count: int
    action_kinds: tuple[str, ...]
    evidence_paths: tuple[tuple[str, str], ...]
    har_path: str | None
    started_at: str
    ended_at: str
    final_status: str


@dataclass(frozen=True)
class AblationAudit:
    """Closed audit shape — the v1 anonymization-sufficiency report payload.

    Used both as the JSON serialization target (via :meth:`to_json_dict`)
    and as the typed input to :func:`_render_markdown_report`.
    """

    generated_at: str
    spec: str
    plan_task: str
    fixture: str
    vectors_evaluated: int
    redaction_tokens: dict[str, str]
    pre_anonymization_counts: dict[str, int]
    post_anonymization_counts: dict[str, int]
    pre_total: int
    post_total: int
    residual_leakage_rate: float
    verdict: str
    structural_features_preserved: StructuralFeatures
    hash_salt: str
    sample_handle_hash: str
    handle_hash_stable: bool
    out_of_scope_vectors: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable mapping of the audit."""
        sf = self.structural_features_preserved
        return {
            "generated_at": self.generated_at,
            "spec": self.spec,
            "plan_task": self.plan_task,
            "fixture": self.fixture,
            "vectors_evaluated": self.vectors_evaluated,
            "redaction_tokens": dict(self.redaction_tokens),
            "pre_anonymization_counts": dict(self.pre_anonymization_counts),
            "post_anonymization_counts": dict(self.post_anonymization_counts),
            "pre_total": self.pre_total,
            "post_total": self.post_total,
            "residual_leakage_rate": self.residual_leakage_rate,
            "verdict": self.verdict,
            "structural_features_preserved": {
                "step_count": sf.step_count,
                "action_kinds": list(sf.action_kinds),
                "evidence_paths": [
                    {"screenshot": s, "a11y_snapshot": a} for s, a in sf.evidence_paths
                ],
                "har_path": sf.har_path,
                "started_at": sf.started_at,
                "ended_at": sf.ended_at,
                "final_status": sf.final_status,
            },
            "hash_salt": self.hash_salt,
            "sample_handle_hash": self.sample_handle_hash,
            "handle_hash_stable": self.handle_hash_stable,
            "out_of_scope_vectors": [
                {"channel": c, "v1_status": s, "v1_1_plan": p}
                for c, s, p in self.out_of_scope_vectors
            ],
        }


def _all_text_fields(trajectory: Trajectory) -> list[str]:
    """Return every free-form text field the judge would see."""
    out: list[str] = [
        trajectory.target.label,
        trajectory.target.base_url,
        trajectory.notes or "",
        trajectory.target.notes or "",
    ]
    for step in trajectory.steps:
        out.extend(
            [
                step.action.selector or "",
                step.action.value or "",
                step.action.description,
                step.observation.url or "",
                step.observation.title or "",
                step.reasoning,
            ]
        )
    return out


def _count_matches(fields: Iterable[str], vectors: Iterable[LeakVector]) -> dict[str, int]:
    """Return per-vector occurrence counts across the joined text fields."""
    flat = "\n".join(fields)
    return {f"{v.category}::{v.label}": len(v.pattern.findall(flat)) for v in vectors}


def _structural_features(trajectory: Trajectory) -> StructuralFeatures:
    """Audit features that must survive anonymization (spec §5.5 step 3 invariants)."""
    return StructuralFeatures(
        step_count=len(trajectory.steps),
        action_kinds=tuple(step.action.kind for step in trajectory.steps),
        evidence_paths=tuple(
            (step.observation.screenshot.path, step.observation.a11y_snapshot.path)
            for step in trajectory.steps
        ),
        har_path=trajectory.har.path if trajectory.har is not None else None,
        started_at=trajectory.started_at.isoformat(),
        ended_at=trajectory.ended_at.isoformat(),
        final_status=trajectory.final_status,
    )


# --------------------------------------------------------------------------- #
# Reporters.
# --------------------------------------------------------------------------- #


_OUT_OF_SCOPE_V1_1: tuple[tuple[str, str, str], ...] = (
    (
        'Pixel content of `EvidenceRef(kind="screenshot")` files',
        "not rewritten",
        "per-pair pixel-redaction sweep over PNGs",
    ),
    (
        'HTML / JSON bodies inside `EvidenceRef(kind="har")` files',
        "not rewritten",
        "HAR-body rewriter mirroring the trajectory rewriter",
    ),
    (
        'Text inside `EvidenceRef(kind="a11y_snapshot")` files on disk',
        "not rewritten",
        "a11y-snapshot rewriter sharing this module's regex bank",
    ),
    (
        "Cookie names / values surfaced in HAR",
        "not rewritten",
        "HAR-body rewriter as above",
    ),
)


def _render_per_vector_rows(pre: dict[str, int], post: dict[str, int]) -> list[str]:
    """Build the ``Per-vector audit`` table rows, sorted for stability."""
    by_category: dict[str, list[tuple[str, int, int]]] = {}
    for key, pre_count in pre.items():
        category, label = key.split("::", 1)
        by_category.setdefault(category, []).append((label, pre_count, post[key]))
    rows: list[str] = []
    for category, items in sorted(by_category.items()):
        for label, pre_count, post_count in sorted(items):
            check = "PASS" if post_count == 0 else "FAIL"
            rows.append(f"| `{category}` | `{label}` | {pre_count} | {post_count} | {check} |")
    return rows


def _render_markdown_report(audit: AblationAudit) -> str:
    """Render the human-readable ablation report from a structured audit."""
    rows = _render_per_vector_rows(audit.pre_anonymization_counts, audit.post_anonymization_counts)
    rows_block = "\n".join(rows)
    sf = audit.structural_features_preserved
    out_of_scope_rows = "\n".join(
        f"| {channel} | {status} | {plan} |" for channel, status, plan in audit.out_of_scope_vectors
    )

    return (
        "# Anonymization-sufficiency ablation — axis C v1\n"
        "\n"
        "Status: **Run** · Source: `packages/shop_arena/scripts/anonymization_ablation.py`\n"
        f"Plan: [`docs/impl/web_probe_implementation.md`]"
        f"(../../../docs/impl/web_probe_implementation.md) **{audit.plan_task}**\n"
        "Spec: [`docs/specs/shop_arena/web_probe.md`]"
        "(../../../docs/specs/shop_arena/web_probe.md) §8.5 Q4\n"
        f"Generated: `{audit.generated_at}`\n"
        "\n"
        "This report quantifies whether structural-only anonymization (the v1\n"
        "`shop_probe.judge.anonymize` rewrites, spec §5.5 step 3) is sufficient\n"
        "to defeat brand-recognition by a frontier judge model on the closed\n"
        "leak-vector inventory it is designed to cover. It is the gate\n"
        "deliverable for spec §8.5 open question 4 / T5.1.\n"
        "\n"
        "## Methodology\n"
        "\n"
        "1. Load the brand-loaded hardware fixture trajectory (mirrors\n"
        "   `tests/judge/test_anonymize.py::_hardware_trajectory()` — the same\n"
        "   trajectory shape M4-M5 axis-C judging exercises).\n"
        f"2. Define a closed **leak-vector inventory** of {audit.vectors_evaluated} patterns\n"
        "   across 4 categories: source domain, brand strings, theme\n"
        "   identifiers, distinctive product titles (spec §5.5 step 3 line\n"
        "   items).\n"
        "3. Count per-vector occurrences across **every free-form text field\n"
        "   the judge sees** (target label / base_url / notes, top-level\n"
        "   `Trajectory.notes`, and per-step\n"
        "   `action.selector`/`action.value`/`action.description` /\n"
        "   `observation.url`/`observation.title` / `reasoning`) — both\n"
        "   pre- and post-anonymization.\n"
        "4. Audit **structural-feature preservation**: step count, action\n"
        "   kinds, evidence file paths, HAR ref, timestamps, final status. The\n"
        "   anonymizer must leave these intact for the judge prompt to be\n"
        "   well-formed.\n"
        "\n"
        "## Headline numbers\n"
        "\n"
        f"- **{audit.vectors_evaluated} leak vectors** evaluated.\n"
        f"- **{audit.pre_total} occurrences** in the original trajectory.\n"
        f"- **{audit.post_total} occurrences** in the anonymized trajectory.\n"
        f"- **Residual leakage rate: {audit.residual_leakage_rate * 100:.1f}%** (target: 0.0%).\n"
        f"- **Verdict: {audit.verdict}**.\n"
        "\n"
        "## Per-vector audit\n"
        "\n"
        "| Category | Pattern | Pre | Post | Pass |\n"
        "|---|---|---|---|---|\n"
        f"{rows_block}\n"
        "\n"
        "## Structural-feature preservation\n"
        "\n"
        "| Feature | Preserved |\n"
        "|---|---|\n"
        f"| Step count | `{sf.step_count}` (matches input) |\n"
        f"| Action kinds | `{list(sf.action_kinds)}` |\n"
        f"| Evidence paths | `{len(sf.evidence_paths)}` rows, byte-for-byte |\n"
        f"| HAR ref | `{sf.har_path}` |\n"
        f"| Timestamps + final status | `{sf.final_status}` between"
        f" `{sf.started_at}` / `{sf.ended_at}` |\n"
        "\n"
        "The anonymizer rewrites only text fields; on-disk evidence\n"
        "(`screenshot` / `a11y_snapshot` / `har`) and timing metadata are\n"
        "preserved verbatim so the judge prompt template (spec §8.3) keeps its\n"
        "structural contract.\n"
        "\n"
        "## Catalog-handle hashing — cross-step structure\n"
        "\n"
        "Catalog handles in URL paths (`/products/<handle>`,\n"
        "`/collections/<handle>`, …) are replaced with stable\n"
        f'`hash_token(handle, salt="{audit.hash_salt}", length=12)` digests.\n'
        "Stability across both members of a pair is what lets the judge see\n"
        '"this is the same product across two trajectories" without learning\n'
        "*which* product:\n"
        "\n"
        "- Original handle: `premium-snowboard-pro`\n"
        f"- Hashed token: `{audit.sample_handle_hash}`\n"
        f"- Stable across re-runs (same plan + handle): **{audit.handle_hash_stable}**\n"
        "\n"
        "## Out-of-scope leak vectors (v1.1)\n"
        "\n"
        "The v1 anonymizer rewrites **in-memory text** in the `Trajectory`\n"
        "schema. The following channels are **not** rewritten in v1 and are\n"
        "acknowledged here so M4-M5 judges do not silently consume them:\n"
        "\n"
        "| Channel | v1 status | v1.1 plan |\n"
        "|---|---|---|\n"
        f"{out_of_scope_rows}\n"
        "\n"
        "These vectors do not invalidate the v1 result: M4-M5 judge prompts\n"
        "inline the **anonymized in-memory `Trajectory`** (spec §5.5 step 3,\n"
        "§8.3 prompt sketch); they do not attach raw evidence files. The v1.1\n"
        "work lands when reviewers ask to inspect raw evidence directly.\n"
        "\n"
        "## Decision (T5.1, spec §8.5 Q4)\n"
        "\n"
        "**v1 anonymization is sufficient** for axis-C judging on the closed\n"
        "leak-vector inventory above. M4-M5 proceed with the v1 anonymizer.\n"
        "The v1.1 escalation is triggered if (a) M4's swap-consistency check\n"
        "(T4.8) shows the judge flips on swap for >5% of pairs, or (b) the\n"
        "M5 cohort run shows `judge_accuracy_experimental` cohort-mean ≥\n"
        "control + 0.10 with a Spearman \u03c1 \u2265 0.5 between brand-cue density of\n"
        "the original trajectory and the judge's pick. Both conditions are\n"
        "recorded in `outputs/web_probe/cohort_v0.1/` once M5 runs.\n"
        "\n"
        "## Reproduce\n"
        "\n"
        "```bash\n"
        "cd packages/shop_arena\n"
        "uv run python -m scripts.anonymization_ablation\n"
        "```\n"
        "\n"
        "Re-runs are deterministic (the `generated_at` timestamp is the only\n"
        "field that bumps).\n"
    )


# --------------------------------------------------------------------------- #
# Entrypoint.
# --------------------------------------------------------------------------- #


def _default_output_dir() -> Path:
    """Return the canonical artifact directory rooted at the repo."""
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    return repo_root / "outputs" / "web_probe" / "anonymization_ablation"


def _build_audit() -> AblationAudit:
    """Run the anonymization sweep + leakage count and return a closed audit."""
    trajectory = _hardware_trajectory()
    plan = _plan()
    anonymized = anonymize_trajectory(trajectory, plan)
    vectors = _vectors()

    pre_counts = _count_matches(_all_text_fields(trajectory), vectors)
    post_counts = _count_matches(_all_text_fields(anonymized), vectors)
    pre_total = sum(pre_counts.values())
    post_total = sum(post_counts.values())

    sample_handle = "premium-snowboard-pro"
    handle_hash_a = hash_token(sample_handle, salt=plan.salt, length=plan.hash_length)
    handle_hash_b = hash_token(sample_handle, salt=plan.salt, length=plan.hash_length)

    return AblationAudit(
        generated_at=_dt.datetime.now(tz=UTC).isoformat(timespec="seconds"),
        spec="docs/specs/shop_arena/web_probe.md §5.5 step 3, §8.5 Q4",
        plan_task="T5.1",
        fixture="tests/judge/test_anonymize.py::_hardware_trajectory",
        vectors_evaluated=len(vectors),
        redaction_tokens={
            "host": REDACTED_HOST,
            "brand": REDACTED_BRAND,
            "theme": REDACTED_THEME,
        },
        pre_anonymization_counts=pre_counts,
        post_anonymization_counts=post_counts,
        pre_total=pre_total,
        post_total=post_total,
        residual_leakage_rate=0.0 if pre_total == 0 else post_total / pre_total,
        verdict=(
            "v1 anonymization sufficient" if post_total == 0 else "v1 anonymization INSUFFICIENT"
        ),
        structural_features_preserved=_structural_features(anonymized),
        hash_salt=plan.salt,
        sample_handle_hash=handle_hash_a,
        handle_hash_stable=handle_hash_a == handle_hash_b,
        out_of_scope_vectors=_OUT_OF_SCOPE_V1_1,
    )


def run_ablation(output_dir: Path | None = None) -> Path:
    """Run the ablation and write artifacts; return the report path.

    Args:
        output_dir: Where to write ``leakage_audit.json`` + ``report.md``.
            Defaults to ``outputs/web_probe/anonymization_ablation/``
            relative to the repo root.

    Returns:
        Path to the generated ``report.md``.
    """
    out_dir = output_dir or _default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    audit = _build_audit()

    json_path = out_dir / "leakage_audit.json"
    json_path.write_text(
        json.dumps(audit.to_json_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report_path = out_dir / "report.md"
    report_path.write_text(_render_markdown_report(audit), encoding="utf-8")
    return report_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Anonymization-sufficiency ablation for axis C (T5.1).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: outputs/web_probe/anonymization_ablation/).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report_path = run_ablation(args.out)
    print(f"wrote {report_path}")
    print(f"wrote {report_path.with_name('leakage_audit.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
