# Visual Verifier — Implementation Plan

Status: **Spec (draft)** · Version: **0.2**
Spec: [`docs/specs/shop_arena/visual_verifier.md`](../specs/shop_arena/visual_verifier.md)
Target package: `packages/shop_arena` (`shop_gen`)

> Pure task checklist. Behavior comes from the spec; this doc only says
> what to do and in what order. Each task references the spec sections
> that govern it.

---

## Tasks

### M1 · `visual_judge` verifier (per-task, no retry budget, no fan-out)

This milestone lands a working `visual_judge` for **per-task
invocations only** (`gen_homepage`, `gen_product`, …). Two later
milestones extend it: **M2** adds the retry budget; **M5** adds the
`consolidate` page-bucket fan-out and the final-eval visual sweep.

- [x] **T1.0** — `src/shop_gen/build/verifiers/_skills.py`: shared skill-probe helper. Lift `_resolve_playwright_skill_dir` out of `shop_explore.pipeline` into this module (or import-and-re-export). Add `is_playwright_skill_available() -> bool` returning True iff the skill directory resolves AND `<skill_dir>/scripts/pw.js` is a file. Spec §5.5.1. **Check:** unit tests cover (a) skill + `pw.js` present → True, (b) skill dir not resolvable → False, (c) skill dir resolvable but `pw.js` missing → False.

- [x] **T1.1** — `src/shop_gen/build/verifiers/_runtime_call.py`: helper that stages a sub-workspace under a parent dir (`work/prompt.md`, `work/routes.json`, `work/iter/`), invokes `runtime.run_iteration(run_dir=work, iter_dir=work/iter, prompt=…, timeout=…)`, and parses `work/verdict.json` per spec §9.3 (forgiving fenced/bare JSON parser, mirror `_judge.dispatch_judge`). The structured schema includes `verdict`, `score`, `category_scores`, `feedback`, `pages_judged`, and `issues[]` carrying `severity ∈ {critical, major, minor}`. The helper applies the score → verdict coercion rules: `score < pass_threshold` coerces an emitted `pass` to `fail`; any `severity: critical` issue forces `verdict=fail`. Spec §5.2.1, §9.3. **Check:** unit tests cover (a) clean PASS verdict, (b) fenced JSON, (c) malformed JSON → `None`, (d) `score < threshold` + `verdict=pass` → coerced to fail, (e) issue with `severity: critical` + `verdict=pass` → coerced to fail.

- [x] **T1.2** — `src/shop_gen/build/prompts/visual_judge.md`: per-iteration prompt template with slots `{base_url}`, `{task_id}`, `{capabilities_slice}`, `{route_list}`, `{verdict_schema}`, `{prior_feedback_or_empty}`. Bake in the "judge only what you have rendered" instruction (spec §9.2) and the structured-score expectation (`score`, `category_scores`, `severity` per §9.3). Spec §9.2, §9.3. **Check:** all slots load; `load_visual_judge_prompt()` exposed from `shop_gen.build.prompts`; rendered prompt explicitly tells the agent the capabilities slice has been pre-filtered for this task's bucket(s).

- [x] **T1.3** — `src/shop_gen/build/verifiers/_task_routes.py`: 2-layer **task → buckets → (routes, capabilities)** module per spec §5.3 + §9.1. Constants:
  - `TASK_BUCKETS: dict[str, frozenset[str]]` — 8 keys covering the canonical `gen_*` task ids plus `visual_polish` and `consolidate`.
  - `BUCKET_CAPABILITY_KEYS: dict[str, frozenset[str]]` — 6 buckets, capability key globs.

  Functions:
  - `buckets_for_task(task_id) -> frozenset[str]` — B1 prefix match (strip trailing `_redo_\d+$`, look up `TASK_BUCKETS`).
  - `bucket_routes(bucket, data_dir, *, caps) -> tuple[str, ...]` — data-driven from `data/{collections,products,pages}.json`.
  - `routes_for_buckets(buckets, data_dir, *, caps) -> tuple[str, ...]` — sorted union over buckets.
  - `capabilities_for_buckets(buckets, capabilities) -> dict` — `fnmatch` filter, union over buckets.

  Plus a `BucketCaps` dataclass for the per-iteration vs. sweep cap differentiation (§5.6.1). Spec §5.3, §9.1, §5.6.1. **Check:** SC8 fixture: `buckets_for_task("gen_homepage")` returns `frozenset({"homepage"})`; `buckets_for_task("gen_homepage_redo_3")` returns the same; multi-bucket route unions are sorted; unknown task id → empty bucket set; cap differentiation observable.

