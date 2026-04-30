"""``quality_judge`` build-loop verifier (spec §5.5.3, impl plan T5.5).

Asks the configured runtime's :class:`~harness.runtimes.LLMCompleter`
to judge whether the hydrogen source under review surfaces the
capabilities listed in the merged ``capabilities.json`` for this shop.
The judge is **quality-only** — it does not cross-compare against any
seed storefront (spec §5.5.5 + alt-#5).

Applicability mirrors the spec table: post ``gen_homepage``,
``gen_product``, ``gen_cart_search``, and the mandatory ``visual_fix``
task (spec §5.5.4).

The verifier reads:

* ``ctx.artifact_dir / "capabilities.json"`` — the merged capabilities
  document copied into the run via ``PlanExecLoopConfig.artifact_seed_dir``
  (T5.6).
* ``ctx.artifact_dir / "hydrogen" / "app" / **`` — the source files
  the executor edits.

A missing capabilities document or a missing hydrogen tree is reported
as ``FAIL`` so the loop can recover by re-running the upstream step.
LLM transport failures (timeout, malformed response) also surface as
``FAIL`` with explanatory feedback rather than crashing the harness.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Final

from harness.verifiers import Verdict, VerifierContext, VerifierResult
from shop_gen.build.prompts import load_quality_judge_prompt
from shop_gen.build.verifiers._judge import (
    JudgeOutput,
    dispatch_judge,
    render_source_blocks,
    require_completer,
)

_NAME: Final[str] = "quality_judge"
"""Verifier name (filesystem-safe; matches the spec table)."""

_HYDROGEN_APP_DIR: Final[str] = "hydrogen/app"
"""Path of the hydrogen ``app/`` tree relative to ``VerifierContext.artifact_dir``."""

_CAPABILITIES_FILE: Final[str] = "capabilities.json"
"""Path of the merged capabilities document relative to ``VerifierContext.artifact_dir``."""

_DEFAULT_TIMEOUT_S: Final[float] = 180.0
"""Wall-clock budget for the LLM judge call.

Conservative: hydrogen source reviews can run a few thousand tokens
each direction; 3 minutes leaves headroom for cold-start latency on
the configured runtime.
"""

_DEFAULT_MAX_BYTES_PER_FILE: Final[int] = 8_000
"""Per-file source-byte cap (truncation defended in the body).

