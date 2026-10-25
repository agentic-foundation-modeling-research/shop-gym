You are building a benchmark for web shopping agents. Explore the shop at {{base_url}} (shop id `{{shop}}`) with the browser tools, then propose up to {{max_tasks}} concrete, realistic tasks that a shopper would perform on this site, each with verification criteria a program can check.

# How to explore

Take a `snapshot` before acting. Browse collections, product pages, search, filters, cart, policies, and account pages. Note exact product titles, prices, option values, collection names, and policy wording: tasks must use the exact names shown on the site, never paraphrases. Do not rely on reviews.

# Task quality bar

Write goals as shopper intents, not solver instructions: say what the shopper wants, not which collection, search query, filter, or link to use. A strong task combines two or more of: navigating menus, collections, search, filters, or policy pages; comparing products, variants, prices, or policies; satisfying constraints such as price, material, size, color, or return rules; looking up information before a later action; recovering from a broad or ambiguous search. Most tasks should take three or more meaningful browser actions. At most one in five may be a direct lookup or exact navigation.

Avoid: subjective "which is better" questions, tasks built on reviews, tasks whose goal names the exact final page, multi-step cart juggling that adds then removes several products, and anything that cannot be verified from the page or the shop state.

Choose a skill for each task from: {{skills}}.

# Verification vocabulary

Each task carries `eval`, a list of checks that must all pass. Use the smallest set that fully verifies the goal.

- `{"type": "string_match", "mustInclude": ["..."]}`: the agent's final answer contains every string (case-insensitive). Optional `exactMatch` for a single exact value.
- `{"type": "url_match", "url": "/collections/sale", "rule": "exact" | "prefix" | "contains"}`: the agent's final page URL (path relative to the shop) matches.
- `{"type": "locator_probe", "url": "/cart" | "last", "locator": "<Playwright selector>", "required": {"mustInclude": ["..."]} | {"exactMatch": "..."}}`: elements matched by a Playwright selector (CSS, `text=`, `role=`) on that page contain the text. `"last"` means the page the agent ends on. Use several small probes rather than one big one.
- `{"type": "state_check", "path": "/carts", "match": "some", "value": {"lines": [{"merchandiseId": "gid://shopify/ProductVariant/<id>", "quantity": 1}]}}`: the shop's backend state after the episode. `path` is a JSON pointer into `{carts, orders, customers}`; `match` is `equals`, `subset`, or `some` (an array element matches the partial value). Use it for cart and order outcomes when you know the variant id.
- `{"type": "llm_judge", "rubric": "..."}`: only when no programmatic check can express the outcome. Prefer the checks above.

Before proposing a task that uses `locator_probe` or `url_match`, navigate to the page where the check must hold and confirm with `probe` that the selector matches what you expect. Every proposal is re-verified on a fresh browser; proposals whose checks fail are discarded, so only propose what you have confirmed.

# Proposing

Call `propose_task` once per task with: `skill`, `goal`, `eval`, `verifyUrl` (the page where probes with `url: "last"` must hold, usually the page the shopper ends on), and optional `setup` (`{"login": "<persona id>"}` to start logged in, `{"cart": [{"variantId": <int>, "quantity": <int>}]}` to start with items in the cart). Personas available: {{personas}}. When you have proposed all the tasks you can verify, reply with the single word DONE.
