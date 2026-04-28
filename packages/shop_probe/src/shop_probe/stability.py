"""N=3 rerun aggregation for axis-A stability (T5.2 — spec §5.8 / §7 M5).

Spec §5.8 mandates N=3 reruns per target so flake is measured at the
suite level (the per-probe runner already pins ``retries=0``). The
aggregation step here turns N independent :class:`ProbeReport`
documents for the *same* target into one canonical report whose
``flake_rate_per_probe`` field is populated from the rerun group, plus
a paper-claim gate ``flake_rate < 1%`` (spec §5.8) that the M5 cohort
run must satisfy.

Definitions used here:

* **Rerun group** — N reports keyed by the same :attr:`Target.label`,
  rubric ``(version, content_hash)``, and runner version. Mismatched
  groups are rejected up front rather than producing a misleading
  flake-rate aggregate (spec §5.8).
* **Per-probe flake rate** — fraction of runs in the rerun group whose
  ``passed`` value differs from the modal value across the group.
  ``passed=None`` ("not_applicable") is treated as a distinct outcome
  alongside ``True`` and ``False`` so a probe that flips between
  applicable and not-applicable still flakes (spec §5.8). Per-probe
  flake therefore lives in ``[0, (N-1)/N]`` for a clean rerun group
  and is exactly ``0`` when every run agrees.
* **Cohort flake rate** — fraction of probes in the rerun group whose
  per-probe flake rate is non-zero. Spec §5.8 gates paper claims on
  ``flake_rate < 1%``; the M5 acceptance check at
  ``docs/impl/web_probe_implementation.md`` reads ``flake_rate < 1%``
  per :class:`ProbeReport`.

The module performs no I/O at import time.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from shop_probe.report import ProbeReport, ProbeResult

__all__ = [
    "FLAKE_RATE_GATE",
    "RerunGroupError",
    "aggregate_flake_rates",
    "consolidate_rerun_group",
    "exceeds_flake_gate",
]

FLAKE_RATE_GATE: float = 0.01
"""Spec §5.8 paper-claim gate on per-probe flake rate (``< 1%``).