Each hydrogen source file beyond this cap is sliced down with an
``... <N> bytes elided ...`` tail so a single large file cannot blow
the LLM's context budget. The default is generous enough for typical
``routes/*.tsx`` files while still bounding worst-case input.
"""

_DEFAULT_MAX_TOTAL_BYTES: Final[int] = 80_000
"""Aggregate source-byte cap across all reviewed files.

Files past this cap are dropped (with a trailing ``files elided`` note)
rather than truncated mid-body, so the prompt stays readable.
"""

_DEFAULT_TASKS: Final[frozenset[str]] = frozenset(
    {
        "gen_homepage",
        "gen_product",
        "gen_cart_search",
        "visual_fix",
    },
)
"""Tasks this verifier applies to per spec §5.5.3 + §5.5.4."""


class QualityJudgeVerifier:
    """Asks the runtime's LLM completer to judge the executor's quality.

    Attributes:
        name: ``"quality_judge"`` — used as the per-verifier telemetry
            filename and the markdown section heading in
            ``feedback.md``.
    """

    name: str = _NAME

    def __init__(
        self,
        *,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_bytes_per_file: int = _DEFAULT_MAX_BYTES_PER_FILE,
        max_total_bytes: int = _DEFAULT_MAX_TOTAL_BYTES,
        applicable_tasks: Iterable[str] | None = None,
    ) -> None:
        """Build the verifier with optional injection seams.

        Args:
            timeout_s: Wall-clock budget for the LLM judge call.
                Defaults to :data:`_DEFAULT_TIMEOUT_S`.
            max_bytes_per_file: Per-file source-byte cap; longer files
                are truncated with an elision marker. Defaults to
                :data:`_DEFAULT_MAX_BYTES_PER_FILE`.
            max_total_bytes: Aggregate source-byte cap; files past the
                cap are dropped. Defaults to
                :data:`_DEFAULT_MAX_TOTAL_BYTES`.
            applicable_tasks: Override the default applicability set.
                Defaults to :data:`_DEFAULT_TASKS`. Pass an explicit
                empty set to disable the verifier (rarely useful;
                callers usually drop it from
                ``PlanExecLoopConfig.verifiers`` instead).
        """
        self._timeout_s = timeout_s
        self._max_bytes_per_file = max_bytes_per_file
        self._max_total_bytes = max_total_bytes
        self._applicable_tasks: frozenset[str] = (
            _DEFAULT_TASKS if applicable_tasks is None else frozenset(applicable_tasks)
        )

    def applies_to(self, task_id: str) -> bool:
        """Match the spec §5.5.3 task list (plus ``visual_fix`` per §5.5.4).

        Args:
            task_id: Selected task id (the executor's ``selected_task_id``).

        Returns:
            ``True`` when the verifier should run for ``task_id``.
        """
        return task_id in self._applicable_tasks

    def run(self, ctx: VerifierContext) -> VerifierResult:
        """Render the judge prompt, call the LLM, and translate its verdict.

        Args:
            ctx: Verifier context. Reads ``ctx.artifact_dir`` to locate
                the hydrogen tree + ``capabilities.json``; uses
                ``ctx.runtime`` (narrowed to ``LLMCompleter``) for the
                judge call.

        Returns:
            ``PASS`` when the LLM emits ``{"verdict": "pass", ...}``;
            ``FAIL`` with the LLM's feedback otherwise. Workspace
            problems (missing capabilities / hydrogen tree) and LLM
            transport errors (timeout, malformed response) also surface
            as ``FAIL`` with explanatory feedback.
        """
        capabilities_path = ctx.artifact_dir / _CAPABILITIES_FILE
        if not capabilities_path.is_file():
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"`quality_judge` could not read `{_CAPABILITIES_FILE}` from the "
                    "run's artifact directory; the build loop is expected to seed it via "
                    "`PlanExecLoopConfig.artifact_seed_dir`."
                ),
                details={"capabilities_path": str(capabilities_path), "exists": False},
            )

        app_dir = ctx.artifact_dir / _HYDROGEN_APP_DIR
        if not app_dir.is_dir():
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"`quality_judge` could not find the hydrogen app tree at "
                    f"`{_HYDROGEN_APP_DIR}/`. Did `clone_template` run?"
                ),
                details={"app_dir": str(app_dir), "exists": False},
            )

        try:
            capabilities_text = capabilities_path.read_text(encoding="utf-8")
            capabilities_payload: Any = json.loads(capabilities_text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"`quality_judge` could not parse `{_CAPABILITIES_FILE}`: "
                    f"{type(exc).__name__}: {exc}"
                ),
                details={"capabilities_path": str(capabilities_path), "error": str(exc)},
            )

        completer = require_completer(ctx.runtime, verifier_name=_NAME)

        source_blocks, files_reviewed, files_elided = render_source_blocks(
            app_dir,
            max_bytes_per_file=self._max_bytes_per_file,
            max_total_bytes=self._max_total_bytes,
        )
        prompt = load_quality_judge_prompt().format(
            task_id=ctx.selected_task_id,
            capabilities=json.dumps(capabilities_payload, indent=2, sort_keys=True),
            source_blocks=source_blocks,
        )

        outcome = dispatch_judge(
            completer,
            prompt=prompt,
            timeout_s=self._timeout_s,
            verifier_name=_NAME,
        )
        if not isinstance(outcome, JudgeOutput):
            return outcome  # Pre-rendered FAIL from dispatch_judge.
        parsed = outcome

        return VerifierResult(
            verdict=parsed.verdict,
            feedback=parsed.feedback,
            details={
                "files_reviewed": files_reviewed,
                "files_elided": files_elided,
                "task_id": ctx.selected_task_id,
            },
        )


__all__ = ["QualityJudgeVerifier"]
