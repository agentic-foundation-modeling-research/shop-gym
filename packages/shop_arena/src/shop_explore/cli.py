"""Command-line entrypoint for ``shop_explore``.

Implements the §5.11 CLI surface of
``docs/specs/shop_arena/shop_explore.md``. v0.1 wires two debug paths:

* ``--prefetch-only`` runs §5.9 against the supplied URL and exits.
* ``--synthesize-only PATH`` re-runs §5.10 against an existing
  ``run_dir`` (the M3 mirror of the legacy ``--merge-only`` flag).

Default invocation (no flag) drives the full pipeline through
:mod:`shop_explore.pipeline`. Both the default and the
``--synthesize-only`` paths route the §5.10 manual-merge LLM call
through the configured harness runtime via
:func:`shop_explore.pipeline.build_runtime_llm` — when ``--runtime``
satisfies :class:`harness.runtimes.LLMCompleter` (``pi`` today) the synthesis
hits the same model the runtime drives iterations with; otherwise it
falls back to the no-op client and the deterministic concatenation of
``parts/*.md`` (impl plan T6.2).

Pointing ``--out`` at an existing run directory triggers resume mode
(``docs/specs/harness/resume.md`` §5.6): the prior ``run.json``'s
``config_snapshot`` is consulted to fill in ``--max-iters`` and
``--timeout`` defaults, ``--url`` and ``--runtime`` must match the
prior values when supplied, and ``--force-resume`` propagates to
:func:`harness.run_plan_exec_loop` (``force=True``) for §5.5 overrides.

The module is import-safe: it performs no I/O at import time.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from harness import get_runtime
from shop_explore.config import (
    DEFAULT_MAX_ITERS,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    ExploreConfig,
)
from shop_explore.pipeline import build_runtime_llm, explore
from shop_explore.prefetch import ShopUnreachableError
from shop_explore.prefetch import run as run_prefetch
from shop_explore.synthesize import (
    SynthesisError,
)
from shop_explore.synthesize import (
    synthesize as run_synthesize,
)

EXIT_OK = 0
"""Successful run."""

EXIT_USAGE = 2
"""Reserved by argparse for usage errors; also used for storefront errors."""


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the matching handler.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code. ``0`` on success; ``2`` if the storefront is
        unreachable (bot-block, robots.txt deny, network error), if the
        ``--synthesize-only`` ``run_dir`` is missing or its layout is
        invalid, or on argparse usage errors.
    """
    args = _build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="shop-explore: %(message)s",
        stream=sys.stderr,
    )

    if args.prefetch_only:
        return _run_prefetch_only(args)

    if args.synthesize_only is not None:
        return _run_synthesize_only(args)

    return _run_explore(args)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser described in spec §5.11."""
    parser = argparse.ArgumentParser(
        prog="shop-explore",
        description=(
            "Explore a public storefront and emit a Shop Manual under "
            "outputs/shop_manuals/<domain>/<run_id>/."
        ),
    )
    parser.add_argument(
        "url",
        help="Public storefront base URL (http:// or https://).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="PATH",
        help=("Run workspace directory. Defaults to outputs/shop_manuals/<domain>/<run_id>/."),
    )
    parser.add_argument(
        "--runtime",
        choices=("pi", "claude_code"),
        default=None,
        help=(
            "Agent runtime for the plan/exec loop. Defaults to 'pi' for fresh runs; "
            "on resume (--out points at an existing run dir) defaults to the prior "
            "run's runtime and must match if supplied."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help=(
            "Model identifier forwarded to the runtime as --model. Defaults to "
            f"{DEFAULT_MODEL!r} for fresh runs; on resume defaults to the prior "
            "run's value. Pass the empty string to skip the flag entirely and "
            "let the runtime use its own default."
        ),
    )
    parser.add_argument(
        "--max-iters",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Executor iteration budget. Defaults to "
            f"{DEFAULT_MAX_ITERS} for fresh runs; on resume defaults to the "
            "prior run's value (interpreted as additional budget per resume.md §5)."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Per-iteration timeout in seconds. Defaults to "
            f"{int(DEFAULT_TIMEOUT_SECONDS)} for fresh runs; on resume defaults "
            "to the prior run's value."
        ),
    )
    parser.add_argument(
        "--force-resume",
        action="store_true",
        help=(
            "Override the harness refusal policy when resuming a prior run that "
            "ended in a bad state (resume.md §5.5). Has no effect on fresh runs."
        ),
    )
    parser.add_argument(
        "--prefetch-only",
        action="store_true",
        help="Run the §5.9 prefetch step and exit; useful for debugging.",
    )
    parser.add_argument(
        "--synthesize-only",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Re-run §5.10 synthesis against an existing run_dir; mirrors "
            "the legacy --merge-only flag. Skips prefetch and the harness loop."
        ),
    )
    return parser


def _run_prefetch_only(args: argparse.Namespace) -> int:
    """Execute the ``--prefetch-only`` path: §5.9 prefetch then exit."""
    out_dir = args.out if args.out is not None else _default_run_dir(args.url)
    dest_dir = out_dir / "artifact" / "prefetch"
    try:
        result = run_prefetch(args.url, dest_dir=dest_dir)
    except ShopUnreachableError as exc:
        print(f"shop-explore: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(
        f"shop-explore: wrote {len(result.entries)} prefetch entries to {dest_dir}",
    )
    return EXIT_OK


def _run_synthesize_only(args: argparse.Namespace) -> int:
    """Execute the ``--synthesize-only PATH`` path: §5.10 against ``PATH``.

    Resolves the configured harness runtime and routes the manual-merge
    LLM call through it (impl plan T6.2). Runtimes that do not satisfy
    :class:`harness.runtimes.LLMCompleter` cause :func:`build_runtime_llm`
    to raise :class:`SynthesisError`; the CLI surfaces that as a usage
    error rather than silently falling back to a deterministic merge
    (M3 behaviour — earlier revisions silently masked LLM-client
    misconfiguration).
    """
    run_dir: Path = args.synthesize_only
    if not run_dir.is_dir():
        print(
            f"shop-explore: --synthesize-only PATH must be an existing directory: {run_dir}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    manual_prompt = _load_manual_prompt()
    runtime_name = args.runtime if args.runtime is not None else "pi"
    model = _resolve_model_arg(args.model)
    timeout = args.timeout if args.timeout is not None else DEFAULT_TIMEOUT_SECONDS
    runtime = get_runtime(runtime_name, **_runtime_kwargs(model))
    try:
        llm = build_runtime_llm(runtime, timeout=timeout)
        result = run_synthesize(run_dir, llm=llm, manual_prompt=manual_prompt)
    except SynthesisError as exc:
        print(f"shop-explore: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(f"shop-explore: synthesized {result.manual_path}")
    return EXIT_OK


def _run_explore(args: argparse.Namespace) -> int:
    """Execute the default invocation: full pipeline via :func:`shop_explore.pipeline.explore`.

    When ``--out`` points at an existing run_dir with a prior ``run.json``,
    the CLI falls into resume mode (``docs/specs/harness/resume.md`` §5.6):

    * ``--max-iters`` and ``--timeout`` default to the prior run's values
      when not supplied on the command line. Per resume.md §5,
      ``max_iters`` is granted as *additional* budget by the harness.
    * ``--runtime`` and ``--model`` default to the prior run's values; if
      supplied, ``--runtime`` must match — otherwise we exit with
      :data:`EXIT_USAGE` before any subprocess is spawned. ``--model`` is
      not strictly identity-checked because the harness does not include
      it in the resume identity tuple.
    * The positional ``url`` must match the prior run's URL.
    * ``--force-resume`` is forwarded to the harness via
      :class:`shop_explore.config.ExploreConfig` so the §5.5 refusal
      policy can be overridden when needed.
    """
    prior = _read_prior_run_config(args.out) if args.out is not None else None
    if prior is not None:
        prior_url = prior.get("url")
        if isinstance(prior_url, str) and prior_url != args.url:
            print(
                f"shop-explore: url {args.url!r} does not match prior run "
                f"({prior_url!r}) at {args.out}",
                file=sys.stderr,
            )
            return EXIT_USAGE
        prior_runtime = prior.get("runtime")
        if (
            args.runtime is not None
            and isinstance(prior_runtime, str)
            and prior_runtime != args.runtime
        ):
            print(
                f"shop-explore: --runtime {args.runtime!r} does not match prior run "
                f"({prior_runtime!r}) at {args.out}",
                file=sys.stderr,
            )
            return EXIT_USAGE

    runtime = args.runtime if args.runtime is not None else _prior_or(prior, "runtime", "pi")
    max_iters = (
        args.max_iters
        if args.max_iters is not None
        else _prior_or(prior, "max_iters", DEFAULT_MAX_ITERS)
    )
    timeout = (
        args.timeout
        if args.timeout is not None
        else _prior_or(prior, "timeout", DEFAULT_TIMEOUT_SECONDS)
    )
    model = (
        _resolve_model_arg(args.model)
        if args.model is not None
        else _prior_or(prior, "model", DEFAULT_MODEL)
    )

    config = ExploreConfig(
        url=args.url,
        out_dir=args.out,
        runtime=runtime,
        model=model,
        max_iters=max_iters,
        timeout=timeout,
        force_resume=args.force_resume,
    )
    try:
        result = explore(config)
    except ShopUnreachableError as exc:
        print(f"shop-explore: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except SynthesisError as exc:
        print(f"shop-explore: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(
        f"shop-explore: wrote manual to {result.manual_path} "
        f"(harness final_status={result.final_status.value})",
    )
    return EXIT_OK


def _read_prior_run_config(run_dir: Path | None) -> dict[str, Any] | None:
    """Return the ``config_snapshot`` from ``run_dir/run.json`` if present.

    Returns ``None`` when ``run_dir`` is missing, has no ``run.json``, or
    the file's payload is not a JSON object containing a
    ``config_snapshot`` object. The harness ultimately validates the
    resume identity tuple via :class:`harness.workspace.Workspace.open`,
    so this helper only needs to be best-effort: a malformed file is
    surfaced by the harness with a clearer error than the CLI could
    produce on its own.
    """
    if run_dir is None or not run_dir.is_dir():
        return None
    run_summary_path = run_dir / "run.json"
    if not run_summary_path.is_file():
        return None
    try:
        payload = json.loads(run_summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    snapshot = cast("dict[str, Any]", payload).get("config_snapshot")
    if not isinstance(snapshot, dict):
        return None
    return cast("dict[str, Any]", snapshot)


def _prior_or(prior: dict[str, Any] | None, key: str, default: Any) -> Any:
    """Return ``prior[key]`` when present and non-``None``; else ``default``."""
    if prior is None:
        return default
    value = prior.get(key)
    return default if value is None else value


def _resolve_model_arg(value: str | None) -> str | None:
    """Map ``--model`` argv to the value forwarded to the runtime.

    ``None`` (flag omitted on a fresh run) yields :data:`DEFAULT_MODEL`.
    The empty string ``""`` is the explicit opt-out: pass ``None`` to
    the runtime so no ``--model`` flag is forwarded and the runtime's
    own default applies.
    """
    if value is None:
        return DEFAULT_MODEL
    if value == "":
        return None
    return value


def _runtime_kwargs(model: str | None) -> dict[str, Any]:
    """Build ``**kwargs`` for :func:`harness.get_runtime` given a model."""
    return {"model": model} if model is not None else {}


def _load_manual_prompt() -> str:
    """Read the bundled ``synthesize_manual.md`` prompt resource."""
    prompts_dir = Path(__file__).resolve().parent / "prompts"
    return (prompts_dir / "synthesize_manual.md").read_text(encoding="utf-8")


def _default_run_dir(url: str) -> Path:
    """Compute ``outputs/shop_manuals/<domain>/<run_id>/`` for ``url``.

    ``run_id`` is a UTC timestamp plus an 8-char random suffix; this is
    enough for human-readable run isolation without coordinating with
    other processes.
    """
    domain = urlsplit(url).hostname or "unknown"
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    return Path("outputs") / "shop_manuals" / domain / run_id


if __name__ == "__main__":
    raise SystemExit(main())
