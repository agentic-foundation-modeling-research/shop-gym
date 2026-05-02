"""Run all scripted transitions for one shop.

Each transition runs in its own isolated Playwright context (so cart
state from one transition does not leak into the next). Errors fold into
the :class:`shop_arena.probe.report.TransitionResult` rather than aborting
the suite.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from playwright.async_api import Page

from shop_arena.probe.playwright_runner import PlaywrightRunner
from shop_arena.probe.report import TransitionResult
from shop_arena.probe.rubric.schema import PageType, RubricEntry
from shop_arena.probe.transition.scripts import SCRIPTS, TransitionContext, TransitionScript

TransitionsResult = dict[PageType, dict[str, TransitionResult]]


def _make_runner_callable(
    fn: TransitionScript,
    *,
    base_url: str,
    sample_collection_url: str | None,
    sample_product_url: str | None,
) -> Callable[[Page], Awaitable[TransitionResult]]:
    """Wrap a transition script into ``PlaywrightRunner.run``'s callable shape."""

    async def _do(page: Page) -> TransitionResult:
        ctx = TransitionContext(
            page=page,
            base_url=base_url,
            sample_collection_url=sample_collection_url,
            sample_product_url=sample_product_url,
        )
        return await fn(ctx)

    return _do


async def run_transitions(
    entries: tuple[RubricEntry, ...],
    *,
    runner: PlaywrightRunner,
    base_url: str,
    sample_collection_url: str | None,
    sample_product_url: str | None,
) -> TransitionsResult:
    """Dispatch every transition entry and accumulate results.

    Args:
        entries: All rubric entries; only ``family=transition kind=scripted``
            rows are dispatched.
        runner: Live :class:`PlaywrightRunner`.
        base_url: Storefront under test.
        sample_collection_url: Pre-resolved collection URL or ``None``.
        sample_product_url: Pre-resolved product URL or ``None``.

    Returns:
        ``{page_type: {transition_id: TransitionResult}}``.
    """
    out: TransitionsResult = {}
    for entry in entries:
        if entry.family != "transition" or entry.kind != "scripted":
            continue
        assert entry.page_type is not None
        assert entry.script is not None
        script_fn = SCRIPTS.get(entry.script)
        if script_fn is None:
            result = TransitionResult(
                action_found=False,
                action_executed=False,
                state_changed=False,
                state_changed_as_expected=False,
                latency_ms=0,
                notes=f"unknown script {entry.script!r}",
            )
        else:
            do_call = _make_runner_callable(
                script_fn,
                base_url=base_url,
                sample_collection_url=sample_collection_url,
                sample_product_url=sample_product_url,
            )
            try:
                result, _outcome = await runner.run(do_call)
            except TimeoutError:
                result = TransitionResult(
                    action_found=False,
                    action_executed=False,
                    state_changed=False,
                    state_changed_as_expected=False,
                    latency_ms=0,
                    notes="transition runner timeout",
                )
            except Exception as err:  # noqa: BLE001
                result = TransitionResult(
                    action_found=False,
                    action_executed=False,
                    state_changed=False,
                    state_changed_as_expected=False,
                    latency_ms=0,
                    notes=f"{type(err).__name__}: {err}",
                )

        page_bucket = out.setdefault(entry.page_type, {})
        page_bucket[entry.id] = result
    return out
