"""``no_brand_leak`` build-loop verifier (spec §5.5.3 + §5.6).

Walks every TypeScript source, CSS file, and Markdown doc under
``ctx.artifact_dir / "hydrogen" / "app"`` and runs the canonical
fake-brand allowlist scanner from
:mod:`shop_gen.brands.allowlist` over the contents. Any non-allowlisted
brand-shaped token triggers a ``FAIL`` verdict; the feedback markdown
embeds the eight-element allowlist verbatim so the next iteration's
agent has the full vocabulary in context.

Applicability mirrors the spec table: every ``gen_*`` task. The
``consolidate`` task is excluded — §5.5.4 lists its gating verifier set
explicitly and ``no_brand_leak`` is not on it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from harness.verifiers import Verdict, VerifierContext, VerifierResult
from shop_gen.brands.allowlist import Allowlist, Hit, load_allowlist, scan

_NAME: Final[str] = "no_brand_leak"
"""Verifier name (filesystem-safe; matches the spec table)."""

_HYDROGEN_APP_DIR: Final[str] = "hydrogen/app"
"""Path of the hydrogen ``app/`` tree relative to ``VerifierContext.artifact_dir``."""

_SCAN_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".tsx", ".ts", ".css", ".md"},
)
"""Source-file extensions covered by the scan (spec §5.5.3 verbatim)."""

_MAX_HITS_IN_FEEDBACK: Final[int] = 50
"""Cap on hits embedded in the feedback markdown.

