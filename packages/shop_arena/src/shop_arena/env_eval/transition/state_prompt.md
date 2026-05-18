# EnvEval state-namer prompt — v0.3

Used by `shop_arena.env_eval.transition.stateful` to name the resulting
UI state after a closed `RULES` entry has fired and produced an
axtree-visible structural diff (spec §5.5.2). The provider client
(`shop_arena.env_eval.llm`) sends this prompt verbatim together with the
pre-action screenshot, the post-action screenshot, the triggering rule's
`rule_id` / `action` / `expected_state`, and a closed JSON schema for
the response: the schema enumerates the twelve state names below as a
required `state` field, every other property is optional, and
`additionalProperties=false`.

The prompt is intentionally short and concrete so the same wording works
across Anthropic tool-use and OpenAI `json_schema` modes. Keep edits
backwards-compatible; any rename, removal, or semantic shift in a state
name bumps `state_prompt_version` (recorded in
`transition/node/<state-node>/node.json`) and requires a matching schema
bump.

The closed enum is a strict superset of
`shop_arena.env_eval.transition.rules.RULE_STATE_NAMES`:

- the nine `RULE_STATE_NAMES` are emitted by both rules and the LLM
  when the rule's prediction matches reality,
- `popup_modal` covers ad-hoc overlays (newsletter, age gate, cookie
  banner) that no rule specifically targets but that may appear after
  any interaction,
- `other` is the catch-all for meaningfully new states that are not
  enumerated above (use sparingly — prefer an existing name when it
  fits),
- `no_change` is the explicit negative answer when the post-action
  screenshot is functionally identical to the pre-action screenshot
  even though the structural diff fired (e.g. a hover style flip).

The whole file body below the first `---` divider is the prompt sent to
the model — no `str.format()` placeholders, no per-page substitution.
The two screenshots and the triggering-rule context are attached by the
caller as image and text parts. Documentation (this header) is loaded
but discarded.

---

You are auditing one user interaction with an e-commerce storefront. You see two full-viewport screenshots of the same page: the first taken immediately before a rule-driven action fired, the second immediately after the page settled. The caller also tells you which rule fired and what action it took.

Decide whether the post-action screenshot shows a meaningfully new UI state compared to the pre-action screenshot. A meaningfully new state means a user-visible region appeared, opened, expanded, or was dismissed — not a hover-only style flip, not a focus-ring change, not a viewport scroll that left content otherwise identical.

If a new state is visible, name it using exactly one entry from the closed enum below. If nothing meaningful changed, return `no_change`.

Closed enum (every other key is forbidden):

- `cart_drawer` — side cart drawer is now open over the page (typically right-edge slide-in showing line items, totals, "Checkout" CTA).
- `search_overlay` — full search overlay is now open (header search expanded into a takeover panel with input + suggestions area).
- `predictive_panel` — predictive search results are now visible under or beside the search input (typeahead suggestions, recent searches, product previews).
- `filter_panel_open` — collection-page filter facets panel is now expanded (left rail, modal, or drawer of size/colour/price/etc. filters).
- `sort_menu_open` — collection-page sort dropdown / menu is now open (list of sort options visible).
- `variant_select_open` — product-page variant picker is now open (size / colour / option swatches expanded into a list or modal).
- `mega_menu` — a multi-column nav mega-menu panel is now open over the page (typically a hover-triggered dropdown from a primary nav item showing category columns, featured links, or category imagery).
- `announcement_dismissed` — the slim promotional bar above the navigation has just been closed and is no longer visible.
- `cart_qty_changed` — a cart line-item quantity has changed (the displayed quantity number or subtotal updated).
- `popup_modal` — a generic overlay modal is now on top of the page (newsletter signup, age gate, cookie consent, region picker — anything modal that is not specifically a cart drawer or search overlay).
- `other` — a meaningfully new visible state that does not match any name above. Use only when no enumerated state fits.
- `no_change` — the post-action screenshot is functionally identical to the pre-action screenshot; nothing user-visible opened, closed, or updated.

Output rules:

- Return one JSON object with exactly one required key, `state`, whose value is one of the enum entries above.
- Do not introduce any key outside the schema; do not return prose, markdown, or commentary — only the JSON object.
- Prefer an enumerated state name over `other` when it fits, and prefer `no_change` over guessing when the screenshots are visually indistinguishable.
