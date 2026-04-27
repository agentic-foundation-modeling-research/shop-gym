"""Phase 5 ``final_eval`` step (spec §5.5.5, impl plan T6.3).

Runs after the build harness loop exits. Drives the playwright smoke flow
against the freshly built hydrogen tree, asks the runtime's
:class:`~harness.runtimes.LLMCompleter` to judge whether the rendered
storefront actually surfaces the merged ``capabilities.json`` document,
and writes the structured verdict to ``<out_dir>/final_eval.json``.

Spec contract (§5.5.5):

* **Quality-only.** No cross-comparison with seed storefronts. The merged
  capabilities document is the only ground truth.
* **Advisory.** The verdict never blocks the run. A passing build loop is
  the gating signal; this step's verdict is recorded for human review,
  not used to gate downstream work. Transport / parse failures during
  the LLM call are recorded into ``final_eval.json`` rather than
  re-raised so the run completes regardless.

Step contract (spec §5.7.1):

* ``id``: ``final_eval``.
* ``phase``: ``final_eval``.
* ``inputs``: :class:`StepInput` for ``run_build_harness_loop`` plus a
  :class:`FileInput` reference to ``manual/capabilities.json``.
* ``outputs``: ``[final_eval.json]``.
* ``depends_on``: ``[run_build_harness_loop]``.

The smoke runner + LLM judge are reachable through three injection seams
so the step is exercised under stubs in CI:

* :class:`~shop_gen.final_eval.playwright_smoke.DevServerFactory` — boots
  the dev server.
* :class:`~shop_gen.final_eval.playwright_smoke.BrowserDriver` — walks
  the smoke flow and writes screenshots.
* :class:`SmokeRunner` — drives the dev server + browser; defaults to
  :func:`shop_gen.final_eval.playwright_smoke.run_playwright_smoke`.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Final, Protocol, cast, runtime_checkable

from harness.runtimes.base import LLMCompleter
from shop_gen.final_eval.playwright_smoke import (
    DEFAULT_VIEWPORTS,
    BrowserDriver,
    DevServerFactory,
    Screenshot,
    SmokeFailure,
    SmokeFlow,
    SmokeReport,
    Viewport,
    resolve_smoke_flow,
    run_playwright_smoke,
)
from shop_gen.final_eval.prompts import load_quality_judge_prompt
from shop_gen.steps.base import FileInput, InputRef, StepContext, StepInput

_PHASE: Final[str] = "final_eval"
_STEP_ID: Final[str] = "final_eval"
_STEP_VERSION: Final[int] = 1

_UPSTREAM_BUILD_LOOP: Final[str] = "run_build_harness_loop"

_IN_CAPABILITIES: Final[Path] = Path("manual") / "capabilities.json"
"""Run-relative path to the merged-or-copied capabilities document."""

_OUT_REPORT: Final[Path] = Path("final_eval.json")
"""Run-relative path of the published advisory verdict file."""

_HYDROGEN_DIR: Final[Path] = Path("runs") / "build" / "artifact" / "hydrogen"
"""Run-relative location of the post-build mutated hydrogen tree.

The build loop step (``run_build_harness_loop``) layers the cloned +
mutated tree under ``<run_dir>/artifact/hydrogen/``; the smoke flow walks
the dev server rooted there.
"""

_SCREENSHOTS_DIR: Final[Path] = Path("runs") / "build" / "final_eval" / "screenshots"
"""Run-relative directory the playwright driver writes screenshots into."""

_DEFAULT_TIMEOUT_S: Final[float] = 180.0
"""Wall-clock budget for the LLM judge call.