Used by :func:`exceeds_flake_gate` so the CLI and the M5 acceptance
script consult the same constant.
"""


class RerunGroupError(ValueError):
    """Raised when a tuple of reports does not form a coherent rerun group.

    A coherent rerun group has identical
    ``(target.label, rubric_version, rubric_hash, runner_version)``
    across every report and is non-empty. The rationale is spec §5.8:
    the flake-rate aggregate is only meaningful across reruns of the
    *same* target under the *same* harness pin.
    """


def aggregate_flake_rates(reports: Sequence[ProbeReport]) -> dict[str, float]:
    """Return the per-probe flake rate over a rerun group.

    The flake rate for one probe is defined as the fraction of runs
    whose ``passed`` value differs from the modal value across the
    group. ``passed=None`` ("not_applicable") is treated as a distinct
    third value so a probe that flips between applicable and
    not-applicable still flakes (spec §5.8). Probes that appear in only
    a subset of the runs flake on the missing runs.

    Args:
        reports: Two or more :class:`ProbeReport` rows from runs of the
            same target. Order is irrelevant — the flake rate depends
            only on the multiset of outcomes.

    Returns:
        Mapping from rubric ``probe_id`` to flake rate in ``[0, 1]``.
        The keys are the union of probe ids observed across the group,
        sorted alphabetically so the dict iteration order is stable.

    Raises:
        RerunGroupError: ``reports`` is empty or contains reports with
            mismatched ``(target.label, rubric_version, rubric_hash,
            runner_version)``.
    """
    materialized = tuple(reports)
    _check_rerun_group(materialized)
    probe_ids: set[str] = set()
    for report in materialized:
        probe_ids.update(result.id for result in report.probe_results)
    out: dict[str, float] = {}
    for probe_id in sorted(probe_ids):
        outcomes = _collect_outcomes(materialized, probe_id)
        out[probe_id] = _flake_rate_for(outcomes)
    return out


def consolidate_rerun_group(reports: Sequence[ProbeReport]) -> ProbeReport:
    """Stamp ``flake_rate_per_probe`` onto the canonical report.

    Picks the report with the smallest :attr:`ProbeReport.rerun_index`
    as the canonical row, ties broken by :attr:`ProbeReport.timestamp`
    so the choice is deterministic across machines, and returns a copy
    with :attr:`ProbeReport.flake_rate_per_probe` populated from the
    full group.

    Args:
        reports: Two or more :class:`ProbeReport` rows from runs of the
            same target.

    Returns:
        A new :class:`ProbeReport` (the model is frozen so a copy is
        produced via ``model_copy``) representing the canonical run
        with the rerun-group flake rate stamped in.

    Raises:
        RerunGroupError: ``reports`` is not a coherent rerun group
            (see :class:`RerunGroupError`).
    """
    materialized = tuple(reports)
    _check_rerun_group(materialized)
    canonical = min(materialized, key=lambda r: (r.rerun_index, r.timestamp))
    flake = aggregate_flake_rates(materialized)
    return canonical.model_copy(update={"flake_rate_per_probe": flake})


def exceeds_flake_gate(
    flake_rate_per_probe: dict[str, float],
    *,
    gate: float = FLAKE_RATE_GATE,
) -> tuple[str, ...]:
    """Return probe ids whose flake rate is ``>= gate``.

    The spec §5.8 / impl T5.2 gate is ``flake_rate < 1%`` per probe, so
    the default ``gate`` is :data:`FLAKE_RATE_GATE`. With ``N=3`` reruns
    the per-probe flake rate is one of ``{0, 1/3, 2/3}`` (ignoring the
    pad case), so any non-zero entry exceeds the gate — that is the
    intended behaviour for the M5 acceptance check.

    Args:
        flake_rate_per_probe: Output of :func:`aggregate_flake_rates`.
        gate: Inclusive lower bound on what counts as a flake gate
            violation. Defaults to :data:`FLAKE_RATE_GATE` (1%).

    Returns:
        Sorted tuple of probe ids whose flake rate meets or exceeds
        ``gate``. Empty when the rerun group passes the gate.
    """
    return tuple(
        probe_id for probe_id, rate in sorted(flake_rate_per_probe.items()) if rate >= gate
    )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


_MISSING: object = object()
"""Sentinel for a probe that did not appear in one of the reruns."""


def _check_rerun_group(reports: tuple[ProbeReport, ...]) -> None:
    """Reject empty or mismatched rerun groups."""
    if not reports:
        msg = "rerun group must contain at least one report"
        raise RerunGroupError(msg)
    head = reports[0]
    expected = (
        head.target.label,
        head.rubric_version,
        head.rubric_hash,
        head.runner_version,
    )
    for report in reports[1:]:
        actual = (
            report.target.label,
            report.rubric_version,
            report.rubric_hash,
            report.runner_version,
        )
        if actual != expected:
            msg = (
                "rerun group mismatch: expected "
                f"(label={expected[0]!r}, rubric={expected[1]!r}, "
                f"rubric_hash={expected[2]!r}, runner={expected[3]!r}); "
                f"got (label={actual[0]!r}, rubric={actual[1]!r}, "
                f"rubric_hash={actual[2]!r}, runner={actual[3]!r})"
            )
            raise RerunGroupError(msg)


def _collect_outcomes(
    reports: tuple[ProbeReport, ...], probe_id: str
) -> tuple[bool | None | object, ...]:
    """Return one outcome slot per report for ``probe_id``.

    Slots default to :data:`_MISSING` when a report omitted the probe so
    the flake-rate denominator stays equal to ``len(reports)`` and
    drift across reruns surfaces in the aggregate.
    """
    outcomes: list[bool | None | object] = []
    for report in reports:
        match = _find_result(report.probe_results, probe_id)
        outcomes.append(_MISSING if match is None else match.passed)
    return tuple(outcomes)


def _find_result(results: tuple[ProbeResult, ...], probe_id: str) -> ProbeResult | None:
    """Look up the :class:`ProbeResult` for ``probe_id`` in ``results``."""
    for result in results:
        if result.id == probe_id:
            return result
    return None


def _flake_rate_for(
    outcomes: tuple[bool | None | object, ...],
) -> float:
    """Compute the flake rate for one probe's per-run outcomes."""
    if not outcomes:
        return 0.0
    counts: Counter[object] = Counter(outcomes)
    # Flake = fraction of runs that disagree with the modal outcome.
    # Tie-breaking on which outcome is the "modal" one does not change
    # the rate, so the numeric output is invariant to input ordering.
    modal_count = max(counts.values())
    return 1.0 - modal_count / len(outcomes)
