# Manual Split — Per-Area Sub-Manuals (`packages/shop_arena`)

Status: **Proposed** · Version: **0.1**
Owners: ShopGym

> Adds a deterministic post-merge step that slices the merged
> ``manual/manual.md`` into per-area sub-manuals under
> ``manual/parts/``. Each ``gen_*`` build task reads only the slice
> relevant to its owned surface, so the executor sees a focused brief
> instead of the full storefront manual every iteration.

---

## 1. Overview

`merge_manual_prose` produces a single canonical ``manual/manual.md``
with eleven H2 sections (Overview, Site shell, Homepage, Collections &
navigation, Product page, Cart, Search, Internationalization, Floating
UX, Policy & info pages, UX Patterns Summary). Today every executor
task reads that whole file. With the prompt loosened to preserve seed
detail (sibling change in `merge_manual_prose.md`), the manual will
grow to 400-700 lines and the per-task signal-to-noise ratio drops.

This spec adds one pure-filesystem step,
``split_manual_parts``, that maps the merged H2 sections onto six
per-area sub-manuals and writes them to ``manual/parts/``. The
build planner and executor prompts are updated to reference the
sub-manual paths so each task reads only the area it owns.

This spec also retires the ``consolidate`` build task: its cleanup
remit is folded into a renamed ``visual_fix`` task that ships with
the new 8-task canonical block.

---

## 2. Terminology

- **Merged manual** — ``manual/manual.md``, the multi-seed prose
  output of `merge_manual_prose` (or single-seed copy of
  `copy_seed_manual`).
- **Sub-manual** — one of six area-scoped views of the merged
  manual: ``homepage.md``, ``navigation.md``, ``product.md``,
  ``collections.md``, ``cart_and_search.md``, ``info_pages.md``.
