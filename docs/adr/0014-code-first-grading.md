# Benchmark checks are graded by code; the LLM judge is opt-in

v1.0 tasks had only `url_contains` checks, so almost every grade needed an LLM. A task's `eval[]` now uses checks that code can grade: `string_match` on the answer, `url_match`, `locator_probe` (a Playwright selector), and `state_check` on the episode's backend `StateSnapshot`. `llm_judge` is explicit per task and runs last, only for goals that no check can express (for example "find a similar product").

## Consequences

Grading runs inside the episode, before the browser closes, because `locator_probe` needs the page as the agent left it and `state_check` needs that episode's backend state. There is no stage that grades saved episodes later.
