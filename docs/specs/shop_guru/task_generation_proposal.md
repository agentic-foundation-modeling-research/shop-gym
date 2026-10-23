# Shopping Task Generation Proposal

Status: **Proposed**. Audience: **ShopGym developers**.
Estimated reading time: **15–20 minutes**, excluding the appendix.
Support baseline: `v2/5-cutover` at
[`230c185a`](https://github.com/agentic-foundation-modeling-research/shop-gym/commit/230c185a6fd7f1616bb18cdf276d451f03c976ab),
reviewed on 2026-10-22.

## Overview

ShopGuru’s current tasks are too simple to cover many shopping decisions.
Its deterministic seeds mostly fill fixed templates: `exact` names a product and
accepts any variant; `shipping` and `returns` ask the agent to open a policy page;
`e2e` adds two named products and changes a quantity. Account and checkout seeds
start signed in; checkout also starts with a prefilled shopping cart. These check
navigation and actions but require little product selection, policy reasoning,
or purchase planning. [C1]

Choosing compatible products, reordering from purchase history, and recovering
from unavailable stock require different evidence and success conditions.
Changing product names in existing templates would not cover these needs.
ShopGuru also lacks difficulty labels and validation that establishes feasibility
and tests each task’s verifier. These are coverage gaps; their effect on agent
rankings has not been measured. [C2] [C11] [C13]

We propose **23 task families and 6 reusable scenario variations**, spanning
discovery, purchase, repeat shopping, and after-sales. The catalog pairs examples
and difficulty levels with generation methods, verifiers, and current support.
Different goals use catalog constraints, state-transition templates, or
recommendation scenarios grounded in product evidence. Visual product matching
is outside the scope of this proposal.

The initial implementation would use existing capabilities, including login and
simulated checkout. Richer commerce workflows and interactive scenarios would
follow as their environment and runner support becomes available.

## Terminology

A **task family** describes a type of shopper goal; its **category** identifies
the shopping stage. A **scenario variation** adds a condition such as clarification
or recovery. A **witness** is one validated solution proving feasibility; other
solutions meeting the same requirements are also valid.

Task difficulty has three tiers, based on reasoning and interaction demands:

- **Easy (E):** an explicit goal with direct evidence and few independent constraints.
- **Medium (M):** several constraints or sources, or decisions that depend on earlier actions.
- **Hard (H):** interacting constraints, trade-offs, compatibility, optimization,
  requirements spread across interactions, or recovery that requires replanning.

Verification difficulty describes the work needed to determine success:
**Low** for direct checks, **Moderate** for joins and calculations, and **High** for
semantic or interaction assessment. Objectivity is **Exact**, **Mixed** when exact
and semantic checks are combined, or **Rubric-based** when success depends on
subjective judgment. Task difficulty and verification difficulty are independent:
a difficult optimization task can still have an exact verifier.

A **database query** in the catalog means a query over catalog records, seeded
records, or episode snapshots. It does not require a SQL service.

## Current Status

The cutover branch has ten seed skills and supports isolated shopping carts,
registration, login and logout, customer and address reads, order history,
simulated checkout, and inventory changes. Grading supports text, URL, locator,
snapshot, and opt-in LLM checks. Account-access tasks need new generators and
verifiers, but basic authentication already exists. [C1] [C3] [C4] [C5] [C6]

Profile editing, wishlists, reviews, and after-sales actions require environment
changes. Coupons have no price effects, and logistics use flat shipping options.
Clarification and changing requirements need a runner dialogue protocol. These
assessments come from shared code; each generated shop also needs validation of
its data and UI. [Appendix A](#a-baseline-capability-audit) contains the audit.

## Desired Status

ShopGuru should generate tasks that express plausible shopper goals, provide the
evidence needed to complete them, and accept all outcomes that meet the stated
requirements. Each task should have a valid initial state, a validated solution
or a proof that no solution exists, and a verifier tested against both correct
outcomes and likely mistakes.

Coverage should span shopping stages and difficulty levels. Environment support,
generator coverage, and verifier readiness need separate tracking: a workflow
can exist without a generator, and a generated task can lack a reliable verifier.

## Proposal

### Unified task catalog

The catalog compares target behavior, support gaps, and verification requirements.
Generators can instantiate an example only when its required facts and actions
exist in the target shop.

**Basic** means the core operations exist, **Partial** means a useful subset
exists, and **Missing** means the core workflow needs implementation. **Later**
identifies expansion beyond the initial single-shop scope. These labels describe
environment support, not completed generators or verifiers. Rows V1–V6 are
scenario variations that can be combined with the base families.

| ID | Category | Task family and realistic examples | Difficulty | Current ShopGym support and gaps | Proposed task generation approach | Required verifier(s) | Verification difficulty / objectivity |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | Discovery and decision | **Known-item discovery.** E: Find the TrailLite 20L backpack. M: Find its available navy variant, distinguishing it from the older model. | Easy–Medium | **Basic:** search and variant selection exist; current seeds accept any variant. [C1] | Sample an available product and similar models, then derive identifying attributes from the catalog. | Query product and variant IDs; check the answer or URL, and shopping cart contents when requested. | **Low / Exact.** |
| 02 | Discovery and decision | **Constraint-based discovery.** E: Find a cotton shirt under $30. H: Find black, machine-washable trousers in my size under $80, excluding wool. | Easy–Hard | **Partial:** filters exist; combined constraints and evidence for care instructions or materials need stronger checks. [C1] [C10] | Derive constraints from a feasible item, then enumerate all matching products and near misses. | Query attributes, price, size, and stock; check supporting text for claims outside structured fields. | **Low–Moderate / Exact; Mixed** for prose. |
| 03 | Discovery and decision | **Recommendations for a purpose or occasion.** E: Suggest a housewarming gift under $25. H: Choose a gift for a beginner gardener with a small balcony and no storage space. | Easy–Hard | **Partial:** browsing exists; generation from shopper needs and suitability rubrics are absent. [C1] | Sample a shopper need and preferences; identify suitable products using catalog evidence and an explicit rubric. | Check budget and stock with queries; use an LLM judge to assess suitability and the explanation. | **High / Rubric-based.** |
| 04 | Discovery and decision | **Comparison and value.** E: Which of two coffee packs is cheaper per kilogram? H: Compare three backpacks on capacity, weight, price, and warranty using my stated priorities. | Easy–Hard | **Partial:** prices and descriptions exist; unit conversion, warranty evidence, and comparison checks need work. [C10] | Select candidates and shopper priorities; calculate comparable values and rankings before writing the request. | Check facts, unit conversions, and rankings; use an LLM judge for qualitative trade-offs. | **Moderate / Exact or Mixed.** |
| 05 | Discovery and decision | **Substitution and unavailability.** E: Find a cheaper alternative to this mug. H: My preferred shoe is unavailable; preserve size, material, and fit within budget. | Easy–Hard | **Partial:** similarity seeds and stock data exist; substitutes need checks for the attributes the shopper wants to preserve. [C1] | Select an original item, specify which attributes can change, and enumerate available alternatives. | Query price, stock, and required attributes; exclude the original item; judge functional similarity when needed. | **Moderate–High / Mixed.** |
| 06 | Discovery and decision | **Sizing, fit, and compatibility.** M: Use my measurements and the size chart to choose a shirt size. H: Find a replacement filter for my exact appliance model and reject a similar incompatible filter. | Medium–Hard | **Partial:** descriptions and options exist; reliable size charts and compatibility data depend on the shop. [C10] | Validate size charts or model compatibility data, then sample valid choices and similar but invalid choices. | Query size ranges or compatibility relations; assess fit claims and uncertainty against the source evidence. | **Moderate / Exact; Mixed** for fit. |
| 07 | Discovery and decision | **Review-grounded research.** M: Summarize recurring sizing complaints for these shoes. H: Compare recent verified-purchase reviews, distinguishing repeated defects from isolated complaints. | Medium–Hard | **Missing:** review records, filtering, and review pages need support. [C10] | Prepare dated reviews with purchase flags and recurring or conflicting findings, then generate research questions. | Query the relevant reviews and check cited passages; use an LLM judge to assess whether the summary represents them faithfully. | **High / Mixed.** |
| 08 | Discovery and decision | **Policy and store information.** E: What is the return window? H: For a discounted gift shipped internationally, explain the applicable shipping and return conditions. | Easy–Hard | **Partial:** policy pages and navigation seeds exist; answers and policy exceptions need additional checks. [C1] | Extract rules, exceptions, and supporting passages; calculate the applicable outcome for a shopper scenario. | Evaluate policy rules and calculations; judge answers against source passages. Use URL checks for navigation-only goals. | **Low / Exact** to **High / Mixed.** |
| 09 | Shopping cart and purchase | **Variant and quantity selection.** E: Add two blue mugs. M: Add one medium black shirt and two large white shirts, using available variants only. | Easy–Medium | **Basic:** variant selection and shopping cart mutations exist; seeds need exact quantity and variant checks. [C1] [C8] | Sample available variants and quantities, then generate a request for those items. | Compare shopping cart lines by variant ID and quantity, including checks for unwanted items. | **Low / Exact.** |
| 10 | Shopping cart and purchase | **Shopping cart revision.** E: Remove the duplicate mug. H: Replace the large pack with two small packs, preserve all other lines, and keep the total under $70. | Easy–Hard | **Basic:** shopping cart setup and mutations exist; revision tasks need before-and-after checks. [C2] [C8] | Seed an initial shopping cart and define the requested changes, budget, and items that must remain unchanged. | Compare initial and final shopping carts; calculate the total and check preserved lines. | **Low–Moderate / Exact.** |
| 11 | Shopping cart and purchase | **Multi-item shopping cart planning.** M: Choose a notebook and pen for under $20. H: Build a cooking kit for four campers, covering required roles with compatible items within budget. | Medium–Hard | **Partial:** multi-item shopping carts exist; planning needs checks for required functions, compatibility, and the complete selection. [C1] | Validate one feasible shopping cart before deriving the request and budget; retain success conditions independent of that solution. | Check quantities, budget, required functions, and compatibility; judge suitability where product facts require interpretation. | **Moderate–High / Exact or Mixed.** |
| 12 | Shopping cart and purchase | **Promotions and total-cost optimization.** M: Apply an eligible 10% coupon. H: Choose the best legal coupon combination for my shopping cart, including shipping and a useful threshold top-up if it lowers the payable total. | Medium–Hard | **Partial:** tax and shipping calculations work; coupon eligibility, discounts, and stacking rules are missing. [C7] [C8] | Define promotion rules and a feasible shopping cart; compute the optimum within an explicit set of candidate choices. | Use pricing calculations, eligibility rules, and an optimizer; check that any added item serves the stated need. | **Moderate–High / Exact.** |
| 13 | Shopping cart and purchase | **Delivery, pickup, and deadlines.** E: Does the shop deliver to my country? H: Find the cheapest option arriving before Friday, with pickup as a fallback. | Easy–Hard | **Partial:** policies and flat shipping rates exist; destination eligibility, arrival dates, and pickup need support. [C5] [C10] | Generate policy questions first; after extending logistics, sample destinations, deadlines, and feasible delivery or pickup slots. | Check policy evidence, destination eligibility, dates, and the selected delivery or pickup option. | **Moderate / Exact; Mixed** for prose. |
| 14 | Shopping cart and purchase | **Checkout and order placement.** E: Complete guest checkout for this shopping cart using supplied details. M: Place the order to my office with the specified shipping and payment options and final amount. | Easy–Medium | **Basic:** simulated guest and customer checkout exist; the current seed starts signed in with a prefilled shopping cart. [C1] [C5] | Seed the shopping cart and customer details; calculate the expected total and order state after checkout. | Identify the new order; check lines, customer details, shipping and payment options, total, and inventory. Reject duplicate orders. | **Low–Moderate / Exact.** |
| 15 | Accounts and repeat shopping | **Account access.** E: Register with these details without marketing opt-in. M: Sign in, report the default-address city, then sign out. | Easy–Medium | **Basic:** registration, login, and logout exist; the current account seed starts signed in. [C1] [C4] | Seed credentials or an unused email and define the expected account and session changes. | Check customer records, marketing consent, browser session state, and the required sequence of account actions. | **Low–Moderate / Exact.** |
| 16 | Accounts and repeat shopping | **Profile, addresses, and payment preferences.** E: Save my office address. M: Make it the default for future purchases, remove an obsolete address, and preserve existing orders. | Easy–Medium | **Missing for edits:** profile and address reads exist; editing, default selection, and saved-payment management need mutations and UI. [C4] [C9] | Seed customer records and define the intended edits and records that must remain unchanged. | Compare profile, address, and payment records; check the default address reference and preservation of existing orders. | **Low–Moderate / Exact.** |
| 17 | Accounts and repeat shopping | **Wishlist and saved plans.** E: Save these two products for later. M: Move available saved items below $30 into my shopping cart while retaining unavailable items in the wishlist. | Easy–Medium | **Missing:** wishlist records, persistence, mutations, and UI need support. [C6] | Seed saved items and derive the requested changes from stock and price constraints. | Compare wishlist and shopping cart contents; check quantities, retained items, and duplicates. | **Low–Moderate / Exact.** |
| 18 | Accounts and repeat shopping | **Order lookup, status, and spending.** E: Report my latest order status. H: Calculate kitchen-category spending last quarter after partial refunds. | Easy–Hard | **Partial:** order history and detail seeds exist; aggregate checks and a partial-refund ledger need adding. [C1] [C6] | Seed dated orders with product categories and calculate reference totals; include refunds once the ledger exists. | Query the customer’s orders by date and category; calculate spending using the declared refund rules. | **Low–Moderate / Exact.** |
| 19 | Accounts and repeat shopping | **Reordering.** E: Add the coffee from my last order to my shopping cart. H: Repeat the office order without pens, double the paper, and substitute an unavailable item. | Easy–Hard | **Partial:** order history, shopping carts, and checkout exist; reordering needs generation and stock-aware checks. [C6] [C8] | Start from a previous order, apply exclusions and quantity changes, then validate available substitutes. | Compare the shopping cart or new order with the source order; check quantities, exclusions, stock, and substitutions. | **Moderate / Exact or Mixed.** |
| 20 | After-sales | **Order modification and cancellation.** E: Cancel my unshipped order. H: Cancel only the duplicate order and change the other order's address if policy permits. | Easy–Hard | **Missing:** order editing and cancellation need lifecycle rules, mutations, and inventory and payment effects. [C5] [C6] | Seed orders with different eligibility states and derive permitted changes from the shop’s policy. | Check order changes, eligibility, inventory, and payment effects; verify that unrelated orders remain unchanged. | **Moderate / Exact.** |
| 21 | After-sales | **Returns, exchanges, and refunds.** E: Request a return for a damaged mug. H: Exchange a shirt's size, return one of two mugs, and explain why another line is ineligible. | Easy–Hard | **Missing:** return, exchange, and refund actions need support; policy lookup already exists. [C1] [C6] | Build scenarios from purchased items, dates, reasons, policy exceptions, and replacement stock. | Check each line’s status, amount, and inventory effects; evaluate policy rules and the explanation. | **Moderate–High / Mixed.** |
| 22 | After-sales | **Review submission and management.** E: Submit a four-star review using my supplied feedback. M: Update my own review after a replacement while preserving its purchase relationship. | Easy–Medium | **Missing:** reviews need records, authorship and purchase links, mutations, and UI. [C6] [C10] | Seed an authenticated customer, purchase, and optional existing review; generate edits from user-supplied feedback. | Check authorship, purchase links, rating, and updates; use an LLM judge to check fidelity to the supplied feedback. | **Low / Exact; High / Mixed** for text. |
| 23 | After-sales | **Subscriptions and recurring replenishment.** M: Set coffee delivery to every four weeks. H: Skip the next shipment and reduce future quantity while keeping the subscription active. | Medium–Hard | **Later:** subscription records, recurring schedules, and UI are absent. [C6] [C10] | Define subscription transitions with a controlled clock and an expected future shipment schedule. | Query subscription state and scheduled shipments; check recurrence calculations and preserved history. | **Moderate / Exact.** |
| V1 | Scenario variation | **Personalization and memory.** M: Use the size from my last purchase. H: Recommend items respecting preferences supplied across earlier sessions. | Medium–Hard | **Partial:** customer and order history exist; preference memory and control across sessions do not. [C2] [C6] | Fix shopper preferences, history, and the information available in each session before generating a personalized request. | Check history and preference constraints; judge soft preferences and verify which memory the agent could access. | **Moderate–High / Mixed.** |
| V2 | Scenario variation | **Clarification and confirmation.** M: Clarify which coffee I mean by “my usual.” H: Resolve an ambiguous delivery address and obtain the required confirmation before order placement. | Medium–Hard | **Missing:** the runner needs shopper dialogue, rules for revealing hidden requirements, and confirmation checks. [C2] [C12] | Withhold a required field from a feasible task; define the shopper’s answers and disclosure rules before the run. | Check questions, answers, and confirmation order against the disclosure log and final task state. | **High / Exact or Mixed.** |
| V3 | Scenario variation | **Incremental requirement changes.** M: Switch my coffee request to decaf mid-task. H: Tighten the budget after a proposed shopping cart and preserve the remaining requirements. | Medium–Hard | **Missing:** the runner needs controlled follow-up messages and versioned requirements. [C2] [C12] | Define a requirement change and its trigger before the run; validate a solution under the revised requirements. | Check when the change was disclosed, which requirements were active, and whether obsolete choices were removed. | **High / Exact or Mixed.** |
| V4 | Scenario variation | **Infeasibility and recovery.** M: Report that no available product meets all constraints without purchasing. H: Recover from an insufficient-stock checkout error by selecting an allowed alternative. | Medium–Hard | **Partial:** checkout can reject insufficient stock; task generation and controlled failure injection need work. [C5] | Prove that no product matches, or seed a stock shortage; specify permitted alternatives for recovery. | Check the infeasibility proof or observed error, final state, preserved records, and explanation. | **Moderate–High / Mixed.** |
| V5 | Scenario variation | **Action boundaries and collateral effects.** E: Research options without changing my shopping cart. H: Update only the specified address while preserving every unrelated address and order. | Easy–Hard | **Partial:** snapshots exist; general state comparisons and checks for transient actions do not. [C3] [C6] | Define permitted changes and forbidden actions; seed unrelated records whose state must be preserved. | Compare initial and final state; use trusted events to check forbidden actions and required confirmation order. | **Low–Moderate / Exact; High / Mixed** for traces. |
| V6 | Scenario variation | **Cross-shop shopping.** M: Compare the delivered price of the same product at two shops. H: Split a compatible shopping cart across shops while including separate shipping charges. | Medium–Hard | **Later:** coordinated setup and grading across shops are absent. [C2] [C12] | Align product identities across validated catalogs; calculate fees and a feasible allocation of purchases. | Query prices and state across shops; check equivalence and compatibility, and optimize within a bounded allocation space. | **Moderate–High / Exact or Mixed.** |

### Generation methods

The generation method depends on the success conditions. Product discovery uses
catalog facts, shopping cart edits use state changes, and recommendations connect
product evidence to a shopper’s purpose. We propose five methods:

- **Catalog- or answer-first generation** derives requirements from verified
  product facts and calculates all valid matches. This suits discovery,
  comparison, and compatibility tasks with explicit constraints.
- **State-transition templates** define the initial records, requested changes,
  and records that must remain unchanged. They suit shopping cart edits, account
  operations, checkout, and eventually after-sales workflows.
- **Needs-first generation** starts with a shopper’s purpose and preferences,
  then identifies products supported by catalog evidence. Recommendations use
  explicit suitability criteria alongside exact budget and stock checks.
- **Witness-first generation** validates a feasible selection before deriving the
  request and budget. It suits multi-item planning, where independently sampled
  constraints can easily produce an impossible task.
- **Exploration of supported functionality** discovers goals from a shop’s actual
  pages and controls. The explorer would produce a replayable solution and
  independent success checks before adding the task to the benchmark.

The methods share validation and metadata. Trajectory synthesis, state-machine
search, and joint generation of environments, tasks, and verifiers offer further
options for discovery and domain expansion. The research comparison is in
[Appendix B](#b-generation-methods-and-research-rationale).

### Task generation and validation

The pipeline produces a shopper request and a separate validation record:

```mermaid
flowchart LR
    A[Shop data and supported actions] --> B[Task family and difficulty]
    B --> C[Initial state, constraints, solution, verifier]
    C --> D[Shopper request]
    D --> E[Independent replay and verifier tests]
    E --> F[Coverage review and benchmark inclusion]
```

Task metadata records category, family, variations, difficulty, generation
method, required capabilities, verification requirements, and source provenance.
Reference answers, witnesses, and hidden requirements stay outside the visible
request. The metadata and interaction protocol require schema extensions. [C2]

A candidate enters the benchmark after four validation steps:

1. **Validate evidence and actions.** Every required fact must be accessible
   through the permitted UI, and every required action must work in that shop.
   A task about sizing, for example, needs an accessible size chart.
2. **Establish feasibility.** Query or solve the constraints independently and
   replay a solution in a fresh episode. For an impossible request, retain an
   empty-result proof or conflicting constraints; an agent’s refusal alone does
   not establish infeasibility.
3. **Test the verifier.** Confirm that it accepts valid alternatives and rejects
   targeted mistakes, such as the wrong variant, an extra line, a stale order,
   an incorrect total, or an unintended change to another record.
4. **Review realism and coverage.** Requirements must be stated or discoverable
   within a plausible shopper request. Product swaps and paraphrases create new
   instances, but do not establish new coverage of goals, evidence, or workflows.

### Verification and coverage

Structured facts and state changes use deterministic checks. For example, a
shopping cart verifier compares variant IDs and quantities, while a checkout
verifier identifies the newly created order and checks its lines and total.
Recommendations and policy explanations also use an LLM judge supplied with the
relevant evidence. Hard constraints are checked separately so a convincing
explanation cannot compensate for an invalid product or order.

A witness proves feasibility; all valid outcomes remain acceptable. Temporal
requirements, such as confirmation before purchase, need trusted events. A final
snapshot cannot show whether an item was temporarily added and removed.
Interactive requirements and disclosure rules must be fixed before the run.
[Appendix C](#c-verifier-design-notes) covers these extensions and domain-specific cases.

Coverage reports would break results down by family, difficulty, and scenario
variation, with additional views of product domains, evidence sources, initial
states, and interacting constraints. Where appropriate, tasks would include ties,
multiple valid outcomes, impossible requests, and recoverable errors. Simple
operations do not need artificial Hard variants. Pilot runs and human review
would calibrate the difficulty labels and distinguish environment failures from
agent failures. Family weights and sample counts remain open until the pilot;
frequent discovery tasks should not dominate the aggregate score simply because
they are easier to generate.

## Alternative

Expanding only the deterministic seeds would be the smallest implementation
change. It fits exact discovery and simple state changes, but would continue to
underrepresent suitability, trade-offs, and interaction. Using one LLM to
generate every task and judge every result would cover more language and goals,
but would make feasibility and state correctness harder to establish.

Combining methods requires maintaining exact verifiers and semantic rubrics,
but supports realistic decisions while keeping structured commerce outcomes
independently checkable.

## Execution Table

The rollout starts with existing capabilities and adds domains independently.
Each phase would generate only tasks supported by the target shop. This proposal
defines scope and sequencing; generator implementation remains separate.

| Phase | Proposed scope | Required work | Completion criteria |
| --- | --- | --- | --- |
| 1. Baseline pilot | 01–02, 08–10, 14–15, basic 18–19; supported subsets of 04–06, V4–V5 | Add task metadata, generators, and checks for exact lines, new orders, and preserved records. Exercise existing authentication. | Replay tasks in fresh episodes; accept valid alternatives; reject targeted errors; validate infeasible cases; report coverage. |
| 2. Richer decisions | 03–06, 11; complex 02, 08, 18–19 | Validate product attributes, compatibility, and policies; add solution search, calculations, and semantic rubrics. | Independently audit feasibility and evidence, and calibrate semantic checks against human judgments. |
| 3. Interactive scenarios | V1–V5 on supported base families | Add shopper dialogue, disclosure rules, controlled changes, memory fixtures, and event checks. | Replay scripted interactions, verify event order, and measure user-simulator violations. |
| 4. Commerce workflows | 07, full 12–13, 16–17, refund-aware 18, 20–22 | Add each domain’s records, rules, mutations, and UI before its generator. | Validate the domain contract, browser workflow, and verifier for each family. |
| 5. Later expansion | 23, V6 | Add subscription schedules and coordinated episodes across shops. | Review domain semantics and verify isolation, replay, and calculations across domains. |

The remaining design decisions are the pilot’s allocation across families and
tiers, how subjective scores contribute to the aggregate metric, and which
missing commerce workflow to prioritize first.

## Appendix

### A. Baseline capability audit

The support assessment uses the shared backend and storefront template on
`v2/5-cutover`. It is based on static code inspection. Generated shops can expose
fewer features or extend the backend, so each shop needs its own data and browser
validation before receiving tasks.

The baseline provides:

- Ten deterministic seed skills: `exact`, `substitute`, `browse`, `filter`,
  `shipping`, `returns`, `e2e`, `account`, `checkout`, and `order_history`.
  These names cover narrower behavior than some proposed families: `returns`,
  for example, locates a policy page rather than executing a return. [C1]
- Shopping carts isolated by episode, customer registration, access-token login
  and logout, customer and address reads, order history, simulated order
  placement, inventory changes, reset, and grader snapshots. [C4] [C5] [C6] [C9]
- `string_match`, `url_match`, `locator_probe`, `state_check`, and explicit
  `llm_judge` checks. `state_check` supports equality, subsets, and array
  membership. All configured checks must pass. Fuzzy text matching also invokes
  a judge. [C2] [C3]
- An explorer that proposes tasks and checks page reachability and locators in a
  fresh browser. It does not replay a full solution or establish feasibility
  and semantic correctness for every check type. [C11]

The following limits affect the proposed catalog:

- Account seeds start signed in. Registration, login, and logout need dedicated
  generators and checks. Profile and address editing, default-address changes,
  and saved-payment management also need mutations and UI. [C1] [C4] [C9]
- Checkout uses configured shipping and payment handles with simulated payment.
  Pricing supports flat tax and shipping rates and a free-shipping threshold.
  Discount codes are stored and reported as applicable, but have no eligibility
  checks or price effects. Delivery dates, geographic eligibility, and pickup
  slots are absent from commerce settings. [C5] [C7] [C8] [C10]
- The shared state and schema have no wishlist, review, subscription,
  cancellation, return, exchange, or refund workflows. A seeded financial-status
  label does not provide the records needed to calculate partial refunds. [C4] [C6] [C10]
- The task contract has one goal, optional login and shopping cart setup, and
  evaluation checks. It lacks typed difficulty, generation-method metadata,
  shopper dialogue, disclosure rules, and a memory contract across sessions. [C2] [C12]
- Built-in grading lacks arbitrary constraint queries, optimization, state diffs,
  and event-order checks. The judge receives the goal, rubric, final answer and
  URL, prior check results, and an optional final screenshot. Supplying source
  evidence and interaction history requires additional plumbing. [C3] [C12]

### B. Generation methods and research rationale

The papers below motivate the proposed methods. Their application to task
families in the catalog is a ShopGym design proposal.

1. **Scenario templates.** AppWorld pairs scenario setup and solutions with
   programmatic assertions. This provides a useful pattern for account actions,
   shopping cart edits, checkout, and after-sales: define the initial records,
   permitted changes, and expected outcome before producing the request.
   [AppWorld](https://arxiv.org/html/2407.18901)
2. **Catalog- or answer-first generation.** ShoppingBench samples products,
   extracts fields, and writes grounded queries. EComAgentBench fixes the answer
   and typed rubrics before generating language, then distributes requirements
   across the query, profile, and clarification. In ShopGym, the generator would
   evaluate the constraints over the catalog and retain all valid matches.
   [ShoppingBench](https://arxiv.org/html/2508.04266v1),
   [EComAgentBench](https://arxiv.org/html/2606.17698v1)
3. **Needs-first generation.** EcomScriptBench connects user objectives, script
   steps, purchase intentions, and products. That connection can inform
   recommendations and substitutes, provided each task also has catalog evidence
   and explicit criteria for assessing suitability.
   [EcomScriptBench](https://arxiv.org/html/2505.15196v1)
4. **Witness-first generation.** ComboShoppingBench validates a feasible shopping
   cart before deriving coupons, budget, query, and rubrics. This avoids
   impossible combinations of independently sampled requirements. Its coupon
   optimum is calculated for the submitted shopping cart; finding the best
   product selection requires a separate objective and candidate space. Other
   selections satisfying the task remain valid.
   [ComboShoppingBench](https://arxiv.org/html/2608.09282v1)
5. **Exploration of supported functionality.** Amazon-Bench grounds queries in
   page content and interactive elements, followed by refinement and review.
   ShopGuru’s explorer could follow this pattern with added solution replay and
   independent assertions before benchmark inclusion.
   [Amazon-Bench](https://arxiv.org/html/2508.15832v1), [C11]
6. **Trajectory synthesis.** NNetNav labels explored trajectories. SynWeaver uses
   website maps, reverse synthesis, refinement, and verification. These methods
   can discover workflows and produce training demonstrations. For evaluation,
   ShopGym would also need to reconstruct the initial state and check success
   independently of the trajectory used to generate the task.
   [NNetNav](https://arxiv.org/html/2410.02907v1),
   [SynWeaver](https://arxiv.org/html/2608.12429v1)
7. **State-machine search.** AutoWebWorld uses finite-state machines and graph
   traversal to obtain reachable goals and trajectories. After modeling a
   commerce domain, ShopGym could use this method to compose workflows. Browser
   replay would still need to establish that the UI implements those transitions.
   [AutoWebWorld](https://arxiv.org/html/2602.14296v1)
8. **Joint generation of environments, tasks, and verifiers.** VeriEnv and
   WebArena Infinity provide precedents for generating executable environments
   with verifiable tasks. This could help add missing commerce domains. Generated
   validators would need review against the domain contract and tests with valid
   alternatives and deliberately wrong outcomes, since the same generation error
   can affect both the task and its verifier.
   [VeriEnv](https://github.com/kyle8581/VeriEnv),
   [WebArena Infinity](https://github.com/web-arena-x/webarena-infinity)

For V1–V3, the proposed approach starts with a grounded base task and defines
preferences, hidden requirements, and changes before interaction. Work on
long-horizon shopping personalization motivates testing consistency across
interactions; ShopGym would need the runner protocol described above to support
such evaluations.
[Personalization Matters](https://arxiv.org/html/2610.11375v1)

### C. Verifier design notes

Deterministic verifiers would query structured facts and compare initial and
final state. Shopping cart checks compare variant IDs and quantities as a
multiset. Order checks identify records created during the episode. Monetary
calculations use integer minor units and the shop’s declared pricing rules.
These checks establish the actual outcome: displaying a product title alone does
not establish the correct variant or quantity, and storing a coupon code does
not establish a discount.

The proposed grader extensions cover constraints, aggregation, optimization, and
state differences. Existing checks remain useful for narrower goals: URLs for
navigation, literal matching for unambiguous reported facts, and locators for
required UI evidence. Current task validation checks schemas, references, and
exact duplicate goals; it does not establish the stronger properties proposed
here. [C2] [C3] [C13]

An LLM judge would receive relevant source records or passages and a rubric that
separates the criteria being assessed. Exact constraints would have their own
checks. Before relying on subjective scores, a human-labeled sample would be
used to measure agreement and inspect false positives and false negatives.
Reporting exact and semantic components separately would make these limitations
visible in benchmark results.

Temporal requirements need trusted events for account access, confirmation,
disclosure of requirements, and forbidden actions. The runner records agent
trajectories, but a trusted event schema and corresponding grader predicates are
still proposed extensions. Snapshots establish final-state properties; events
are needed to determine what happened during the episode. [C6] [C12]

Some families need additional definitions before their verifiers can be built:

- **Promotions (12):** optimality must specify either coupon choice for a fixed
  shopping cart or product selection within a bounded candidate set.
- **Order spending (18):** the reference calculation needs a time window,
  gross or net accounting, partial-refund records, and rules for allocating tax
  and shipping.
- **Account access (15):** checks need browser session effects as well as backend
  state. Ending signed out does not establish that login and the requested read
  occurred. Password recovery and OTP are outside the baseline authentication surface.
- **Interactive variations (V1–V3):** a versioned log records active requirements
  and their disclosure. The simulator’s answers and timing need validation
  separately from the agent’s final outcome. Hidden facts must be recoverable
  through permitted observations.
- **Subscriptions and cross-shop tasks (23, V6):** recurrence and billing rules,
  product equivalence, and coordinated episode isolation need definitions before
  generation.

### D. Code evidence

These links refer to the implementation inherited from the audited baseline.
They support the current-state and support assessments in this proposal.

- [C1: Seed generators][C1] — the behavior of each existing seed family.
- [C2: Task and check schema][C2] — setup, goal, provenance, and evaluation fields.
- [C3: Grading dispatcher][C3] — check behavior and judge inputs.
- [C4: Customer schema][C4] — authentication mutations and profile and address reads.
- [C5: Checkout resolver][C5] — validation, commerce settings, and simulated placement.
- [C6: Episode snapshot][C6] — customer, session, shopping cart, order, and inventory
  state; [state transitions](../../../packages/shop_backend/src/state/shop_state.ts).
- [C7: Pricing][C7] — flat tax and shipping calculations and the free-shipping threshold.
- [C8: Shopping cart resolver][C8] — mutations and placeholder discount-code behavior.
- [C9: Account routes][C9] and [checkout route](../../../packages/shop-arena/templates/storefront/app/routes/checkout.tsx).
- [C10: Dataset schemas][C10] — catalog, customer, order, and commerce data contracts.
- [C11: Explorer verification][C11] — page and locator checks.
- [C12: Agent-under-test runner][C12] and
  [episode execution](../../../packages/shop-guru/src/solve/solve.ts).
- [C13: Task validation][C13] — schema and reference checks, goal deduplication, and caps.

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

Method selection builds on the
[previous ShopGym research review](https://shop-gym.quick.shopify.io/public/specs/docs/shop-gym/shopgym_v2/shopgym_v2_task_research_review.html#methods)
and the primary papers and repositories above, including 2026 work through
October. The hosted review redirected to authentication during this research;
its local counterpart was available as context, but is not part of the base
branch. Current support was assessed from code. This is a focused synthesis for
the proposed catalog; the cited benchmark results have not been replicated.