- **Section** — one H2 block in the merged manual (heading + body
  up to the next ``## `` heading).
- **Routing map** — the static dict that names which sub-manuals
  each canonical H2 section belongs to.

---

## 3. Current Status

- `merge_manual_prose`
  (`packages/shop_arena/src/shop_gen/manual_merge/prose.py`) emits
  ``manual/manual.md`` with the 11 canonical H2 sections.
- `_parse_manual_sections` (private to ``prose.py``) already H2-splits
  a manual body for the merge loop. No public helper exposes the same
  capability.
- Build planner (`build/prompts/planner.md`) emits a 9-task list with
  ``visual_polish`` + ``consolidate``. Executor (`build/prompts/execute.md`)
  tells every task to read ``artifact/manual/manual.md``.
- Build orchestrator (`build/loop.py`) deterministically appends a
  ``consolidate`` bullet via `consolidate.ensure_consolidate_task` if
  the planner forgot one, and re-invokes the harness so the executor
  picks it.
- The 9-task pattern has produced confused executor behavior: tasks
  that read 600 lines to extract the 30 lines that scope their slice;
  ``consolidate`` taking on either too little or far too much. The
  recent ``mock_cookware`` run jumped to final_eval with five tasks
  unchecked when ``gen_product`` ended without marking its checkbox.

---

## 4. Desired Status

### 4.1 I/O contract

Inputs (relative to ``ctx.out_dir``):

- ``manual/manual.md`` — produced by `merge_manual_prose` or
  `copy_seed_manual`.

Outputs:

- ``manual/parts/homepage.md``
- ``manual/parts/navigation.md``
- ``manual/parts/product.md``
- ``manual/parts/collections.md``
- ``manual/parts/cart_and_search.md``
- ``manual/parts/info_pages.md``

Each sub-manual has a single H1 line ``# Sub-Manual — <area>`` and
zero or more H2 sections in canonical order. Empty sub-manuals are
still written (as a one-line H1 with a placeholder body) so
downstream consumers do not branch on existence.

### 4.2 Success criteria

- After running ``split_manual_parts``, all six sub-manual files
  exist and the union of their H2 sections is exactly the set of
  canonical H2 sections present in the merged manual that have at
  least one routing target. Sections in {Overview, UX Patterns
  Summary} stay in the full manual only.
- Validation: if the merged manual contains none of {Homepage,
  Product page, Collections & navigation, Cart, Policy & info pages},
  the step raises ``ValueError`` (the merge regressed; better to
  fail loudly than to write empty parts).
- Build planner emits exactly 8 canonical tasks ending in
  ``visual_fix``.
- Each ``gen_*`` task reads its sub-manual; ``gen_theme`` and
  ``visual_fix`` read the full merged manual.
- The build pipeline no longer auto-appends ``consolidate``;
  ``visual_fix`` is the cross-cutting cleanup task and is part of the
  canonical set.

---

## 5. Proposal

### 5.1 Architecture

`split_manual_parts` is a pure-filesystem step (no LLM call,
no network, no subprocess). It depends on the upstream manual
producer and runs once per shop_gen invocation.

```
merge_capabilities ─┐
                    ├─ merge_manual_prose ─ split_manual_parts ─ (synth_*)
copy_seed_manual ───┘
                    ╰── (single-seed shortcut also flows into split)
```

### 5.2 Routing map

```
Overview                   → ()
Site shell                 → ("navigation",)
Homepage                   → ("homepage",)
Collections & navigation   → ("collections",)
Product page               → ("product",)
Cart                       → ("cart_and_search",)
Search                     → ("cart_and_search",)
Internationalization       → ("navigation",)
Floating UX                → ("homepage",)
Policy & info pages        → ("info_pages",)
UX Patterns Summary        → ()
```

Unknown H2 headings (anything outside the canonical set) route to
no sub-manual; they remain in the full ``manual.md`` only. The
helper logs a single warning per unknown section so a regression in
the merge prompt surfaces in the run log.

### 5.3 Step contract

- ``id``: ``split_manual_parts``.
- ``phase``: ``manual_merge``.
- ``inputs``: ``StepInput`` for the upstream producer
  (``merge_manual_prose`` for multi-seed runs, ``copy_seed_manual``
  for single-seed runs).
- ``outputs``: the six sub-manual paths.
- ``depends_on``: ``[merge_manual_prose]`` or ``[copy_seed_manual]``
  depending on the branch.
- ``version``: 1.

### 5.4 Build prompt changes

`build/prompts/planner.md`:

- Replace the canonical 9-task block with the 8-task block:
  ``gen_theme(9), gen_navigation(8), gen_homepage(7),
  gen_collections(6), gen_product(5), gen_cart_search(4),
  gen_info_pages(3), visual_fix(2)``.
- ``visual_fix`` brief: "fix leftover ``[!]`` task issues and
  cross-page seams (shared-component drift, design-token drift,
  broken inter-page links, deferred verifier feedback)".
- §1 ("Light read budget"): point at ``artifact/manual/manual.md``
  for shop-level scope and ``artifact/manual/parts/<area>.md`` for
  per-task scope.
- §2 / §3 references to ``consolidate`` and ``visual_polish``
  removed.

`build/prompts/execute.md`:

- §2 reading list: each ``gen_*`` task reads
  ``artifact/manual/parts/<area>.md``; ``gen_theme`` and
  ``visual_fix`` read ``artifact/manual/manual.md``.
- §3 owned-slice table loses the ``consolidate`` row, gains a
  ``visual_fix`` row that allows cross-slice cleanup.
- Sub-manual mapping (informative, also reproduced in the executor
  table):

  | Task               | Reads                                      |
  | ------------------ | ------------------------------------------ |
  | ``gen_theme``      | ``artifact/manual/manual.md`` (full)        |
  | ``gen_navigation`` | ``artifact/manual/parts/navigation.md``     |
  | ``gen_homepage``   | ``artifact/manual/parts/homepage.md``       |
  | ``gen_collections``| ``artifact/manual/parts/collections.md``    |
  | ``gen_product``    | ``artifact/manual/parts/product.md``        |
  | ``gen_cart_search``| ``artifact/manual/parts/cart_and_search.md``|
  | ``gen_info_pages`` | ``artifact/manual/parts/info_pages.md``     |
  | ``visual_fix``     | ``artifact/manual/manual.md`` (full)        |

### 5.5 Removal of the consolidate fallback

`build/loop.py` no longer calls `ensure_consolidate_task` after the
harness returns. ``consolidate.py`` and
``prompts/consolidate_execute.md`` are deleted. The 8-task list is
the entire canonical contract; ``visual_fix`` carries the cleanup
remit.

---

## 6. Alternative

**LLM-driven split.** Reject. The merge step already costs a
per-section LLM call; a second LLM pass for routing is wasteful when
the canonical section set is fully enumerable and the routing
deterministic. Programmatic regex split is < 100 lines of pure
Python with no external dependency.

**Sub-manuals as views in code (no on-disk file).** Reject. The
executor is an external agent reading files at runtime; in-memory
views do not help. On-disk files also let humans inspect what each
task saw.

**Fold ``visual_fix`` into the existing ``visual_polish``
without renaming.** Reject. The legacy ``visual_polish`` brief is
purely typographic ("layout / spacing / responsive"). ``visual_fix``
explicitly absorbs the consolidate cleanup remit; the rename signals
the broader scope.

---

## 7. Milestones

- **M1 — Spec sign-off.** This document.
- **M2 — Implementation.**
  - `split_manual_into_parts` helper + `SplitManualPartsStep` under
    `manual_merge/split.py`.
  - Pipeline registration (multi-seed + single-seed).
  - Planner + executor prompt edits.
  - `consolidate.py` + `consolidate_execute.md` removed; `build/loop.py`
    cleanup.
- **M3 — Tests.**
  - Unit tests for `split_manual_into_parts` (routing map coverage,
    validation, ordering).
  - Update `test_loop.py` for the build orchestrator (drop
    consolidate-fallback case).
- **M4 — End-to-end verification.** Re-run
  ``mock_cookware`` from clean run dirs; confirm the planner emits 8
  tasks and each task brief references its sub-manual.

---

## 8. Appendix

### 8.1 Public surface (informative)

```python
from shop_gen.manual_merge import (
    SplitManualPartsStep,
    split_manual_into_parts,
)


parts: dict[str, str] = split_manual_into_parts(manual_text)
# parts.keys() == {"homepage", "navigation", "product",
#                  "collections", "cart_and_search", "info_pages"}
```

### 8.2 References

- `docs/specs/shop_arena/shop_gen.md` §5.2 — Phase 1 manual merge.
- `docs/specs/shop_arena/shop_gen.md` §5.5 — Phase 4 build harness loop.
- `packages/shop_arena/src/shop_gen/manual_merge/prose.py` —
  `_CANONICAL_SECTIONS`, `_parse_manual_sections`.
- `packages/shop_arena/src/shop_gen/build/prompts/planner.md` —
  current 9-task canonical block.

### 8.3 Out of scope

- Changes to the merged-capabilities schema or its merge logic.
- Visual sweep timeout / Playwright session isolation.
- Verifier dispatch or feedback rendering.