- [x] **T1.4** — `src/shop_gen/build/verifiers/visual_judge.py`: `VisualJudgeVerifier` class. Constructor:

  ```python
  def __init__(
      self,
      *,
      data_dir: Path,                              # data/*.json source for bucket → routes
      dev_server_factory: DevServerFactory,
      retry_budget: int = 3,
      timeout_s: float = 300.0,
      pass_threshold: float = 7.0,
      applicable_tasks: Iterable[str] | None = None,
  ) -> None: ...
  ```

  `applies_to` mirrors §5.2's default set **excluding `consolidate`** in M1 (added back in M5 alongside the fan-out). `run()` per spec §5.2.1:

  1. Resolve task scope: `buckets_for_task(ctx.selected_task_id)` → `routes` + `cap_keys`; filter `capabilities.json` to the slice (T1.3).
  2. Skip the retry-budget check — lands in M2.
  3. Boot dev server via injected factory.
  4. Stage sub-workspace via T1.1.
  5. **Single** `run_iteration` call (no fan-out — `consolidate` lands in M5).
  6. Parse `verdict.json`; apply score → verdict coercion via T1.1.
  7. Promote screenshots to `iter_dir/checks/verifiers/visual_judge/screenshots/`.
  8. Return `VerifierResult` with `details = {routes, pages_judged, score, category_scores, buckets_run: [<single_bucket>], retry_budget_exhausted: false, prior_fails: 0}`.

  Spec §5.2, §5.2.1, §9.3. **Check:** unit test with stub `AgentRuntime` covers PASS + FAIL paths; missing `verdict.json` → FAIL with diagnostic; dev server torn down on every exit (success and exception); score < threshold coerces pass→fail; critical issue coerces pass→fail; `consolidate` task does not match `applies_to`.

- [x] **T1.5** — Wire `VisualJudgeVerifier` into `default_verifiers_factory` (still hardcoded; M3 makes the set configurable). **Gate construction behind `is_playwright_skill_available()`** (T1.0): on probe failure, log a single WARNING with the install hint (`pnpm add -g pi-playwright`) and **omit** the verifier from the tuple. Insert order: between `quality_judge` and `cross_task_consistency`. Spec §5.2, §5.5, §5.5.1. **Check:** SC7 — request `visual_judge` with skill missing → tuple does not include verifier, exactly one WARNING is emitted; with skill present → verifier appears in the expected slot; rule verifiers always present.

- [x] **T1.6** — Tests with stub `AgentRuntime` writing a deterministic `verdict.json`:
  - **SC1** — PASS leaves `[x]` intact.
  - **SC2** — FAIL rewrites `[x]` → `[~]`.
  - **SC7** — skill-probe failure path (factory omits verifier, one warning logged, loop completes).
  - **SC8** — `gen_homepage` iteration calls `runtime.run_iteration` with a route list of just `("/",)` and a capabilities slice keyed by `homepage` bucket only; capabilities outside the slice never reach the prompt; `gen_homepage_redo_3` produces the same scope (prefix-match coverage).
  - Malformed `verdict.json` → FAIL with diagnostic.
  - Runtime raises → harness ERROR (per dispatch lifecycle).

  **Check:** all six pass under `pytest`.

**M1 acceptance:** SC1, SC2, SC7, SC8 covered; verifier registered behind skill probe; consolidate excluded; no behaviour change to existing rule verifiers.

---

### M2 · Per-task retry budget

