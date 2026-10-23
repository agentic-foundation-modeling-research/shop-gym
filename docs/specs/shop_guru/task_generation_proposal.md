# Shopping Task Generation Proposal

Status: **Proposed**. Audience: **ShopGym developers**.
Main content: **15–20 minutes**; supporting audit and research are in the appendix.
Support baseline: `v2/5-cutover` at
[`230c185a`](https://github.com/agentic-foundation-modeling-research/shop-gym/commit/230c185a6fd7f1616bb18cdf276d451f03c976ab),
reviewed on 2026-10-22.

## Overview

Existing ShopGuru generates tasks that are too simple to represent the range of
real shopping-agent use cases. Its deterministic seeds provide useful basic
checks, but mostly instantiate narrow, fixed templates: `exact` asks for a named
product and accepts any variant; `shipping` and `returns` ask the agent to open a
policy page; `e2e` adds two named products and changes one quantity. Account and
checkout seeds start with login or shopping-cart setup already applied. These
exercise navigation and action execution, with limited product choice, policy
reasoning, or planning. [C1]

Changing product names or extending a prescribed action sequence does not provide
systematic coverage of interacting constraints, suitability, compatibility,
repeat shopping, recovery, or user clarification. ShopGuru also lacks explicit
difficulty control and complete feasibility/verifier validation for discovered
tasks. Consequently, its current task set gives limited evidence about whether
an agent can handle a broader shopper goal. These are coverage/design limitations;
we have not measured their effect on agent rankings. [C2] [C11] [C13]

This proposal gives developers a shared catalog of **23 task families and 6
scenario variations**, with generation methods and verifiers chosen for each
goal. It retains exactly three task tiers—**Easy, Medium, Hard**—and uses
**shopping cart** terminology. Visual product matching is out of scope for now.
Review should focus on the catalog's coverage, the initial supported subset, and
which missing capabilities to add next. The rollout remains proposed.

## Terminology

A **task family** is a shopper goal; its **category** identifies the journey stage.
A **scenario variation** adds requirements such as recovery or clarification to a
base family. A **witness** is one validated solution proving feasibility; every
other solution satisfying the same requirements should also pass.

Task difficulty measures reasoning and interaction demands, not clicks or length:

- **Easy (E):** explicit goal, direct evidence, few independent constraints.
- **Medium (M):** multiple constraints/sources or dependent decisions/state changes.
- **Hard (H):** interacting constraints, trade-offs, compatibility, optimization,
  distributed requirements, or meaningful recovery.

Verification difficulty is separate: **Low** = direct checks; **Moderate** = joins,
calculations or constraint checks; **High** = semantic evidence or interaction
assessment. Objectivity is **Exact**, **Mixed** (exact plus semantic checks), or
**Rubric-based** (materially subjective). An expensive optimizer can still yield
an exact verdict. Database queries below refer to catalog/fixture records and
snapshots; no SQL service is assumed.

## Current Status

The cutover branch provides ten seed skills, episode-isolated shopping carts,
basic registration/login/logout, customer/address reads, order history, simulated
checkout and inventory changes. Grading supports text, URL, locator, snapshot and
opt-in LLM checks. The environment therefore supports more than the existing seed
templates exercise. [C1] [C3] [C4] [C5] [C6]

Other families need domain support: account edits, reviews, wishlists and
after-sales workflows are absent; coupons lack actual discount semantics;
logistics are limited to flat shipping choices. Interactive user requirements
also need a runner protocol. The table identifies these gaps. Support is audited
from shared code, so each generated shop still needs capability/UI validation.
See [Appendix A](#a-baseline-capability-audit) for implementation details.

## Desired Status

Every admitted task should express a realistic shopper intent, expose sufficient
evidence, have a valid setup and a feasible solution or proven infeasibility, and
accept all valid outcomes while rejecting plausible mistakes. Coverage should
span journey stages and difficulty levels.

Keep **environment support**, **generator coverage**, and **verifier readiness**
separate. A generated prompt does not establish executability; an absent seed
family does not imply the environment cannot perform the action.

## Proposal

### Unified task catalog

Keep one catalog for all families and variations. Examples are illustrative:
instantiate only facts/actions available in the target shop.

Support: **Basic** = core operations exist; **Partial** = a useful subset exists;
**Missing** = core workflow needs support; **Later** = expansion beyond the initial
single-shop scope. Basic does not imply every example or verifier is implemented.
Rows V1–V6 are reusable scenario variations, rather than additional base families.

| ID | Category | Task family and realistic examples | Difficulty | Current ShopGym support and gaps | Proposed task generation approach | Required verifier(s) | Verification difficulty / objectivity |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | Discovery and decision | **Known-item discovery.** E: Find the TrailLite 20L backpack. M: Find its available navy variant, distinguishing it from the older model. | Easy–Medium | **Basic:** search/variants exist; seeds permit any variant. [C1] | Catalog-first: choose an available target, identifying attributes, and similar-model distractors. | Catalog ID/variant query; answer/URL check; shopping-cart state when requested. | **Low / Exact.** |
| 02 | Discovery and decision | **Constraint-based discovery.** E: Find a cotton shirt under $30. H: Find black, machine-washable trousers in my size under $80, excluding wool. | Easy–Hard | **Partial:** filters exist; combined predicates and care/material evidence need work. [C1] [C10] | Answer-first: derive constraints from a feasible item; enumerate all matches and near misses. | Catalog query for attributes, budget, size, and stock; prose evidence where needed. | **Low–Moderate / Exact; Mixed** for prose. |
| 03 | Discovery and decision | **Occasion/use-case recommendation.** E: Suggest a housewarming gift under $25. H: Choose a gift for a beginner gardener with a small balcony and no storage space. | Easy–Hard | **Partial:** browsing exists; needs-based generation and preference rubrics are absent. [C1] | Needs-first: sample use case/persona; ground suitable products and explicit preference criteria. | Budget/stock query plus evidence-grounded LLM judge for suitability and explanation. | **High / Rubric-based.** |
| 04 | Discovery and decision | **Comparison and value.** E: Which of two coffee packs is cheaper per kilogram? H: Compare three backpacks on capacity, weight, price, and warranty using my stated priorities. | Easy–Hard | **Partial:** prices/text exist; units, warranty, comparison and calculation checks need work. [C10] | Comparison-first: sample candidates and priorities; calculate rankings before generating the request. | Unit conversion, arithmetic/ranking; factual checks; LLM judge for qualitative trade-offs. | **Moderate / Exact or Mixed.** |
| 05 | Discovery and decision | **Substitution and unavailability.** E: Find a cheaper alternative to this mug. H: My preferred shoe is unavailable; preserve size, material, and fit within budget. | Easy–Hard | **Partial:** similarity seeds/stock exist; attribute-preserving alternatives need stronger grounding. [C1] | Choose source item and preserved/relaxed attributes; enumerate alternatives under stock constraints. | Price/stock/attribute queries; exclude original; LLM judge for functional similarity. | **Moderate–High / Mixed.** |
| 06 | Discovery and decision | **Sizing, fit, and compatibility.** M: Use my measurements and the size chart to choose a shirt size. H: Find a replacement filter for my exact appliance model and reject a similar incompatible filter. | Medium–Hard | **Partial:** descriptions/options exist; validated size charts and compatibility relations are not guaranteed. [C10] | Relation-first: validate charts/model compatibility, then sample matches and near misses. | Size-range lookup or compatibility query; source-backed fit/uncertainty assessment. | **Moderate / Exact; Mixed** for fit. |
| 07 | Discovery and decision | **Review-grounded research.** M: Summarize recurring sizing complaints for these shoes. H: Compare recent verified-purchase reviews, distinguishing repeated defects from isolated complaints. | Medium–Hard | **Missing:** review data, evidence access/filtering, and corresponding UI. [C10] | Evidence-first: annotate dated reviews, purchase flags, corroboration and contradictions; generate questions. | Review-filter query; source-span checks; LLM judge for faithful, representative synthesis. | **High / Mixed.** |
| 08 | Discovery and decision | **Policy and store information.** E: What is the return window? H: For a discounted gift shipped internationally, explain the applicable shipping and return conditions. | Easy–Hard | **Partial:** policy pages/navigation seeds exist; answer and exception checks need adding. [C1] | Policy-first: extract rules/exceptions and source spans; compute the scenario outcome. | Policy-rule query/calculation; grounded answer judge; URL check for navigation goals. | **Low / Exact** to **High / Mixed.** |
| 09 | Shopping cart and purchase | **Variant and quantity selection.** E: Add two blue mugs. M: Add one medium black shirt and two large white shirts, using available variants only. | Easy–Medium | **Basic:** variant/shopping-cart mutations; seeds need precise variant–quantity checks. [C1] [C8] | State-first: sample available variants/quantities and generate the shopper request. | Shopping-cart line multiset by variant ID/quantity; reject unwanted lines. | **Low / Exact.** |
| 10 | Shopping cart and purchase | **Shopping cart revision.** E: Remove the duplicate mug. H: Replace the large pack with two small packs, preserve all other lines, and keep the total under $70. | Easy–Hard | **Basic:** mutations/prefilled setup; revision generators and diff checks need adding. [C2] [C8] | Seed initial shopping cart; specify requested changes and untouched-line invariants. | Before/after shopping-cart diff plus pricing, budget and preserved-line checks. | **Low–Moderate / Exact.** |
| 11 | Shopping cart and purchase | **Multi-item shopping cart planning.** M: Choose a notebook and pen for under $20. H: Build a cooking kit for four campers, covering required roles with compatible items within budget. | Medium–Hard | **Partial:** multi-item shopping carts exist; role/compatibility planning and set-level grading need work. [C1] | Witness-first: validate one feasible shopping cart; derive budget/request; retain independent constraints. | Quantity, budget, role-coverage and compatibility predicates; semantic suitability judge when needed. | **Moderate–High / Exact or Mixed.** |
| 12 | Shopping cart and purchase | **Promotions and total-cost optimization.** M: Apply an eligible 10% coupon. H: Choose the best legal coupon combination for my shopping cart, including shipping and a useful threshold top-up if it lowers the payable total. | Medium–Hard | **Partial:** tax/shipping work; coupon eligibility, discounts and stacking are missing. [C7] [C8] | Rule-first: generate feasible shopping cart/coupons; compute optimum over a declared candidate space. | Pricing engine, eligibility/stacking checks, optimizer; useful-top-up predicate. | **Moderate–High / Exact.** |
| 13 | Shopping cart and purchase | **Delivery, pickup, and deadlines.** E: Does the shop deliver to my country? H: Find the cheapest option arriving before Friday, with pickup as a fallback. | Easy–Hard | **Partial:** policies/flat shipping exist; serviceability, arrival dates and pickup need support. [C5] [C10] | Policy templates first; later sample destination, date, service rules and feasible slots. | Policy evidence; serviceability/calendar calculation; selected delivery/pickup state. | **Moderate / Exact; Mixed** for prose. |
| 14 | Shopping cart and purchase | **Checkout and order placement.** E: Complete guest checkout for this shopping cart using supplied details. M: Place the order to my office with the specified shipping/payment options and final amount. | Easy–Medium | **Basic:** guest/customer simulated checkout exists; seed uses signed-in, prefilled setup. [C1] [C5] | Scenario templates: seed shopping cart/identity/address; calculate totals and expected order changes. | New-order delta, exact lines, identity/address/methods/totals, inventory; no duplicate orders. | **Low–Moderate / Exact.** |
| 15 | Accounts and repeat shopping | **Account access.** E: Register with these details without marketing opt-in. M: Sign in, report the default-address city, then sign out. | Easy–Medium | **Basic:** register/login/logout exist; current account seed starts signed in. [C1] [C4] | Persona templates: seeded credentials or unused email; expected customer/session changes. | Customer/marketing state; session/cookie checks; required login/read/logout sequence. | **Low–Moderate / Exact.** |
| 16 | Accounts and repeat shopping | **Profile, addresses, and payment preferences.** E: Save my office address. M: Make it the default for future purchases, remove an obsolete address, and preserve existing orders. | Easy–Medium | **Missing for edits:** profile/address reads exist; edit/default/payment-preference mutations and UI do not. [C4] [C9] | State-transition templates: seed records, intended changes, and preserved entities. | Customer/address/payment diff; default-reference integrity; unchanged existing orders. | **Low–Moderate / Exact.** |
| 17 | Accounts and repeat shopping | **Wishlist and saved plans.** E: Save these two products for later. M: Move available saved items below $30 into my shopping cart while retaining unavailable items in the wishlist. | Easy–Medium | **Missing:** wishlist state, persistence, mutations and UI. [C6] | Seed saved list; derive target changes under stock/price constraints. | Wishlist/shopping-cart set diff; quantities, retained items, and duplicate checks. | **Low–Moderate / Exact.** |
| 18 | Accounts and repeat shopping | **Order lookup, status, and spending.** E: Report my latest order status. H: Calculate kitchen-category spending last quarter after partial refunds. | Easy–Hard | **Partial:** history/detail seeds exist; aggregate checks and partial-refund ledger need adding. [C1] [C6] | History-first: seed dated orders/category links; precompute aggregates; add refunds when modeled. | Customer-scoped order/date/category queries; arithmetic and refund accounting. | **Low–Moderate / Exact.** |
| 19 | Accounts and repeat shopping | **Reordering.** E: Add the coffee from my last order to my shopping cart. H: Repeat the office order without pens, double the paper, and substitute an unavailable item. | Easy–Hard | **Partial:** history/shopping-cart/checkout exist; reorder generation and stock-aware checks need adding. [C6] [C8] | Compose from prior order; transform quantities/exclusions; validate available alternatives. | Source-order join; shopping-cart/new-order quantities, exclusions, stock and substitution checks. | **Moderate / Exact or Mixed.** |
| 20 | After-sales | **Order modification and cancellation.** E: Cancel my unshipped order. H: Cancel only the duplicate order and change the other order's address if policy permits. | Easy–Hard | **Missing:** cancellation/edit lifecycle, mutations and stock/payment effects. [C5] [C6] | Policy-constrained transitions: seed eligible/ineligible orders and expected changes. | Order-state diff; eligibility; inventory/payment effects; preserve unrelated orders. | **Moderate / Exact.** |
| 21 | After-sales | **Returns, exchanges, and refunds.** E: Request a return for a damaged mug. H: Exchange a shirt's size, return one of two mugs, and explain why another line is ineligible. | Easy–Hard | **Missing:** executable return/exchange/refund workflows; policy lookup exists. [C1] [C6] | Scenario templates: order lines, dates, reasons, exceptions and replacement stock. | Line-level lifecycle/amount/stock queries; policy calculations; grounded explanation judge. | **Moderate–High / Mixed.** |
| 22 | After-sales | **Review submission and management.** E: Submit a four-star review using my supplied feedback. M: Update my own review after a replacement while preserving its purchase relationship. | Easy–Medium | **Missing:** review state, ownership/purchase links, mutations and UI. [C6] [C10] | Authenticated templates using supplied user feedback, rating, prior review and purchase. | Review/author/purchase queries; rating/update checks; text-fidelity LLM judge. | **Low / Exact; High / Mixed** for text. |
| 23 | After-sales | **Subscriptions and recurring replenishment.** M: Set coffee delivery to every four weeks. H: Skip the next shipment and reduce future quantity while keeping the subscription active. | Medium–Hard | **Later:** subscription lifecycle, recurrence and UI are absent. [C6] [C10] | Schedule/state-machine templates with controlled time and intended future state. | Subscription/schedule query; calendar/shipment checks; preserved history. | **Moderate / Exact.** |
| V1 | Scenario variation | **Personalization and memory.** M: Use the size from my last purchase. H: Recommend items respecting preferences supplied across earlier sessions. | Medium–Hard | **Partial:** customer/order history exists; preference memory and cross-session control do not. [C2] [C6] | Persona/history-first: precommit preferences, evidence sources and per-session memory availability. | History/preference queries; recommendation predicates; soft-preference judge and memory-access evidence. | **Moderate–High / Mixed.** |
| V2 | Scenario variation | **Clarification and confirmation.** M: Clarify which coffee I mean by “my usual.” H: Resolve an ambiguous delivery address and obtain the required confirmation before order placement. | Medium–Hard | **Missing:** shopper dialogue, hidden-spec/reveal protocol and confirmation-event checks. [C2] [C12] | Withhold a required field from a feasible task; fix answers/reveal rules before interaction. | Question/confirmation events and ordering; reveal log; resolved-goal state. | **High / Exact or Mixed.** |
| V3 | Scenario variation | **Incremental requirement changes.** M: Switch my coffee request to decaf mid-task. H: Tighten the budget after a proposed shopping cart and preserve the remaining requirements. | Medium–Hard | **Missing:** controlled follow-ups and versioned requirements in the runner. [C2] [C12] | Perturb a validated task with a precommitted change and feasible revised solution. | Reveal timing; active requirement version; final constraints and removal of obsolete choices. | **High / Exact or Mixed.** |
| V4 | Scenario variation | **Infeasibility and recovery.** M: Report that no available product meets all constraints without purchasing. H: Recover from an insufficient-stock checkout error by selecting an allowed alternative. | Medium–Hard | **Partial:** atomic checkout stock errors exist; infeasibility/recovery generators and event injection need work. [C5] | Prove an empty result set or seed stock shortfall; predefine allowed recovery. | Constraint/stock proof; error evidence; final state, preserved entities and grounded explanation. | **Moderate–High / Mixed.** |
| V5 | Scenario variation | **Action boundaries and collateral effects.** E: Research options without changing my shopping cart. H: Update only the specified address while preserving every unrelated address and order. | Easy–Hard | **Partial:** snapshots exist; general diff and transient-event graders do not. [C3] [C6] | Attach allowed-change sets/forbidden actions; seed unrelated records to preserve. | State diffs for terminal invariants; events/trajectory for forbidden actions and confirmation order. | **Low–Moderate / Exact; High / Mixed** for traces. |
| V6 | Scenario variation | **Cross-shop shopping.** M: Compare the delivered price of the same product at two shops. H: Split a compatible shopping cart across shops while including separate shipping charges. | Medium–Hard | **Later:** no coordinated multi-shop setup or grader. [C2] [C12] | Join validated catalogs; derive comparable identities, fees and feasible allocation. | Cross-shop price/state queries; equivalence/compatibility predicates; bounded allocation optimizer. | **Moderate–High / Exact or Mixed.** |

### Choose the recipe for the goal

Choose from complementary generation recipes:

- **Catalog/answer-first** for discovery, comparison and compatibility: derive
  requirements from verified facts and compute the complete valid set.
- **Scenario/state-transition templates** for shopping-cart edits, accounts,
  checkout and after-sales: define setup, intended changes and preserved state.
- **Needs-first with evidence** for recommendations: connect the shopper's purpose
  to product facts and an explicit suitability rubric.
- **Witness-first** for multi-item planning and promotions: validate feasibility
  before deriving the budget/request, then grade independent constraints.
- **Functionality exploration** for coverage of actual shop affordances: convert
  discovered actions into replayable tasks with independent assertions.

Trajectory synthesis, state-machine search and environment/task/verifier
co-generation can support discovery or later domain expansion. The research
basis, trade-offs and limits of each method are in
[Appendix B](#b-generation-recipes-and-research-rationale).

### Generation and admission

```mermaid
flowchart LR
    A[Shop evidence and capabilities] --> B[Family, difficulty, recipe]
    B --> C[Setup, constraints, witness, verifier]
    C --> D[Natural shopper request]
    D --> E[Independent replay and verifier validation]
    E --> F[Coverage review and admission]
```

Record family/category, scenario variations, difficulty, recipe, required
capabilities, verifier difficulty/objectivity and provenance. Reference facts,
witnesses and hidden requirements stay outside the agent-visible request; these
metadata and interaction contracts require extensions to the current schema. [C2]

Admission requires four checks:

1. **Grounding:** evidence and actions exist and are accessible through the agent's
   permitted UI. Do not invent size charts, compatibility, reviews or promises.
2. **Feasibility:** independently query/solve constraints and replay a solution in
   a fresh episode. For infeasible tasks, retain a contradiction or empty-result
   proof; a solver failure or agent refusal is insufficient.
3. **Verifier quality:** accept a valid outcome and legitimate alternatives;
   reject targeted mistakes such as wrong variant, extra line, stale order,
   wrong total or changed unrelated record.
4. **Naturalness and diversity:** express a plausible need, make all requirements
   stated or recoverable, and reject paraphrases/parameter swaps that add no
   meaningful goal, evidence or workflow coverage.

### Verification and coverage principles

Use deterministic queries for structured facts and state changes. Check exact
variant–quantity pairs, newly created orders, totals and preserved entities. Use
an evidence-grounded LLM judge for suitability, synthesis and explanations;
score hard constraints separately. A hidden witness proves feasibility without
restricting the answer to that witness.

Record trusted events for temporal requirements such as confirmation before
purchase or login before logout. A final snapshot cannot establish that a
forbidden transient action never occurred. Freeze hidden requirements and reveal
rules before interactive runs. Detailed grader limits and domain-specific edge
cases are in [Appendix C](#c-verifier-design-notes).

Track **family × difficulty × scenario variation**, plus product domain,
information source, constraint interactions and initial state. Include ties,
multiple valid outcomes, infeasibility and recoverable errors where appropriate.
Do not force Hard variants for simple operations. Calibrate tiers with pilot
runs/human review, report per-family/per-tier results, and separate environment
failures from agent failures. Prevent prolific discovery templates from
controlling the headline score; final weights and sample counts follow the pilot.

## Alternative

Expanding only the current deterministic seeds is the smallest step and fits
exact discovery/state changes, but leaves semantic decisions and interactions
underrepresented. A single LLM generator/judge is flexible but provides weaker
feasibility and exact-state guarantees. The proposed combination uses each where
its grounding and verification are strongest.

## Execution Table

Implement by capability increment; emit only tasks supported by the target shop.
This PR proposes coverage and sequencing, without implementing the generators.

| Increment | Proposed scope | Key work | Exit evidence |
| --- | --- | --- | --- |
| 1. Baseline pilot | 01–02, 08–10, 14–15, basic 18–19; supported subsets of 04–06, V4–V5 | Add metadata/generators and exact line, new-order and preservation checks; exercise existing auth. | Fresh-episode replay, proven negative cases, valid alternatives accepted, targeted errors rejected, coverage report. |
| 2. Richer decisions | 03–06, 11; complex 02, 08, 18–19 | Validate attributes/relations/policies; add witness search, calculations and semantic rubrics. | Independent feasibility/evidence audit and calibrated semantic checks. |
| 3. Interactive scenarios | V1–V5 on supported base families | Add dialogue/reveal protocol, controlled changes, memory fixtures and event predicates. | Scripted replay, ordering checks, and measured simulator violations. |
| 4. Commerce domains | 07, full 12–13, 16–17, refund-aware 18, 20–22 | Add domain records/rules/mutations/UI before generators; domains can ship independently. | Domain contracts, UI replay and verifier validation for each family. |
| 5. Later expansion | 23, V6 | Subscription lifecycle/calendar and coordinated multi-shop episodes. | Reviewed semantics, isolation, replay and cross-domain checks. |

Review decisions: initial family/tier allocation, treatment of subjective scores
in the headline metric, and the first missing domain to prioritize. Supporting
implementation and literature detail follows in the appendix.

## Appendix

### A. Baseline capability audit

The support audit uses the **shared backend and storefront template on
`v2/5-cutover`**, rather than `main` or a planned specification. It is a static
code audit, not an end-to-end certification of every generated shop. A generated
shop may expose fewer features or extend its backend; task admission must check
that particular shop's data and UI.

The baseline already has:

- Ten deterministic seed skills: `exact`, `substitute`, `browse`, `filter`,
  `shipping`, `returns`, `e2e`, `account`, `checkout`, and `order_history`.
  These names are coarser than the proposed families. For example, `returns`
  locates a policy page; it does not execute a return. [C1]
- Episode-scoped shopping carts, customer registration and access-token
  login/logout, customer/address reads, order history, simulated checkout/order
  creation, inventory changes, reset, and grader snapshots. Basic login is
  therefore supported on this base. [C4] [C5] [C6] [C9]
- `string_match`, `url_match`, `locator_probe`, `state_check`, and explicit
  `llm_judge` checks. `state_check` supports equality, subsets, and array membership;
  all configured checks must pass. Fuzzy text matching also invokes a judge. [C2] [C3]
- An explorer that proposes tasks and checks page reachability/locators in a fresh
  browser. This is useful grounding, but it does not replay a full solution or
  establish semantic correctness and feasibility for every check type. [C11]

Important limits for the catalog:

- Current account seeds start **already signed in**. Registration, login, and
  logout need dedicated task generators and checks, rather than new basic auth
  infrastructure. Address/profile editing and saved-payment management do need
  additional mutations and UI. [C1] [C4] [C9]
- Checkout uses configured shipping/payment handles and simulated payment. Pricing
  supports a flat tax rate, flat shipping rates, and a free-shipping threshold.
  Discount codes are stored and reported applicable without eligibility or price
  effects; coupon optimization is not supported. Delivery dates, geographic
  serviceability, and pickup slots are not modeled in commerce settings. [C5] [C7] [C8] [C10]
- The shared state/schema does not provide wishlist, review, subscription,
  cancellation, return, exchange, or refund workflows. Seeded financial status is
  not a refund ledger. [C4] [C6] [C10]
- The task contract has one goal, optional login/shopping-cart setup, and evaluation
  checks. It has no typed difficulty, recipe, user-dialogue/reveal protocol, or
  cross-session memory contract. Built-in grading does not provide arbitrary
  constraint queries, an optimizer, state diffs, or event-order predicates. The
  judge receives the goal, rubric, final answer/URL, prior check results, and an
  optional final screenshot; full source evidence and interaction history need
  explicit plumbing. [C2] [C3] [C12]

### B. Generation recipes and research rationale

Use a small set of complementary recipes. The mapping in the catalog is our
proposal; the papers provide supporting methods rather than evidence that the
ShopGym implementation already has them.

1. **Scenario templates with setup, solution, and assertions.** Best for accounts,
   shopping-cart edits, checkout, and after-sales transitions. Parameterize customer
   records, initial state, permitted changes, and distractors before producing
   natural language. AppWorld's scenario construction and programmatic evaluation
   provide a useful precedent. [AppWorld](https://arxiv.org/html/2407.18901)
2. **Catalog/answer-first constraint generation.** Best for discovery, comparisons,
   and compatibility. ShoppingBench samples products, extracts fields, and writes
   grounded queries. EComAgentBench fixes the answer and typed rubrics before
   generating language, then distributes requirements across the query, profile,
   and clarification. For ShopGym, execute the predicates over the catalog and
   retain the complete valid set. [ShoppingBench](https://arxiv.org/html/2508.04266v1),
   [EComAgentBench](https://arxiv.org/html/2606.17698v1)
3. **Needs-first scenarios with evidence grounding.** Best for occasion-based
   shopping and functional substitutes. EcomScriptBench connects user objectives,
   script steps, purchase intentions, and products. Adapt that semantic bridge to
   shopper goals, then validate recommendations against actual catalog evidence
   and an explicit preference rubric.
   [EcomScriptBench](https://arxiv.org/html/2505.15196v1)
4. **Witness-first shopping-cart construction.** Best for multi-item planning and
   promotions. ComboShoppingBench validates a feasible witness before deriving
   coupons, budget, query, and rubrics. The witness proves feasibility; it is not
   the only correct answer. Its coupon optimality is evaluated for the submitted
   shopping cart, so global product-selection optimality requires a separate,
   explicit objective and search space.
   [ComboShoppingBench](https://arxiv.org/html/2608.09282v1)
5. **Functionality-grounded exploration.** Best for discovering tasks that a shop's
   actual pages and controls support. Amazon-Bench grounds queries in page content
   and interactive elements, followed by refinement and review. Extend ShopGuru's
   explorer with solution replay and independent assertions before benchmark
   admission. [Amazon-Bench](https://arxiv.org/html/2508.15832v1), [C11]
6. **Trajectory-first or reverse synthesis.** Useful for discovering affordances
   and collecting training demonstrations. NNetNav labels explored trajectories;
   SynWeaver uses website maps, reverse synthesis, refinement, and post-verification.
   For evaluation tasks, reconstruct the initial state and add an independent
   verifier before admission; a post-hoc description alone is insufficient.
   [NNetNav](https://arxiv.org/html/2410.02907v1),
   [SynWeaver](https://arxiv.org/html/2608.12429v1)
7. **State-machine search.** Best for controlled compositions of commerce state
   transitions after the domain model exists. AutoWebWorld uses finite-state
   machines and graph traversal to obtain reachable goals and trajectories.
   ShopGym could use the same principle to enumerate meaningful workflows while
   separately checking that the browser implements the modeled transitions.
   [AutoWebWorld](https://arxiv.org/html/2602.14296v1)
8. **Environment/task/verifier co-generation.** Useful when the desired family
   requires missing domain behavior. VeriEnv and WebArena Infinity are precedents
   for generating executable environments with verifiable tasks. Treat generated
   validators as candidates: review the domain contract and test them against
   correct alternatives and deliberately wrong outcomes to reduce shared errors.
   [VeriEnv](https://github.com/kyle8581/VeriEnv),
   [WebArena Infinity](https://github.com/web-arena-x/webarena-infinity)

For V1–V3, personalize or perturb a grounded base task rather than freely inventing
a conversation. Recent work on long-horizon shopping personalization motivates
testing consistency across interactions; it does not establish that our current
browser runner supports that protocol.
[Personalization Matters](https://arxiv.org/html/2610.11375v1)

### C. Verifier design notes

Prefer deterministic state/database queries for state changes and structured
facts. Validate variant–quantity pairs as sets/multisets, query newly created
orders relative to the initial snapshot, and calculate money in integer minor
units using the shop's declared rules. A title on the shopping-cart page is weak
evidence of correct contents; a coupon string is weak evidence of a discount.

Extend snapshot grading with constraint, aggregation, optimization, and
before/after predicates where needed. Preserve the existing lightweight checks
for goals they actually establish: URL checks for navigation, literal matching
for unambiguous reported facts, and locators for required UI evidence. Current
validation checks schemas/references and exact duplicate goals, rather than all
of these stronger properties. [C2] [C3] [C13]

Use an LLM judge for evidence-grounded suitability, synthesis, and faithful
explanations. Supply the relevant source records/spans and a decomposed rubric;
grade hard constraints separately. Audit a human-labeled sample and report judge
agreement and false-positive/false-negative cases before relying on subjective
scores. Publish exact and semantic components separately so one does not hide the
other.

For temporal requirements, record interaction/commerce events: login before
logout, confirmation before purchase, requirement reveal before action, and
forbidden transient changes. A final snapshot can establish preservation at the
end but cannot prove that an action never occurred. The runner already records
agent trajectories; a trusted event schema and corresponding grader predicates
remain proposed extensions. [C6] [C12]

Additional task-specific rules:

- **Promotions (12):** declare whether optimality concerns coupon selection for a
  fixed shopping cart or product selection over a bounded candidate space. A
  stored coupon code is not evidence of a price reduction.
- **Order spending (18):** define the time window, gross/net treatment, partial
  refunds, and allocation of tax/shipping before computing a reference answer.
  Financial-status labels cannot substitute for a refund ledger.
- **Account access (15):** verify browser access/session effects as well as backend
  state. Ending signed out does not establish that the required login/read steps
  occurred. Password recovery/OTP is outside the baseline auth surface.
- **Interactive variations (V1–V3):** keep a versioned requirement/reveal ledger;
  validate answers and disclosure timing separately from final task success.
  Hidden facts must be recoverable through permitted observations.
- **Subscriptions and cross-shop tasks (23, V6):** define recurrence/billing rules,
  product equivalence and coordinated isolation before generating tasks; these
  remain later expansions.

### D. Code evidence

These links point to the implementation inherited from the audited baseline.
They support the Current Status and catalog support assessments; proposed
verifiers and generation recipes are not claims of shipped behavior.

- [C1: Seed generators][C1] — inspect the individual generators for exact coverage.
- [C2: Task and check schema][C2] — setup, goal, provenance, and evaluation contract.
- [C3: Grading dispatcher][C3] — current check behavior and judge inputs.
- [C4: Customer schema][C4] — auth mutations and read-only profile/address surface.
- [C5: Checkout resolver][C5] — validation, commerce settings, simulated placement.
- [C6: Episode snapshot][C6] — grader-visible customer, session, shopping-cart,
  order, and inventory state; [state transitions](../../../packages/shop_backend/src/state/shop_state.ts).
- [C7: Pricing][C7] — flat tax/shipping and free-shipping threshold calculations.
- [C8: Shopping-cart resolver][C8] — mutations and placeholder discount-code behavior.
- [C9: Account routes][C9] and [checkout route](../../../packages/shop-arena/templates/storefront/app/routes/checkout.tsx).
- [C10: Dataset schemas][C10] — catalog, customer, order, and commerce data contracts.
- [C11: Explorer proposal verification][C11] — page/locator checks, not full replay.
- [C12: Agent-under-test runner seam][C12] — single-goal browser episode;
  [episode execution](../../../packages/shop-guru/src/solve/solve.ts).
- [C13: Task validation][C13] — schema/reference validation, goal deduplication, caps.

[C1]: ../../../packages/shop-guru/src/seed/index.ts
[C2]: ../../../packages/core/src/schema/task.ts
[C3]: ../../../packages/shop-guru/src/grade/grade.ts
[C4]: ../../../packages/shop_backend/src/schema/customer.ts
[C5]: ../../../packages/shop_backend/src/resolvers/checkout.ts
[C6]: ../../../packages/shop_backend/src/sandbox/snapshot.ts
[C7]: ../../../packages/shop_backend/src/state/pricing.ts
[C8]: ../../../packages/shop_backend/src/resolvers/cart.ts
[C9]: ../../../packages/shop-arena/templates/storefront/app/routes/account
[C10]: ../../../packages/shop_backend/src/data/schema.ts
[C11]: ../../../packages/shop-guru/src/explore/verify.ts
[C12]: ../../../packages/shop-guru/src/solve/agent.ts
[C13]: ../../../packages/shop-guru/src/validate.ts

### E. Research scope and prior context

The method selection builds on the
[previous ShopGym research review](https://shop-gym.quick.shopify.io/public/specs/docs/shop-gym/shopgym_v2/shopgym_v2_task_research_review.html#methods)
and the primary papers/repositories linked above, including 2026 work through
October. The hosted review redirects to authentication in this environment; its
local counterpart was available as prior research context. It is not part of this
base branch. Current support claims were re-audited against code rather than
copied from that earlier review. This is a focused synthesis for the proposed
catalog, not an exhaustive literature survey or a replication of paper results.
