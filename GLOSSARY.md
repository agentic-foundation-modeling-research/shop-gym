# ShopGym

ShopGym makes safe, deterministic copies of online shops and uses them to build and run benchmarks for shopping web agents. Work flows from a Live storefront to a Shop Manual, then to a SandboxShop, then to a Benchmark and its scores.

## Language

### Components and pipeline

**ShopArena**:
The environment factory of ShopGym. It turns a Live storefront into a Shop Manual, and one or more Shop Manuals into a SandboxShop.

**ShopBackend**:
The GraphQL server that serves one Dataset through a subset of the Shopify Storefront API and keeps separate shop state for each Episode. Every SandboxShop runs its own copy of it.
_Avoid_: SandboxShop instance, mock-api

**ShopGuru**:
The benchmark pipeline. It makes Tasks for one SandboxShop, runs an AgentUnderTest on each Task in an Episode, grades the Episodes, and adds up the scores.

**Harness**:
The runtime-agnostic plan-then-execute engine that drives an agent through Iterations in a run directory that holds a `plan.md`. It owns run state, protocol checks, and resume, but has no prompts, tools, or domain knowledge of its own.

**Step**:
One named unit of work in the explore or gen pipeline, with declared input paths and declared output paths. A complete Step is skipped on the next run unless `--from` forces it.
_Avoid_: node, phase

### ShopArena

**Live storefront**:
A real, public online store on the web, as a buyer sees it before logging in. It is the input to Storefront exploration, and no output may name it.
_Avoid_: real shop, source storefront, original shop

**Storefront exploration**:
The ShopArena process (`shopgym explore`) that browses one Live storefront and writes one Shop Manual.
_Avoid_: ShopExplore, explore (alone)

**Shop Manual**:
The anonymized description of one storefront's structure, features, and UX: prose in `manual.md`, Capabilities in `capabilities.json`, and catalog statistics in `stats.json`.
_Avoid_: manual (alone), seed manual, Seed Shop Manual

**Capability**:
One structured, schema-checked fact about one storefront feature, for example the cart type or the list of collection filters.

**Anonymization**:
The rule that a Shop Manual describes only structure and UX patterns, and contains no brand, domain, product name, or other text that identifies the Live storefront.

**Shop generation**:
The ShopArena process (`shopgym gen`) that turns one or more Shop Manuals into a SandboxShop.
_Avoid_: ShopGen

**SandboxShop**:
A self-contained, deterministic, hostable shop: a Dataset, a storefront, its own backend copy, and a Merged manual. Shop generation makes it, and `shopgym host` runs it.
_Avoid_: sandbox shop, generated shop, published shop, mock shop

**Shop manifest**:
The `shop.json` file that marks a directory as a SandboxShop that is ready to host. It records the templates used, whether the backend was generated, and the final status of the Build loop.
_Avoid_: publish manifest

**Merged manual**:
The single Shop Manual in a SandboxShop's `manual/` directory. Shop generation merges it from all input Shop Manuals, or copies it when there is only one.
_Avoid_: composite manual

**Sub-manual**:
One of the area files in a SandboxShop's `manual/parts/`, so that each build task reads only its own area. Six are cut from the Merged manual (homepage, navigation, product, collections, cart and search, info pages); the seventh is the Standard sub-manual.
_Avoid_: manual part, part

**Standard sub-manual**:
The one checked-in Sub-manual that Shop generation adds to every SandboxShop as `manual/parts/standard.md`. It describes, by the Shopify standard, the pages that Storefront exploration cannot observe (account, checkout, and order confirmation), the rules for the announcement bar and for product reviews, and the behavior that the backend supports.
_Avoid_: standard manual, account manual

**Storefront template**:
The React Router SSR storefront app that every SandboxShop starts from. The build agent edits a copy of it, never the template itself.

**Backend template**:
The ShopBackend package used as the starting backend of every SandboxShop. Each shop gets its own copy, and the build agent may extend that copy only in `--gen-backend` mode.

**Build loop**:
The Harness run inside Shop generation in which a build agent turns the template copies into the shop's own storefront (and, in `--gen-backend` mode, its own backend). Verifiers gate every build task.
_Avoid_: build phase, Build Harness Loop

**Sidecar**:
A child process that serves a backend copy or a built storefront during Shop generation, so that the build agent and the Verifiers use the same endpoints the finished shop will have.
_Avoid_: hosting sidecar

**Final eval**:
The advisory check of a built shop after the Build loop: a visual sweep that screenshots and judges the canonical pages, and a functional sweep that runs a fixed sign-up-to-order script. Its result never fails Shop generation.

### ShopBackend

**Dataset**:
The read-only JSON files and images under a SandboxShop's `data/` directory: store, catalog, Reviews, content, policies, customers, orders, and commerce settings (shipping methods, payment methods, tax, the free-shipping threshold, and Discount codes). The backend loads it and never changes it.
_Avoid_: shop data, catalog (the catalog is only one part of it)