- [x] **T2.1** — Sibling-iter scan helper in `_runtime_call.py` (or new `_history.py`): given `run_dir`, `iter_id`, `verifier_name`, `task_id`, return the count of prior `verdict == "fail"` entries against the same task. Skip the current `iter_id`. Spec §5.4. **Check:** unit tests with fixture `iters/exec-0001..0004/checks/verifiers/visual_judge.json` covering count = 0, 1, 3, 5.

- [x] **T2.2** — Wire the budget check into `VisualJudgeVerifier.run` as the second step (after route resolution, before dev-server boot). On overflow: return `Verdict.ADVISORY` with feedback that names the budget + points to prior failed iter dirs; persist `details.retry_budget_exhausted = true` and `details.prior_fails = <count>`. Do **not** boot the dev server, do **not** call the runtime. Spec §5.4. **Check:** unit test under stub runtime — 4th call against a task with 3 prior FAILs returns ADVISORY without invoking the runtime stub (assert call count = 0).

- [ ] **T2.3** — Make `retry_budget` configurable: `ShopGenConfig.visual_retry_budget: int = 3`; threaded through `default_verifiers_factory`. `0` disables the budget. Spec §5.4 + §5.9. **Check:** library round-trip; unit test `visual_retry_budget=0` runs the runtime even after 10 prior FAILs.

- [ ] **T2.4** — CLI flag `--visual-retry-budget <int>` on `cli.py`. Spec §5.9. **Check:** `shop-gen --visual-retry-budget 5 ...` propagates to `VisualJudgeVerifier`.

- [ ] **T2.5** — Tests: SC3 — 4 consecutive FAILs against `gen_homepage` with budget 3 → 4th invocation is ADVISORY with `details.retry_budget_exhausted = true`. **Check:** test green; `runs/build/iters/exec-0004/checks/verifiers/visual_judge.json` records the downgrade.

**M2 acceptance:** SC3 covered; budget knob exposed on CLI + library.

---

### M3 · Configurable LLM-judge set + score / concurrency knobs

- [ ] **T3.1** — `ShopGenConfig.judges: frozenset[str] = frozenset({"visual_judge", "quality_judge", "cross_task_consistency"})`. Validate against the known judge list at config-validation time; unknown names raise. Spec §5.5. **Check:** invalid name in `judges` raises `ValueError` with the offending token.

- [ ] **T3.2** — `default_verifiers_factory(*, out_dir, sidecar, judges, ...) -> tuple[Verifier, ...]`: gate each LLM-judge constructor behind a membership check on `judges`. Rule verifiers always included. The `visual_judge` branch also gates on `is_playwright_skill_available()` (T1.5). Spec §5.5, §5.5.1. **Check:** `judges=frozenset()` returns only the rule verifiers; `judges={"visual_judge"}` includes exactly one LLM judge (when skill present); `judges={"visual_judge"}` + skill missing returns rule verifiers only with one warning.

- [ ] **T3.3** — Thread `judges` through `build/loop.py::run_build_loop` and the step that wraps it. **Check:** library callers can pass `judges={"visual_judge"}` and observe the right tuple.

- [ ] **T3.4** — CLI flag `--judges <comma-list|all|none>` on `cli.py`. Parse `none` → empty set, `all` → full default set, comma-separated → set of tokens. Reject unknown tokens with a CLI-level error. Spec §5.5 + §5.9. **Check:** integration test exercises `--judges visual_judge,quality_judge`, `--judges none`, `--judges all`, `--judges bogus` (rejected).

- [ ] **T3.5** — Tests: SC5 — `--judges visual_judge,quality_judge` registers exactly those two LLM judges (when skill present); `cross_task_consistency` is absent. `--judges none` registers zero LLM judges. **Check:** assert `len(verifier_runs) by name` per case.

- [ ] **T3.6** — Score + concurrency knobs (delta 1 + delta 2):
  - `ShopGenConfig.visual_judge_pass_threshold: float = 7.0` (§9.3 score-coercion threshold)
  - `ShopGenConfig.visual_judge_max_concurrency: int = 3` (§5.2.1 step 5, §5.6 fan-out worker count)
  - CLI: `--visual-judge-pass-threshold <float>`, `--visual-judge-max-concurrency <int>`
  - Threaded through factory → verifier ctor + final-eval sweep driver.

  Spec §4.1, §5.9. **Check:** library + CLI round-trip; verifier emits `score` + `category_scores` in `details`; threshold change observable via stub runtime test (e.g. agent emits `verdict=pass, score=6.0` with threshold 7.0 → coerced to fail).

