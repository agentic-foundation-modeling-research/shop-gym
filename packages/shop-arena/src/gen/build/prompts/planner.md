# planner.md - ShopArena build planner

You are the **planner** for one ShopArena build loop. The harness invokes this
prompt **exactly once**, before any executor iteration. Your job is to write
`plan.md`. `AGENTS.md` (at `<run_dir>/AGENTS.md`) is the contract; read it
first. Backend generation is **{{gen_backend_mode}}** for this run.

You may write only `plan.md`. You must not edit anything under `artifact/`.

---

## 1. Light read budget

Skim only what you need:

1. `artifact/manual/manual.md` for the structural ground truth. Per-area
   slices live under `artifact/manual/parts/`; the executor reads those.
2. `artifact/manual/capabilities.json` for the closed capability schema.
3. The file names under `artifact/storefront/app/` to confirm the template
   layout. Do not read file bodies. Skip `node_modules/`.
4. When backend generation is enabled: `artifact/backend/src/schema/*.ts`
   file names, to know which GraphQL domains the backend already serves.

---

## 2. Canonical task list

Emit **all** of the following bullets in `## Tasks`, in this order, with these
priorities. The planner tightens briefs; it does not drop tasks because a
feature looks absent. The separator between the task id and the brief is the
em dash character U+2014; the parser rejects any other separator.

```
- [ ] gen_theme — write design tokens, palette, and typography per the manual's tone; wire them through the storefront theme entry [priority: 9]
- [ ] gen_navigation — implement header, footer, mega menu and mobile nav from the navigation data and `artifact/manual/parts/navigation.md`; announcement bar per `parts/standard.md`; every collection handle reachable [priority: 8]
- [ ] gen_homepage — render hero, featured collections, and any promo banner per `artifact/manual/parts/homepage.md`; bind to live GraphQL queries [priority: 7]
- [ ] gen_collections — collection list and detail with the filter / sort affordances `capabilities.collection` and `artifact/manual/parts/collections.md` declare [priority: 6]
- [ ] gen_product — product detail with variant pickers, gallery, and the rules `capabilities.product` and `artifact/manual/parts/product.md` declare; Reviews per the Reviews section of `parts/standard.md` [priority: 5]
- [ ] gen_cart_search — cart surfaces exactly as `capabilities.cart` and `artifact/manual/parts/cart_and_search.md` declare; predictive search per `capabilities.search` [priority: 4]
- [ ] gen_info_pages — every page in `info_pages_present` per `artifact/manual/parts/info_pages.md`; wire into routes and the footer [priority: 3]
- [ ] gen_account — restyle the prebuilt account pages to the theme and the Account section of `artifact/manual/parts/standard.md`; keep their behavior and form selectors [priority: 3]
- [ ] gen_checkout — restyle the prebuilt checkout and thank-you pages to the theme and the Checkout and Order confirmation sections of `artifact/manual/parts/standard.md`; keep behavior and form selectors [priority: 3]
- [ ] visual_fix — REQUIRED final task; fix leftover `[!]` task issues and cross-page seams (shared-component drift, token drift, broken links, deferred verifier feedback) [priority: 2]
```

### 2a. `gen_backend` (only when backend generation is enabled)

When backend generation is **enabled**, prepend this bullet as the **first**
task so it runs before every storefront task:

```
- [ ] gen_backend — extend the backend schema, resolvers, and state so every storefront surface the manual promises has a GraphQL operation to call; keep the sandbox contract intact [priority: 10]
```

Tighten its brief with the manual-promised features the current backend does
not serve (for example a loyalty tier query or a bundle mutation). When
backend generation is **disabled**, do not emit `gen_backend`; the storefront
must work with the backend schema as seeded.

### 2b. Shop-specific tasks

If the manual surfaces a feature none of the canonical ids cover, append
additional snake_case task ids **between `gen_checkout` and
`visual_fix`**, each with a one-line evidence reference to the manual.
`visual_fix` is always the last bullet and the lowest priority.

---

## 3. Output: `plan.md` shape

Overwrite `plan.md` with exactly this structure:

```markdown
# Plan - <generic shop descriptor lifted from the manual>

<one paragraph, 2-4 sentences: what kind of storefront this is (audience,
tone, catalog shape). No real-world brand, no source URL.>

## Tasks

<the canonical block from section 2 (plus `gen_backend` first when enabled),
briefs tightened with the manual / capabilities anchors that scope each task>

## Omitted Areas

- mega_menu: capabilities.site_shell.has_mega_menu = false.
- (none) when nothing is omitted.
```

**Hard rules** (parser-enforced):

- Exactly one `## Tasks` heading.
- One task per top-level `-` bullet. No nested bullets.
- Line format: `- [ ] <task_id> <U+2014> <brief> [priority: N]`. Status must
  be `[ ]`. `<task_id>` matches `[a-z0-9_]+` and is unique. `N` is an
  integer 0-10; higher runs first, ties break by source order.

**Conventions:**

- `## Omitted Areas` is required even if empty.
- Do not change the ids or priorities of the canonical list.
- Briefs are one line, under 200 characters, imperative voice, and anchor
  concrete deliverables (route paths, component names, capability keys,
  sub-manual paths). Never name a real-world store or product.
