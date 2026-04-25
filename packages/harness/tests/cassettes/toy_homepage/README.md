# `toy_homepage` cassette

Hand-authored toy scenario used by the harness e2e replay tests
(spec §5.6, impl plan T2.5).

## Shape

```
toy_homepage/
├── plan/                 # planner iteration
├── exec-0001/            # executor iteration 1 (selects `homepage`, priority 2)
└── exec-0002/            # executor iteration 2 (selects `product_detail`, priority 1)
```

Each iteration directory matches the spec §5.6 minimal cassette layout:

```
<iter_id>/
├── trajectory.json       # normalized telemetry (replayed verbatim)
├── native.log            # raw runtime stream (informational; copied to iter_dir)
└── workspace_after/
    ├── plan.md           # plan snapshot the iteration leaves behind
    └── artifact/         # evolving workspace surface
```

## Behaviour

`plan/` writes a `plan.md` with two PENDING tasks:

```
- [ ] homepage          [priority: 2]
- [ ] product_detail    [priority: 1]
```

`exec-0001/` runs against the harness-selected `homepage` task (highest
priority) and flips it to `[x]`. `exec-0002/` runs against
`product_detail` and flips it to `[x]`. The run ends `completed`.

Trajectories use `runtime: "replay"` and a placeholder
`prompt_sha256`; the harness loop normalises the digest from the live
prompt before persisting telemetry, so the placeholder is never visible
in a replayed run's `iters/<iter_id>/trajectory.json`.
