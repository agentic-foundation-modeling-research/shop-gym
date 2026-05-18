# `replay_run` fixture

Recorded inputs for `test_evaluate_replay` — a full `evaluate()` pipeline
run with no live browser and no live LLM.

| File | What it captures |
| --- | --- |
| `pages.json` | A `PagesDoc` covering all five buckets (one `not_found` to exercise the closed status path). |
| `axtrees.json` | Per-URL recorded BrowserGym/CDP merged-axtree payloads served by the fake session. |
| `rubric.json` | Per-bucket recorded screenshot-rubric counts (closed `RUBRIC_CATEGORIES`). |
| `expected_metrics.json` | Golden values asserted on the produced `metrics.json`. |

The fixtures are deliberately small: one realistic role/structure per
bucket, just enough to drive the M1 observation, M3 action, and M4 BFS
layers without any live calls. The M5 stateful pass runs but every rule
resolves to `no_target` (the recorded axtrees do not include banner /
main landmark scopes the rule list demands), so `state_node_count == 0`
and the LLM is never called by the state-namer — only the rubric layer
issues vision calls.