Conservative: visually grounded judging over multiple screenshots can
run a few thousand tokens; 3 minutes leaves headroom for cold-start
latency on the configured runtime.
"""

_FAILURES_PLACEHOLDER: Final[str] = "_(none)_"
"""Body shipped in ``{failures_table}`` when the smoke run was clean."""


# --------------------------------------------------------------------------- #
# Output schema
# --------------------------------------------------------------------------- #


_VERDICT_PASS: Final[str] = "pass"
_VERDICT_FAIL: Final[str] = "fail"
_VERDICT_ERROR: Final[str] = "error"
"""``"error"`` is reserved for transport / parse failures; the LLM never emits it."""


# --------------------------------------------------------------------------- #
# Injection seams
# --------------------------------------------------------------------------- #


@runtime_checkable
class SmokeRunner(Protocol):
    """Callable that drives one playwright smoke run.

    Production callers pass :func:`run_playwright_smoke`; tests inject a
    stub that returns a deterministic :class:`SmokeReport` so the step
    can be exercised without booting a dev server.
    """

    def __call__(
        self,
        *,
        hydrogen_dir: Path,
        screenshots_dir: Path,
        flow: SmokeFlow,
        dev_server_factory: DevServerFactory,
        browser_driver: BrowserDriver,
    ) -> SmokeReport:
        """Walk ``flow`` against ``hydrogen_dir`` and aggregate the report."""
        ...


# --------------------------------------------------------------------------- #
# Step
# --------------------------------------------------------------------------- #


class FinalEvalStep:
    """Phase 5 ``final_eval`` step (spec §5.5.5, T6.3).

    Drives the smoke flow + LLM judge and writes the advisory verdict.
    Injection seams keep CI deterministic: production callers wire the
    real Playwright + ``pnpm dev`` driver; tests inject stubs that
    fabricate screenshots and a canned LLM response.

    Attributes:
        id: Step id (``final_eval``).
        phase: ``final_eval``.
        inputs: :class:`StepInput` for ``run_build_harness_loop`` + a
            :class:`FileInput` for ``manual/capabilities.json``.
        outputs: ``[final_eval.json]``.
        depends_on: ``[run_build_harness_loop]``.
        version: Bumped when the step's contract changes (spec §5.7.1).
    """

    def __init__(
        self,
        *,
        dev_server_factory: DevServerFactory | None = None,
        browser_driver: BrowserDriver | None = None,
        smoke_runner: SmokeRunner | None = None,
        viewports: Sequence[Viewport] = DEFAULT_VIEWPORTS,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        """Build the step with optional injection seams.

        Args:
            dev_server_factory: Boots the dev server the smoke flow walks.
                Defaults to :func:`_unconfigured_dev_server_factory`,
                which raises until the production playwright wiring lands
                (M8). Tests inject a stub that yields a fake base URL.
            browser_driver: Walks the smoke flow + writes screenshots.
                Defaults to :func:`_unconfigured_browser_driver`, which
                raises until the production playwright wiring lands.
            smoke_runner: Drives the dev server + browser end-to-end.
                Defaults to
                :func:`~shop_gen.final_eval.playwright_smoke.run_playwright_smoke`.
            viewports: Viewports the smoke flow captures each step at.
                Defaults to :data:`DEFAULT_VIEWPORTS` (one desktop, one
                mobile per spec §5.5.5).
            timeout_s: Wall-clock budget for the LLM judge call.
                Defaults to :data:`_DEFAULT_TIMEOUT_S`.
        """
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [
            StepInput(step_id=_UPSTREAM_BUILD_LOOP),
            FileInput(path=_IN_CAPABILITIES),
        ]
        self.outputs: list[Path] = [_OUT_REPORT]
        self.depends_on: list[str] = [_UPSTREAM_BUILD_LOOP]
        self.version: int = _STEP_VERSION

        self._dev_server_factory: DevServerFactory = (
            dev_server_factory or _unconfigured_dev_server_factory
        )
        self._browser_driver: BrowserDriver = browser_driver or _unconfigured_browser_driver
        self._smoke_runner: SmokeRunner = smoke_runner or run_playwright_smoke
        self._viewports: tuple[Viewport, ...] = tuple(viewports)
        self._timeout_s: float = timeout_s

    def run(self, ctx: StepContext) -> None:
        """Walk the smoke flow, ask the LLM judge, write ``final_eval.json``.

        The verdict is **advisory** (spec §5.5.5): a ``fail`` verdict,
        an LLM transport error, or a parse failure are recorded into
        ``final_eval.json`` rather than re-raised so the run completes.
        Wiring bugs (missing ``out_dir``, missing capabilities, missing
        hydrogen tree) are also recorded as ``error`` verdicts so the
        run continues — the verdict file is the single source of truth
        for what went wrong.

        Args:
            ctx: Execution context. ``ctx.runtime`` should implement
                :class:`~harness.runtimes.LLMCompleter`. ``None`` is
                tolerated and surfaces as an ``error`` verdict.
        """
        report = run_final_eval(
            out_dir=ctx.out_dir,
            completer=ctx.runtime,
            dev_server_factory=self._dev_server_factory,
            browser_driver=self._browser_driver,
            smoke_runner=self._smoke_runner,
            viewports=self._viewports,
            timeout_s=self._timeout_s,
        )
        out_path = ctx.out_dir / _OUT_REPORT
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


# --------------------------------------------------------------------------- #
# Pure driver (testable without a running step)
# --------------------------------------------------------------------------- #


def run_final_eval(
    *,
    out_dir: Path,
    completer: LLMCompleter | None,
    dev_server_factory: DevServerFactory,
    browser_driver: BrowserDriver,
    smoke_runner: SmokeRunner = run_playwright_smoke,
    viewports: Sequence[Viewport] = DEFAULT_VIEWPORTS,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Drive the smoke flow + LLM judge and return the advisory verdict body.

    The function is **non-raising** by contract: every recoverable
    failure (missing capabilities, missing hydrogen tree, LLM transport
    error, parse error, runtime without a completer) is captured in the
    returned report rather than surfaced as an exception. The caller
    persists the body verbatim into ``final_eval.json``.

    Args:
        out_dir: Run workspace. Reads
            ``<out_dir>/manual/capabilities.json`` and the post-build
            hydrogen tree under
            ``<out_dir>/runs/build/artifact/hydrogen/``.
        completer: Optional :class:`LLMCompleter` for the judge call.
            ``None`` (or a runtime that does not implement the protocol)
            is recorded as an ``error`` verdict.
        dev_server_factory: Boots the dev server.
        browser_driver: Walks the smoke flow and writes screenshots.
        smoke_runner: Drives ``dev_server_factory`` + ``browser_driver``
            end-to-end. Defaults to :func:`run_playwright_smoke`.
        viewports: Viewports each smoke step is captured at.
        timeout_s: Wall-clock budget for the LLM judge call.

    Returns:
        JSON-serialisable mapping with keys:

        * ``ok`` — overall pass (smoke clean *and* verdict ``pass``).
        * ``smoke`` — ``{base_url, screenshots[], failures[]}``.
        * ``judge`` — ``{verdict, feedback, error}``. ``verdict`` is
          ``"pass"`` / ``"fail"`` / ``"error"``; ``error`` is ``null``
          on a clean LLM round trip and a short diagnostic otherwise.
    """
    flow = resolve_smoke_flow(out_dir=out_dir, viewports=viewports)
    hydrogen_dir = out_dir / _HYDROGEN_DIR
    screenshots_dir = out_dir / _SCREENSHOTS_DIR

    smoke_payload = _run_smoke(
        hydrogen_dir=hydrogen_dir,
        screenshots_dir=screenshots_dir,
        flow=flow,
        dev_server_factory=dev_server_factory,
        browser_driver=browser_driver,
        smoke_runner=smoke_runner,
        out_dir=out_dir,
    )

    judge_payload = _run_judge(
        out_dir=out_dir,
        completer=completer,
        smoke_payload=smoke_payload,
        timeout_s=timeout_s,
    )

    smoke_clean = not smoke_payload["failures"] and smoke_payload.get("error") is None
    return {
        "ok": smoke_clean and judge_payload["verdict"] == _VERDICT_PASS,
        "smoke": smoke_payload,
        "judge": judge_payload,
    }