**M3 acceptance:** SC5 covered; CLI + library knobs in place for `judges`, score threshold, fan-out concurrency.

---

### M4 · Re-introduce `routes_200` + bucket consumers

The 2-layer model was already landed in T1.3 (M1 prereq). M4 wires it
into the second consumer.

- [ ] **T4.1** — Re-introduce `src/shop_gen/build/verifiers/routes_200.py`. The original was pruned in commit `e54c98f`; rebuild against the new bucket axis. Constructor takes `data_dir: Path` + `dev_server_factory`. `applies_to` matches every `gen_*` task. `run()` calls `routes_for_buckets(buckets_for_task(task_id), data_dir)`, hits each route via the dev server, asserts HTTP 2xx. Spec §5.3, §5.8. **Check:** `routes_200` passes against a healthy fixture; FAILs on a 404 route; consumes the same `_task_routes.py` module as `visual_judge`; `gen_homepage_redo_3` resolves to the same routes as `gen_homepage`.

- [ ] **T4.2** — Sample-token resolution for `cart_search`: pick the first product title's first noun-token as the `q=` value. Deterministic per dataset. Spec §9.1. **Check:** unit test against a fixture `products.json` returns a stable token across reruns.

- [ ] **T4.3** — Tests: deterministic ordering of multi-bucket route unions (`visual_polish`, `consolidate`); cap respected per §5.6.1 (per-iteration vs. sweep); `_redo_<n>` task ids resolve to the same routes as the base. **Check:** assert sorted tuple, length within caps, prefix-match coverage for redo flow, sweep `BucketCaps` widens beyond per-iteration.

**M4 acceptance:** one source of truth for task → buckets → routes/capabilities; `routes_200` and `visual_judge` consume the same module.

---

### M5 · `final_eval` visual sweep + page-bucket fan-out

Lands the page-bucket `ThreadPoolExecutor` fan-out for both
`consolidate` (in `visual_judge`) and the final-eval sweep, per
§5.2.1 step 5 + §5.6.

- [ ] **T5.1** — `src/shop_gen/final_eval/visual_sweep.py`: pure driver. Resolves the all-pages page set via `routes_for_buckets(consolidate_buckets, data_dir, caps=SWEEP_CAPS)` with the §5.6.1 wider caps. Stages sub-workspaces under `<out_dir>/visual_eval/work/<bucket>/`. **Page-bucket `ThreadPoolExecutor` fan-out** (`max_workers = visual_judge_max_concurrency`): one `runtime.run_iteration` call per bucket. Per-bucket `verdict.json` + screenshots. Promote screenshots into `<out_dir>/visual_eval/screenshots/<bucket>/<page>/`, write `<out_dir>/visual_eval/report.md`. Spec §5.6, §9.4. **Check:** stub `AgentRuntime` covers a 6-bucket fan-out run; per-bucket sub-iter dirs exist; screenshots land in the right subdirs; `report.md` non-empty; wall-clock scales with longest bucket, not sum.

- [ ] **T5.2** — `src/shop_gen/final_eval/prompts/visual_sweep.md`: visual-sweep prompt body (per-bucket variant of §9.2 — same structured-score schema, same "judge only what you have rendered" instruction; advisory-language verdict per §9.4). Spec §9.4. **Check:** all slots load; `load_visual_sweep_prompt()` exposed; advisory framing distinct from gating `visual_judge` prompt.

