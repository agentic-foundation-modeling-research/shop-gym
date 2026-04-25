# `fermliving_live/` — captured artefacts from the M4 manual gate (T4.5)

This directory holds the `run_dir/` from a successful local run of the
T4.5 live test (`tests/shop_explore/smoke/test_pi_fermliving.py`)
against `https://fermliving.com` with the real `pi` runtime.

It is committed so future regressions on the same shop are
diff-reviewable. It is **not** loaded by any test — the M4 gate
re-runs the live pipeline rather than replaying these artefacts.

## How this directory gets populated

The live test writes here only when both env vars are set:

```bash
SHOP_EXPLORE_LIVE_FERMLIVING=1 \
SHOP_EXPLORE_LIVE_PERSIST=1 \
  uv run pytest \
    packages/shop_arena/tests/shop_explore/smoke/test_pi_fermliving.py
```

Without `SHOP_EXPLORE_LIVE_PERSIST=1` the test runs against a tmp dir
and is discarded.

## Pre-commit checklist (mirrors `cassettes/README.md`)

1. Anonymization scan over the captured `manual.md` and
   `capabilities.json` must be clean — the test's own
   `_scan_for_leaks` step covers this, but re-run
   `pytest packages/shop_arena/tests/shop_explore/test_anonymization.py`
   to confirm the M2 fixture is unaffected.
2. Hand-review `artifact/evidence/<task_id>/screenshots/*.png` for
   brand-identifying imagery; remove or redact as needed.
3. Strip every `iters/*/native.log` of any API keys before committing
   (the harness writes these by default).
4. Commit the populated tree under this directory; do **not** commit
   `iters/**/native.log` raw — gitignored via `.gitignore` below.

## Status

Currently empty. The live run is the manual M4 milestone gate; this
README is committed so the destination is unambiguous. Replace this
file with the captured `run_dir/` contents after a successful run.