# --------------------------------------------------------------------------- #
# Internals — smoke
# --------------------------------------------------------------------------- #


def _run_smoke(
    *,
    hydrogen_dir: Path,
    screenshots_dir: Path,
    flow: SmokeFlow,
    dev_server_factory: DevServerFactory,
    browser_driver: BrowserDriver,
    smoke_runner: SmokeRunner,
    out_dir: Path,
) -> dict[str, Any]:
    """Drive the smoke flow and return a JSON-serialisable summary.

    Catches the documented :exc:`FileNotFoundError` (missing hydrogen
    tree) and any unexpected exception so a smoke failure never blocks
    the advisory verdict. The error is captured in the returned payload
    so the LLM judge can react to it (and the report records it for the
    human reviewer).
    """
    try:
        report = smoke_runner(
            hydrogen_dir=hydrogen_dir,
            screenshots_dir=screenshots_dir,
            flow=flow,
            dev_server_factory=dev_server_factory,
            browser_driver=browser_driver,
        )
    except FileNotFoundError as exc:
        return {
            "base_url": None,
            "screenshots": [],
            "failures": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    except Exception as exc:
        return {
            "base_url": None,
            "screenshots": [],
            "failures": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    return _serialise_smoke_report(report, out_dir=out_dir)


def _serialise_smoke_report(report: SmokeReport, *, out_dir: Path) -> dict[str, Any]:
    """Project :class:`SmokeReport` onto the JSON shape ``final_eval.json`` records."""
    return {
        "base_url": report.base_url,
        "screenshots": [
            {
                "step": shot.step,
                "viewport": shot.viewport,
                "path": _relative_or_str(shot.path, base=out_dir),
                "url": shot.url,
            }
            for shot in report.screenshots
        ],
        "failures": [
            {
                "step": failure.step,
                "viewport": failure.viewport,
                "error": failure.error,
            }
            for failure in report.failures
        ],
        "error": None,
    }


def _relative_or_str(path: Path, *, base: Path) -> str:
    """Return ``path`` relative to ``base`` (POSIX) or its string form on mismatch."""
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- #
# Internals — judge
# --------------------------------------------------------------------------- #


def _run_judge(
    *,
    out_dir: Path,
    completer: LLMCompleter | None,
    smoke_payload: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    """Render the prompt, call the LLM, and project its verdict for the report.

    All recoverable failures (missing capabilities, missing completer,
    transport / parse errors) collapse to a single ``verdict="error"``
    entry with a short diagnostic. The advisory contract (spec §5.5.5)
    forbids re-raising from this path.
    """
    capabilities_payload = _load_capabilities(out_dir / _IN_CAPABILITIES)
    if isinstance(capabilities_payload, str):
        return _judge_error(capabilities_payload)
    if not isinstance(completer, LLMCompleter):
        return _judge_error(
            "runtime does not implement LLMCompleter; final-eval judge skipped",
        )
    prompt = load_quality_judge_prompt().format(
        base_url=smoke_payload.get("base_url") or "(unavailable)",
        capabilities=json.dumps(capabilities_payload, indent=2, sort_keys=True),
        screenshots_table=_render_screenshots_table(smoke_payload["screenshots"]),
        failures_table=_render_failures_table(smoke_payload["failures"]),
    )
    return _dispatch_llm_judge(completer, prompt=prompt, timeout_s=timeout_s)


def _load_capabilities(path: Path) -> Any:
    """Return the parsed capabilities payload or a diagnostic message.

    Returns:
        The parsed JSON payload on success, or a string diagnostic the
        caller surfaces verbatim through :func:`_judge_error` on a
        missing / unreadable / unparseable file.
    """
    if not path.is_file():
        return f"capabilities document not found at `{_IN_CAPABILITIES.as_posix()}`"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return f"could not parse `{_IN_CAPABILITIES.as_posix()}`: {type(exc).__name__}: {exc}"


def _dispatch_llm_judge(
    completer: LLMCompleter,
    *,
    prompt: str,
    timeout_s: float,
) -> dict[str, Any]:
    """Call the LLM, parse its verdict, and shape the report entry."""
    try:
        raw = completer.complete(prompt, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return _judge_error(
            f"LLM call exceeded the verifier timeout of {timeout_s:.0f}s",
        )
    except Exception as exc:
        return _judge_error(f"LLM call raised {type(exc).__name__}: {exc}")
    parsed = _parse_judge_output(raw)
    if parsed is None:
        return _judge_error(f"could not parse the LLM verdict; raw={raw!r}")
    verdict, feedback = parsed
    return {"verdict": verdict, "feedback": feedback, "error": None}


def _judge_error(message: str) -> dict[str, Any]:
    """Shape an ``error`` verdict entry."""
    return {"verdict": _VERDICT_ERROR, "feedback": "", "error": message}


_FENCE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"```(?:json)?\s*(?P<body>\{.*?\})\s*```",
    re.DOTALL,
)
"""Match the first fenced ```json``` block in a model response."""

_BARE_OBJECT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?P<body>\{.*\})",
    re.DOTALL,
)
"""Match a bare top-level JSON object as a fallback."""

_VALID_VERDICTS: Final[frozenset[str]] = frozenset({_VERDICT_PASS, _VERDICT_FAIL})
"""Verdict tokens the LLM is allowed to emit (lowercase)."""


def _parse_judge_output(raw: str) -> tuple[str, str] | None:
    """Parse the LLM judge response.

    Mirrors the build-loop ``quality_judge`` parser
    (:mod:`shop_gen.build.verifiers._judge`): forgive surrounding
    chatter, accept a fenced ``json`` block, and fall back to the first
    ``{...}`` slice. Returns ``None`` on any unrecoverable parse error;
    the caller renders an ``error`` verdict in that case.
    """
    body = _extract_json_object(raw)
    if body is None:
        return None
    try:
        payload: Any = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    payload_dict = cast("dict[str, Any]", payload)
    verdict_raw = payload_dict.get("verdict")
    feedback_raw = payload_dict.get("feedback", "")
    if not isinstance(verdict_raw, str) or not isinstance(feedback_raw, str):
        return None
    verdict_token = verdict_raw.strip().lower()
    if verdict_token not in _VALID_VERDICTS:
        return None
    feedback = feedback_raw.strip()
    return verdict_token, feedback


def _extract_json_object(raw: str) -> str | None:
    """Return the first JSON object body found in ``raw`` or ``None``."""
    fence_match = _FENCE_PATTERN.search(raw)
    if fence_match is not None:
        return fence_match.group("body")
    bare_match = _BARE_OBJECT_PATTERN.search(raw)
    if bare_match is not None:
        return bare_match.group("body")
    return None


def _render_screenshots_table(rows: Sequence[dict[str, Any]]) -> str:
    """Render the ``{screenshots_table}`` slot.

    A clean run has one row per ``(step, viewport)`` pair; an empty
    smoke result (e.g. dev-server boot failure) renders the placeholder
    so the prompt template still formats cleanly.
    """
    if not rows:
        return _FAILURES_PLACEHOLDER
    header = "| step | viewport | url | path |\n| --- | --- | --- | --- |"
    body_lines = [
        f"| {row['step']} | {row['viewport']} | {row['url']} | {row['path']} |" for row in rows
    ]
    return "\n".join([header, *body_lines])


def _render_failures_table(rows: Sequence[dict[str, Any]]) -> str:
    """Render the ``{failures_table}`` slot or :data:`_FAILURES_PLACEHOLDER`."""
    if not rows:
        return _FAILURES_PLACEHOLDER
    header = "| step | viewport | error |\n| --- | --- | --- |"
    body_lines = [f"| {row['step']} | {row['viewport']} | {row['error']} |" for row in rows]
    return "\n".join([header, *body_lines])


# --------------------------------------------------------------------------- #
# Defaults — placeholders until the production playwright wiring lands
# --------------------------------------------------------------------------- #


def _unconfigured_dev_server_factory(
    hydrogen_dir: Path,
) -> AbstractContextManager[str]:  # pragma: no cover — production wiring deferred.
    """Default :class:`DevServerFactory` — refuses to boot.

    The production ``pnpm dev`` driver is deferred (spec §5.5.5 +
    impl plan T6.x); v0.1 ships the step with seams so callers / tests
    inject a working factory. A run that hits this default lands an
    ``error`` verdict in :data:`final_eval.json` rather than crashing
    the pipeline (advisory contract).
    """
    del hydrogen_dir
    raise NotImplementedError(
        "default final_eval dev_server_factory is unconfigured; "
        "inject a `dev_server_factory` via the FinalEvalStep constructor.",
    )


def _unconfigured_browser_driver(
    *,
    base_url: str,
    flow: SmokeFlow,
    screenshots_dir: Path,
) -> tuple[tuple[Screenshot, ...], tuple[SmokeFailure, ...]]:  # pragma: no cover
    """Default :class:`BrowserDriver` — refuses to drive a browser."""
    del base_url, flow, screenshots_dir
    raise NotImplementedError(
        "default final_eval browser_driver is unconfigured; "
        "inject a `browser_driver` via the FinalEvalStep constructor.",
    )


__all__ = [
    "FinalEvalStep",
    "SmokeRunner",
    "run_final_eval",
]