- [ ] **T5.3** — `final_eval/step.py` integration: extend `run_final_eval` to run the visual sweep alongside the existing 5-step smoke. Merge per-bucket results: weighted overall via `PAGE_WEIGHTS` (§9.5), averaged `category_scores`, severity-sorted concatenated issues. Write into `final_eval.json` under the `visual` subtree (§4.1) — `verdict`, `score`, `category_scores`, `pages_judged`, `feedback`, `report_path`. Smoke + judge subtrees stay unchanged. Failures (probe miss, runtime crash, parse error) collapse to `visual.error`. Spec §5.6. **Check:** SC6 — `final_eval.json` carries the full `visual.{ok, verdict, score, category_scores, pages_judged, feedback, report_path}` subtree; `<out_dir>/visual_eval/{screenshots,report.md}` exists.

- [ ] **T5.4** — Config knobs: `ShopGenConfig.final_eval_max_collections / .final_eval_products_per_collection / .final_eval_max_pages / .final_eval_visual_timeout_s`. CLI flag `--final-eval-visual-timeout`. These flow into `SWEEP_CAPS: BucketCaps` (T1.3). Spec §5.6.1, §5.9. **Check:** library + CLI round-trip; cap changes observable in resolved sweep route count.

- [ ] **T5.5** — Tests: SC6 (full visual subtree present); SC7 sweep arm (skill probe failure → ERROR captured, `<out_dir>/visual_eval/` not created, run completes). **Check:** both pass under stub runtime.

- [ ] **T5.6** — **Skill probe at sweep entry**. Reuse `is_playwright_skill_available` from T1.0 in `final_eval/visual_sweep.py`. On failure: log single warning, write `visual.error = "playwright skill not available"` into `final_eval.json`, do not create `<out_dir>/visual_eval/`. Spec §5.5.1, §5.6. **Check:** SC7 sweep arm — probe-failure path emits one warning, no empty dirs, run completes.

- [ ] **T5.7** — **`consolidate` page-bucket fan-out** in `VisualJudgeVerifier`. Add `consolidate` back to the default applicability set (M1 had excluded it). Detect multi-bucket invocations (`task_id == "consolidate"` or `len(buckets) > 1` for `visual_polish`). For each bucket, stage `work/iter/<bucket>/` and submit one `run_iteration` call to a `ThreadPoolExecutor(max_workers=visual_judge_max_concurrency)`. Merge per-bucket `verdict.json` per §5.2.1 step 6: weighted score via `PAGE_WEIGHTS` (§9.5), averaged `category_scores`, severity-sorted concatenated issues. Single bucket FAIL → merged FAIL. Spec §5.2.1 step 5–6, §9.5. **Check:** SC4 — `consolidate` invocation walks every bucket; merged `verdict.json` carries weighted overall score; per-bucket sub-iters exist on disk; bucket FAIL propagates to merged verdict.

**M5 acceptance:** SC4 + SC6 + SC7 (sweep arm) covered; fan-out lands for both consolidate + sweep; `final_eval` output schema bumped.

---

### M6 · Production playwright wiring

- [ ] **T6.1** — Real `DevServerFactory` (`pnpm dev` runner) replacing `_unconfigured_dev_server_factory` in `build/loop.py` and `final_eval/step.py`. Spec §5.2.1, §5.6. **Check:** integration test under a recorded cassette boots the server, waits for readiness, tears down on exit (incl. exception path).

- [ ] **T6.2** — End-to-end visual sub-iter against a real `pi` runtime: a fresh sub-workspace with no `AGENTS.md` / `plan.md` should complete cleanly (the `pi` adapter already supports this — same shape `shop_explore` and the `shop_gen` build executor use). **Check:** sub-iter completes; `iter/native.log` populated; playwright skill available; screenshots written; `verdict.json` parsed.

- [ ] **T6.3** — End-to-end smoke test wiring `visual_judge` and the visual sweep against a real (recorded) hydrogen tree. Spec §5.2 + §5.6. **Check:** at least one PASS and one FAIL captured; screenshots present; `verdict.json` parsed.

**M6 acceptance:** production wiring lands; replay-runtime tests green; `_unconfigured_*` placeholders deleted.

---

### M7 · Release

- [ ] **T7.1** — Update [`docs/specs/shop_arena/shop_gen.md`](../specs/shop_arena/shop_gen.md) §5.5.3 verifier table to add `visual_judge` and reference `visual_verifier.md`. **Check:** cross-link resolves.