Without a cap a runaway leak (e.g. an entire seed-storefront paste)
would emit thousands of lines and overflow the 4000-char feedback
budget enforced by the harness. Fifty hits is enough to give the next
iteration a representative sample without truncating the body.
"""


@dataclass(frozen=True, slots=True)
class _BrandLeak:
    """One non-allowlisted token surfaced by :func:`_scan_tree`.

    Attributes:
        path: Run-relative path of the source file containing the leak.
        token: Raw brand-shaped token, with case preserved.
        line: 1-indexed line number of the offending token.
    """

    path: Path
    token: str
    line: int


class NoBrandLeakVerifier:
    """Runs the §5.6 allowlist scanner over the hydrogen ``app/`` tree.

    Attributes:
        name: ``"no_brand_leak"`` — used as the per-verifier telemetry
            filename and the markdown section heading in
            ``feedback.md``.
    """

    name: str = _NAME

    def __init__(self, *, allowlist: Allowlist | None = None) -> None:
        """Build the verifier with an optional pre-loaded allowlist.

        Args:
            allowlist: Pre-loaded :class:`~shop_gen.brands.allowlist.Allowlist`.
                Defaults to the in-repo ``fake_brands.json`` (loaded
                lazily on first call to :meth:`run`).
        """
        self._allowlist = allowlist

    def applies_to(self, task_id: str) -> bool:
        """Match every ``gen_*`` task (spec §5.5.3).

        Args:
            task_id: Selected task id.

        Returns:
            ``True`` when the verifier should run for ``task_id``.
        """
        return task_id.startswith("gen_")

    def run(self, ctx: VerifierContext) -> VerifierResult:
        """Scan every covered file in the hydrogen ``app/`` tree.

        Args:
            ctx: Verifier context. Reads ``ctx.artifact_dir`` to locate
                the hydrogen ``app/`` tree; ``ctx.runtime`` is unused.

        Returns:
            ``PASS`` when no covered file contains a non-allowlisted
            brand-shaped token. ``FAIL`` with a feedback body listing
            the first :data:`_MAX_HITS_IN_FEEDBACK` leaks plus the
            allowlist itself otherwise.

            A missing hydrogen tree returns ``FAIL`` with an
            explanatory feedback string — the verifier does not crash
            on workspace bugs, so the loop can recover by re-running
            ``clone_template``.
        """
        allowlist = self._allowlist if self._allowlist is not None else load_allowlist()
        app_dir = ctx.artifact_dir / _HYDROGEN_APP_DIR
        if not app_dir.is_dir():
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    "no_brand_leak could not find the hydrogen app tree "
                    f"at `{_HYDROGEN_APP_DIR}/`. Did `clone_template` run?"
                ),
                details={"app_dir": str(app_dir), "exists": False},
            )

        leaks = list(_scan_tree(app_dir, allowlist=allowlist))
        if not leaks:
            return VerifierResult(
                verdict=Verdict.PASS,
                details={
                    "files_scanned": _count_files(app_dir),
                    "leaks": 0,
                },
            )
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback=_render_failure_markdown(leaks, allowlist=allowlist),
            details={
                "leaks": len(leaks),
                "first_path": str(leaks[0].path),
                "first_token": leaks[0].token,
            },
        )


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _scan_tree(app_dir: Path, *, allowlist: Allowlist) -> Iterable[_BrandLeak]:
    """Yield one :class:`_BrandLeak` per non-allowlisted token under ``app_dir``."""
    for path in sorted(app_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in _SCAN_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # A binary-content false-positive (e.g. a generated
            # ``.d.ts`` lookalike) is silently skipped. The post-pass
            # scanner already runs on `data/*.json`; this verifier's
            # scope is the agent-authored hydrogen tree.
            continue
        for hit in _scan_text_with_lines(text, allowlist=allowlist):
            yield _BrandLeak(
                path=path.relative_to(app_dir.parent.parent),
                token=hit.token,
                line=_line_number(text, hit),
            )


def _scan_text_with_lines(text: str, *, allowlist: Allowlist) -> list[Hit]:
    """Run :func:`scan` and return raw hits in match order."""
    return scan(text, allowlist=allowlist)


def _line_number(text: str, hit: Hit) -> int:
    """Return the 1-indexed line containing ``hit`` in ``text``.

    Counts the number of newline characters before ``hit.start``; the
    loop's worst case is one full pass over the source file per leak.
    """
    return text.count("\n", 0, hit.start) + 1


def _count_files(app_dir: Path) -> int:
    """Return the number of files matching :data:`_SCAN_SUFFIXES` under ``app_dir``."""
    count = 0
    for path in app_dir.rglob("*"):
        if path.is_file() and path.suffix in _SCAN_SUFFIXES:
            count += 1
    return count


def _render_failure_markdown(
    leaks: list[_BrandLeak],
    *,
    allowlist: Allowlist,
) -> str:
    """Render the failure feedback body.

    The body lists the first :data:`_MAX_HITS_IN_FEEDBACK` leaks and
    embeds the eight-element allowlist verbatim so the next iteration
    has the full vocabulary in scope (spec §5.6).

    Args:
        leaks: All leaks discovered by :func:`_scan_tree`, in scan
            order.
        allowlist: Pre-loaded allowlist used to render the embedded
            "allowed brands" line.

    Returns:
        Markdown body suitable for the next iteration's prompt.
    """
    lines = [
        f"`no_brand_leak` found {len(leaks)} non-allowlisted brand-shaped token(s) "
        "in the hydrogen tree.",
        "",
        "Use only the eight allowlisted fake brands; remove any other brand-shaped "
        "proper noun (or rephrase it as a plain description).",
        "",
        f"Allowed brands: {', '.join(sorted(allowlist.brands))}.",
        "",
        "Leaks:",
    ]
    visible = leaks[:_MAX_HITS_IN_FEEDBACK]
    for leak in visible:
        lines.append(f"- `{leak.path}:{leak.line}` — `{leak.token}`")
    if len(leaks) > _MAX_HITS_IN_FEEDBACK:
        remaining = len(leaks) - _MAX_HITS_IN_FEEDBACK
        lines.append(f"- ...and {remaining} more leak(s) elided.")
    return "\n".join(lines)


__all__ = ["NoBrandLeakVerifier"]
