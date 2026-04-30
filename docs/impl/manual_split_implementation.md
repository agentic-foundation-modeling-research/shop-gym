# Manual Split — Implementation Plan

Spec: [`docs/specs/shop_arena/manual_split.md`](../specs/shop_arena/manual_split.md)

---

## 1. Overview

Implements the `split_manual_parts` step plus the planner / executor
prompt refresh and the removal of the `consolidate` fallback. All
work lives in `packages/shop_arena`; `packages/harness` is untouched
by this slice.

---

## 2. Terminology

Match the spec.

---

## 3. Current Status

See spec §3.

---

## 4. Desired Status

After this slice lands:

- `manual_merge` phase produces six sub-manuals at
  ``manual/parts/<area>.md`` in addition to the existing
  ``manual/manual.md``.
- Build planner emits an 8-task canonical block. No `consolidate` task,
  no `visual_polish` task; the final task is `visual_fix`.
- Each `gen_*` executor reads its sub-manual; `gen_theme` and
  `visual_fix` read the full merged manual.

---

## 5. Proposal

### 5.1 Module layout

```
packages/shop_arena/src/shop_gen/manual_merge/
├── __init__.py                           (re-export new symbols)
├── prose.py                              (bump _STEP_VERSION; _parse_manual_sections relocated to a shared module-level helper or re-exported)
├── split.py                              (new: split_manual_into_parts + SplitManualPartsStep)
└── prompts/merge_manual_prose.md         (text edit only)

packages/shop_arena/src/shop_gen/build/
├── consolidate.py                        (DELETED)
├── loop.py                               (drop consolidate post-call resume)
├── prompts.py                            (drop load_consolidate_execute_prompt)
└── prompts/
    ├── consolidate_execute.md            (DELETED)
    ├── planner.md                        (replace canonical block; reference sub-manual paths)
    └── execute.md                        (per-task sub-manual reading list; rename visual_polish → visual_fix)

packages/shop_arena/src/shop_gen/
└── pipeline.py                           (register SplitManualPartsStep in both seed branches)

packages/shop_arena/tests/
├── manual_merge/test_split.py            (NEW)
├── manual_merge/test_prose.py            (verify prompt template renders post-rewrite)
└── build/test_loop.py                    (drop consolidate fallback case)
```

### 5.2 split_manual_into_parts

Pure helper, signature:

```python
def split_manual_into_parts(manual_text: str) -> dict[str, str]:
    """Return {part_name: sub_manual_body} for the six canonical parts.

    Each value is the full sub-manual body (H1 line + routed H2
    sections in canonical order, ending with one trailing newline).

    Raises:
        ValueError: The merged manual is missing ALL of {Homepage,
            Product page, Collections & navigation, Cart, Policy &
            info pages} — a regressed merge.
    """
```

Implementation notes:

- Re-uses the existing `_parse_manual_sections` from
  `manual_merge/prose.py`. Cleanest move: relocate it to a shared
  module-level helper (e.g. expose as
  `shop_gen.manual_merge.prose.parse_manual_sections`, drop the
  leading underscore) so tests can import it without going through
  the private name. `prose.py` keeps using its own reference.
- Iterate the six sub-manual buckets in deterministic order; for each
  bucket, walk `_CANONICAL_SECTIONS` and append every section that
  routes to it, in canonical order.
- An empty bucket emits a one-line placeholder body
  (``_(no sections from the merged manual route to this part)_``)
  so downstream consumers always have a non-empty file.

### 5.3 SplitManualPartsStep

```python
_STEP_ID = "split_manual_parts"
_PHASE = "manual_merge"
_STEP_VERSION = 1

# inputs is the upstream manual producer; depends_on gates cache
# staleness so a re-merge invalidates the parts.
```

Two construction modes (mirrors `MergeManualProseStep`):

- Multi-seed branch: `depends_on=["merge_manual_prose"]`,
  `inputs=[StepInput(step_id="merge_manual_prose")]`.
- Single-seed branch: `depends_on=["copy_seed_manual"]`,
  `inputs=[StepInput(step_id="copy_seed_manual")]`.

The selection happens in `pipeline._register_manual_merge` /
`_register_single_seed_manual`; the step accepts an `upstream_step_id`
constructor arg.

`run(ctx)` reads `ctx.out_dir / "manual" / "manual.md"`, calls
`split_manual_into_parts`, and writes each sub-manual under
`ctx.out_dir / "manual" / "parts" /`.

### 5.4 Pipeline registration

```python
def _register_manual_merge(registry, *, config=None):
    ...
    registry.register(MergeManualProseStep(...))
    registry.register(SplitManualPartsStep(upstream_step_id="merge_manual_prose"))
    registry.register(ComputeMergeStatsStep(...))
    registry.register(WriteMergeManifestStep())


def _register_single_seed_manual(registry, *, config=None):
    ...
    registry.register(CopySeedManualStep(...))
    registry.register(SplitManualPartsStep(upstream_step_id="copy_seed_manual"))
```