**Discount code**:
A code in the Dataset's commerce settings that lowers the price of a cart: a percent or a fixed amount off the merchandise subtotal, or free shipping, with an optional minimum merchandise subtotal. A cart holds at most one code, matched in any case; the code applies only while the cart meets the minimum, and the order records the code and the discount amount.
_Avoid_: coupon, promo code

**Persona**:
A customer account in the Dataset's `customers.json`, with an email and password that a Task's setup can log in with, saved addresses, and seeded orders in `orders.json` that its order history shows.
_Avoid_: seeded customer

**Review**:
A read-only opinion of one product in the Dataset's optional `reviews.json`: the variant bought, a rating from 1 to 5, a title, a text, the reviewer's first name and last initial, a date, a Verified Buyer flag, and a helpful count. The product's `reviews.rating` and `reviews.rating_count` metafields are computed from its Reviews. Shoppers read and sort Reviews; they cannot write or vote on them.
_Avoid_: rating (one field of a Review), testimonial

**Episode**:
One attempt by one agent at one Task on one SandboxShop. The backend keeps the state of each Episode (cart, login, orders) apart from all others, by the episode id in the `x-shopgym-episode` header.
_Avoid_: session, run

**StateSnapshot**:
The grader-facing JSON view of the backend state of one Episode: customers, sessions, carts, orders, and inventory.

**Control API**:
The plain HTTP routes under `/__shopgym/episodes/<id>` that reset, read, and delete the backend state of one Episode.

**Sandbox contract**:
The part of the Backend template that no SandboxShop may change: Dataset loading, Episode isolation, the Control API, the StateSnapshot shape, and the contract tests that check them.
_Avoid_: read-only backend paths, template-owned files

### ShopGuru

**Task**:
One benchmark item: a natural-language goal, an optional setup (a Persona login or a pre-filled cart), and the Checks that decide if an Episode passed.

**Skill**:
The category of a Task, for example `exact`, `browse`, `checkout`, or `order_history`. ShopGuru generates, stores, and scores Tasks per Skill.
_Avoid_: category

**Check**:
One gradable condition in the `eval` list of a Task: `string_match`, `url_match`, `locator_probe`, `state_check`, or `llm_judge`. Code grades most Checks; `llm_judge` and fuzzy string matches use an LLM judge.
_Avoid_: verifier

**Seed task**:
A Task that a deterministic generator makes from the Dataset. The same Dataset and seed string always give the same Seed tasks.

**Explore task**:
A Task that an explorer agent proposed while it browsed a hosted SandboxShop. ShopGuru keeps it only after a fresh browser confirms it.
_Avoid_: agent-discovered task, discovered task

**Benchmark**:
The validated Tasks for one SandboxShop, stored as one file per Skill.
_Avoid_: dataset

**AgentUnderTest**:
The interface that every measured agent implements. It receives one Episode (the Task, a ready BrowserSession, and the Browser tools) and returns a Trajectory and a status.
_Avoid_: solver

**Grader**:
The code that turns one finished Episode (answer, final URL, final page, and StateSnapshot) and the Checks of its Task into a pass or a fail.
_Avoid_: verifier, judge

**Aggregate**:
The roll-up of the Episode results of one evaluation into pass rates (overall, by Skill, and by shop) and token and cost totals.

### Harness

**Harness run**:
One call of the Harness over one run directory, from the planner Iteration until the plan is done or the budget ends. A stopped Harness run can resume in the same directory.
_Avoid_: run (alone)

**Iteration**:
One fresh-context Agent run inside a Harness run: the one planner iteration that writes `plan.md`, or one executor iteration that works on one Plan task.
_Avoid_: LLM turn, step

**Plan task**:
One line in the `## Tasks` list of `plan.md`, with an id, a status (pending, in progress, done, or blocked), a priority, and a note. In the Build loop it is a build task.
_Avoid_: harness task, task (alone)

**Artifact seed**:
The input files that the Harness copies into the `artifact/` directory of a run when the Harness run starts. They must not change: an edit, a deletion, or a new file inside them is a protocol violation.
_Avoid_: seed (alone), seeded subtree

**Verifier**:
A rule or an LLM judge that the caller gives the Harness to run after each executor Iteration. Its verdict is `pass`, `fail` (which reopens the Plan task), `advisory`, or `error`.
_Avoid_: check, grader

### Agent and browser

**AgentRuntime**:
The seam that does one Agent run: it sends a prompt and tools to a model, runs the tool calls, and returns a Trajectory. An adapter binds it to one SDK; pi is the shipped adapter.

**Agent run**:
One call of `AgentRuntime.run`: one prompt, the tool calls of the model, and one Trajectory. A Harness run holds one Agent run per Iteration.
_Avoid_: episode

**Trajectory**:
The SDK-independent, ordered record of one Agent run: messages, tool calls, tool results, and token usage.

**BrowserSession**:
One Chromium browser, context, and page bound to one Episode id, so that every request it sends carries the episode header.
_Avoid_: session (alone)

**Browser tools**:
The agent tools that act on the page of a BrowserSession through element refs from the latest aria snapshot. They include `finish`, which ends the Episode with an answer or marks it infeasible.
