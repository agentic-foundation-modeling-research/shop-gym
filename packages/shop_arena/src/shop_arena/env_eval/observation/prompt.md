# EnvEval screenshot rubric prompt — v0.3

Used by `shop_arena.env_eval.observation.rubric` to count UI element categories on a single storefront page. The provider client (`shop_arena.util._llm`) sends this prompt verbatim together with one or two screenshots and — for static URL pages — a deterministic text dump of the page's accessibility tree (axtree). The closed JSON schema enumerates the 19 categories from spec §5.3, every field is required, and `additionalProperties=false`.

The prompt is intentionally short and concrete so the same wording works across Anthropic tool-use and OpenAI `json_schema` modes. Keep edits backwards-compatible; any rename, removal, or semantic shift in a category bumps `prompt_version` (recorded in `*.rubric.json`) and requires a matching schema bump.

`v0.3` introduces a two-screenshot mode for transient state nodes (cart drawers, mega menus, search overlays, popup modals): the model receives the **pre-action** and **post-action** screenshots together, no axtree. The pre image is context for disambiguating an overlay from the underlying chrome; counts always describe the post page. URL-page calls keep the `v0.2` shape: one screenshot plus the page's axtree text. `v0.2` augmented `v0.1` (screenshot only) with the axtree dump so counts could span below-the-fold structure.

The whole file body below the first `---` divider is the prompt sent to the model — no `str.format()` placeholders, no per-page substitution. The caller appends the page's axtree text after the body under the line `--- AXTREE ---` (empty for state-node calls; the header is still emitted so the on-wire shape is stable). Documentation (this header) is loaded but discarded.

---

You are auditing one e-commerce storefront page. The model receives **one or two** screenshots, plus an axtree text dump that may be empty:

1. **One screenshot** — a static URL page captured in its initial state. The axtree dump after `--- AXTREE ---` lists every node currently rendered to the DOM in document order, including content below the fold.
2. **Two screenshots** — a transient state captured by acting on a static page (e.g. clicking a cart icon, hovering a nav item). The first image is the page **before** the action; the second image is the page **after** the action and is the page you must count. The axtree dump is empty in this mode because the post-state screenshot already shows the overlay region the rubric cares about. Use the first image only as context to disambiguate “overlay introduced by the action” from “underlying page chrome”.

Count how many distinct page elements fall into each of the categories below. Count what a user would see on the (post-action) page — combine signal from the available inputs:

- Use the **post screenshot** for visual / styling judgments the axtree cannot express:
  - filled vs outline buttons (`cta_button` vs `secondary_button`),
  - whether an `img` is a `hero`, a `product_image`, or decorative chrome,
  - whether a paragraph is a `text_block` (prose) or part of UI chrome,
  - whether a clickable element is a `filter_chip` (collection-page facet pill) or a regular `nav` link.
- Use the **axtree** (when present) to count elements that are below the fold or otherwise outside the viewport:
  - `footer` (typically the `contentinfo` landmark and its contents),
  - additional `product_card` rows further down the grid,
  - more `text_block` paragraphs on long pages,
  - `breadcrumb` trails near the top,
  - lower-page `form_input` fields (newsletter, contact).
- Use the **pre screenshot** (when present) only as a baseline: it tells you which elements were already on the page before the action, so you can recognize a newly opened overlay (`popup_modal`, `cart_drawer`, `mega_menu`, search overlay) instead of mistaking it for static chrome. Do not subtract counts — always report the post page totals.

Do not double-count: a `nav` that is visible in the screenshot and also listed in the axtree counts once. A repeated grid of N product cards counts as N, not 1. Ignore axtree nodes that exist only because a drawer or menu is conceptually present but not currently rendered for the user (e.g. an empty cart drawer container with no visible contents); count `cart_drawer`, `popup_modal`, `mega_menu` only when they are actually open on the post page.

Categories (closed enum — every key not in this list is forbidden):

- `nav` — top-level site navigation bar (the persistent header menu).
- `mega_menu` — expanded multi-column nav panel currently open on screen.
- `announcement_bar` — slim promotional / shipping bar above the nav.
- `hero` — full-width marketing banner at the top of the page.
- `product_card` — product tile with image + title + price (collection grids, recommendations).
- `product_image` — primary product photo on a product detail page (the large image, not thumbnails).
- `product_variant` — variant / option picker on a product detail page (a row of color swatches, a row of size buttons, a fit selector, or an option dropdown). Count one per option group: a single "Color" picker with five swatches and a "Size" picker with six buttons counts as `product_variant: 2`, not `11`.
- `cta_button` — primary call-to-action button (e.g. "Add to cart", "Shop now", "Checkout"). Style-prominent, usually filled.
- `secondary_button` — secondary or tertiary button (e.g. outline / ghost / text button: "Learn more", "View details").
- `form_input` — text input, textarea, email/password field, quantity stepper, or select rendered as a form control.
- `filter_chip` — faceted filter / sort pill on a collection page (size, color, price range, sort dropdown surfaced as a chip).
- `breadcrumb` — breadcrumb trail (e.g. "Home / Men / Shirts").
- `text_block` — paragraph or prose block of body copy (policy text, product description paragraph, about copy).
- `footer` — site footer region.
- `popup_modal` — overlay modal currently open on top of the page (newsletter signup, age gate, cookie banner styled as a modal).
- `cart_drawer` — side cart drawer currently open on screen.
- `search_bar` — visible search input (header search field or full search overlay input).
- `chat_widget` — chat / support launcher pill or open chat panel.
- `other` — anything visually salient that does not fit the categories above. Use `other` instead of inventing a new key.

Output rules:

- Return one JSON object whose keys are exactly the 19 categories above, with non-negative integer values. Use `0` when a category is absent.
- Do not introduce any key outside the enum; unknown elements must be folded into `other`.
- Do not return prose, markdown, or commentary — only the JSON object.