In `_build_registry`, the `manual_step_ids` tuple expands to include
`split_manual_parts` so synth steps that read the manual rebuild when
the parts change:

```python
manual_step_ids = ("merge_capabilities", "merge_manual_prose", "split_manual_parts")
# single-seed:
manual_step_ids = ("copy_seed_manual", "split_manual_parts")
```

### 5.5 Prompt edits

`build/prompts/planner.md` — full canonical block becomes:

```
- [ ] gen_theme        — write design tokens, palette, typography per the manual's tone; wire them through the Hydrogen theme entry [priority: 9]
- [ ] gen_navigation   — implement Header, Footer, MegaMenu, mobile nav, announcement bar from `data/navigation.json` and `artifact/manual/parts/navigation.md` [priority: 8]
- [ ] gen_homepage     — render hero, featured collections, and any promo banner from `homepage.section_types` and `artifact/manual/parts/homepage.md` [priority: 7]
- [ ] gen_collections  — collection list + collection detail per `capabilities.collection` and `artifact/manual/parts/collections.md` [priority: 6]
- [ ] gen_product      — product detail with variant pickers, gallery per `capabilities.product` and `artifact/manual/parts/product.md` [priority: 5]
- [ ] gen_cart_search  — cart drawer + predictive search per `capabilities.cart` / `capabilities.search` and `artifact/manual/parts/cart_and_search.md` [priority: 4]
- [ ] gen_info_pages   — every page in `info_pages_present` per `artifact/manual/parts/info_pages.md`; wire into routes and the footer [priority: 3]
- [ ] visual_fix       — REQUIRED final task; fix leftover `[!]` task issues and cross-page seams (shared-component drift, token drift, broken inter-page links, deferred verifier feedback) [priority: 2]
```

`build/prompts/execute.md`:

- §2 ("Reading the inputs"): per-task table swaps in.
- §3 ("Stay in your slice."): drop the `consolidate` row, rename
  `visual_polish` → `visual_fix`. The `visual_fix` row's owned slice
  is "cross-cutting cleanup across slices, no new components" with the
  cross-cutting authority that previously belonged to consolidate.

### 5.6 Removal

- Delete `packages/shop_arena/src/shop_gen/build/prompts/consolidate_execute.md`.
- Delete `packages/shop_arena/src/shop_gen/build/consolidate.py`.
- In `packages/shop_arena/src/shop_gen/build/prompts.py`:
  - Drop `load_consolidate_execute_prompt`, `_CONSOLIDATE_EXECUTE_FILE`.
  - Drop the matching `__all__` entry.
- In `packages/shop_arena/src/shop_gen/build/loop.py`:
  - Drop `from shop_gen.build.consolidate import ensure_consolidate_task`.
  - Drop the post-`_loop_runner` `if ... ensure_consolidate_task ...`
    block (lines ~420-435 today).

---

## 6. Alternative

See spec §6.

---

## 7. Milestones

| ID | Description | Files |
|----|-------------|-------|
| T1 | Loosen `merge_manual_prose` prompt for detail preservation; bump `_STEP_VERSION` | `manual_merge/prompts/merge_manual_prose.md`, `manual_merge/prose.py` |
| T2 | Implement `split_manual_into_parts` + `SplitManualPartsStep` | `manual_merge/split.py`, `manual_merge/__init__.py` |
| T3 | Register the new step in the pipeline (both seed branches), thread `manual_step_ids` updates | `pipeline.py` |
| T4 | Refresh `planner.md` (8-task block, sub-manual references) | `build/prompts/planner.md` |
| T5 | Refresh `execute.md` (sub-manual reading list, owned-slice table) | `build/prompts/execute.md` |
| T6 | Delete `consolidate.py`, `consolidate_execute.md`; clean up `build/prompts.py` and `build/loop.py` | (deletions + edits) |
| T7 | New unit tests for the split step + prose-prompt-template render check | `tests/manual_merge/test_split.py`, `tests/manual_merge/test_prose.py` |
| T8 | Drop the consolidate-fallback test case; cover 8-task list | `tests/build/test_loop.py` |

---

## 8. Appendix

### 8.1 Verification commands

```
uv run pytest packages/shop_arena/tests/manual_merge -k "split or prose"
uv run pytest packages/shop_arena/tests/build/test_loop.py
uv run pyright packages/shop_arena
uv run ruff check packages/shop_arena
```

End-to-end:

```
uv run shop-gen --steps merge_manual_prose,split_manual_parts --shop mock_cookware
ls outputs/shops/mock_cookware/manual/parts/
```

### 8.2 References

Same as the spec.