- [ ] **T7.2** — Update [`docs/specs/README.md`](../specs/README.md) ShopArena table with the new `visual_verifier.md` row (already listed; bump status). **Check:** spec index lists the new spec + impl plan with current status.

- [ ] **T7.3** — Update spec status badge in [`docs/specs/shop_arena/visual_verifier.md`](../specs/shop_arena/visual_verifier.md) from `Spec (draft)` to `v0.1` once M1–M5 land. **Check:** badge accurate.

- [ ] **T7.4** — `packages/shop_arena/src/shop_gen/_version.py`: bump to the next minor (e.g. `0.2.0`). **Check:** `from shop_gen import __version__` returns the new version.

**M7 acceptance:** spec marked v0.1; cross-references in place.

---

## Milestones (summary)

| Milestone | Tasks       | Gate                                                                                  |
| --------- | ----------- | ------------------------------------------------------------------------------------- |
| M1        | T1.0–T1.6   | per-task `visual_judge` registered behind skill probe; SC1, SC2, SC7, SC8             |
| M2        | T2.1–T2.5   | per-task retry budget; SC3                                                            |
| M3        | T3.1–T3.6   | configurable judge set + score/concurrency knobs; SC5                                 |
| M4        | T4.1–T4.3   | `routes_200` re-introduced; bucket axis shared with `visual_judge`                    |
| M5        | T5.1–T5.7   | sweep + page-bucket fan-out for both `consolidate` and final-eval; SC4, SC6, SC7      |
| M6        | T6.1–T6.3   | real `pnpm dev` + `pi` runtime; placeholders deleted                                  |
| M7        | T7.1–T7.4   | spec promoted; v0.2 of `shop_gen` tagged                                              |

---

## Notes

- **Sub-workspace immutability.** The verifier writes inside the harness-owned `iters/` tree; this is fine — verifier dispatch already writes there (`<name>.json`, `feedback.md`). Do **not** write under the seed-protected `artifact/` subtree from inside the verifier (that's the parent loop's domain). Spec §7.3.

- **Replay-runtime tests** must use a stub `AgentRuntime` (no real playwright skill available); the cassette format is unchanged. Spec §7.5.

- **Screenshot promotion.** Hard-link when possible (same filesystem), fall back to copy. Keep originals under `iter/screenshots/` for replay parity.

- **Order of LLM judges in `default_verifiers_factory`.** Insert `visual_judge` between `quality_judge` and `cross_task_consistency` (matches §5.2 spec table ordering and the expected `feedback.md` ordering).

- **Skill probe is platform-level.** `is_playwright_skill_available` (T1.0) does not depend on the runtime instance — it queries the JS package manager's global root, which is the same for `pi`, `claude_code`, and `replay`. Replay-runtime tests therefore behave the same as production: skill installed → verifier runs with stub runtime per §7 Q5; not installed → omitted. CI runners that deliberately exclude the skill exercise the omit-and-warn path.

- **B1 prefix match on task ids.** `buckets_for_task` strips a trailing `_redo_<n>` suffix; this makes the redo flow (`gen_homepage_redo_3`) automatic without enumerating every redo variant in `TASK_BUCKETS`. Spec §5.3 layer 1.

- **Consolidate appears twice in M-tracking.** It's *excluded* from the M1 default applicability set (single-call fan-out unsupported until M5) and *added back* in T5.7 alongside the `ThreadPoolExecutor` fan-out. M2 (retry budget) and M3 (judge-set switch) work on whatever applicability set is current at the time they land.

- **Shared `BucketCaps` config flow.** Per-iteration `consolidate` uses tight caps (1 collection, 1 product); the final-eval sweep uses §5.6.1 wider caps. Both flow through the same `routes_for_buckets(..., caps=...)` signature in `_task_routes.py` (T1.3). The wiring is: `ShopGenConfig.final_eval_*` (T5.4) → `SWEEP_CAPS: BucketCaps` → `routes_for_buckets`. Per-iteration caps are constants in the verifier module.
