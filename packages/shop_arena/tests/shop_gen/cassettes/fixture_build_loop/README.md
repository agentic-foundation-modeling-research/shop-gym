# `fixture_build_loop` cassette

Hand-crafted replay cassette that drives the Phase 4 build loop
(`shop_gen.build.loop.RunBuildHarnessLoopStep`) through the four
canonical tasks documented in `docs/specs/shop_arena/shop_gen.md` §5.5:
`gen_theme`, `gen_navigation`, `gen_homepage`, and the mandatory
`consolidate` cleanup pass.

It is consumed by `tests/shop_gen/test_build_loop_replay.py` (T5.9) so
the loop driver is exercised end-to-end deterministically without any
LLM, sidecar subprocess, or network call.

## Shape

```
fixture_build_loop/
├── plan/                               # planner emits the four-task plan
│   ├── trajectory.json
│   └── workspace_after/plan.md
├── exec-0001/                          # selects gen_theme
│   ├── trajectory.json
│   └── workspace_after/
│       ├── plan.md                     # gen_theme [x], rest PENDING
│       └── artifact/hydrogen/app/styles/theme.css
├── exec-0002/                          # selects gen_navigation
│   ├── trajectory.json
│   └── workspace_after/
│       ├── plan.md                     # gen_theme + gen_navigation [x]
│       ├── artifact/hydrogen/app/components/Header.tsx
│       └── artifact/hydrogen/app/components/Footer.tsx
├── exec-0003/                          # selects gen_homepage
│   ├── trajectory.json
│   └── workspace_after/
│       ├── plan.md                     # 3/4 [x]
│       └── artifact/hydrogen/app/routes/_index.tsx
└── exec-0004/                          # selects consolidate
    ├── trajectory.json
    └── workspace_after/
        ├── plan.md                     # all 4 [x]
        └── artifact/hydrogen/CONSOLIDATE.md
```

Each `workspace_after/plan.md` is the **complete** plan snapshot the
harness re-applies after the iteration. Priorities (`gen_theme=4`,
`gen_navigation=3`, `gen_homepage=2`, `consolidate=1`) drive the
executor's `select_next` ordering so the cassette and the harness agree
on which task is in flight every iteration.

The hydrogen mutations under `artifact/hydrogen/` are intentionally
minimal — the cassette demonstrates that the executor's writes survive
the overlay copy and accumulate across iterations. The `Header.tsx`
and `Footer.tsx` deltas additionally exercise the M2/M3 navigation
primitives contract (`<HeaderShell>` + `<NavMenu>` and
`<FooterColumns>` imports respectively) so
`navigation_primitive_usage` (per
`docs/specs/shop_arena/template_navigation_primitives.md` §"Acceptance")
would PASS against the post-build artifact. End-to-end behavioural
coverage (build / tsc / verifiers passing) lands with T5.10.

## Provenance

Synthetic placeholder cassette — not a recording of any real
`shop_gen` build run. Refresh by re-running the live build loop under
`HARNESS_RECORD=1` once the recording infrastructure (T7) lands.
