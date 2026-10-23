# Shopping Task Generation Proposal

Status: **Proposed**. Audience: **ShopGym developers**.
Estimated reading time: **15–20 minutes**, excluding the appendix.
Support baseline: existing implementation at
[`230c185a`](https://github.com/agentic-foundation-modeling-research/shop-gym/commit/230c185a6fd7f1616bb18cdf276d451f03c976ab),
reviewed on 2026-10-22; account support rechecked on 2026-10-23.

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
Task generation combines parameterized shopper scenarios with product- or
answer-first construction. An exploration agent and BFS build an interaction
graph on each generated SandboxShop, recording typical pages, key states, and
interactive elements. The graph grounds the workflows available to each scenario.

ShopGym v2 development will add the commerce workflows and runner features
needed for the broader catalog. Task generation will expand coverage of existing
commerce operations and add tasks as those v2 features become available.

## Terminology

A **task family** describes a type of shopper goal; its **category** identifies
the shopping stage. A **scenario variation** adds a condition such as clarification
or recovery. A **validated solution** demonstrates that a task can be completed;
the verifier also accepts other outcomes meeting the same requirements.

Verification difficulty describes the work needed to determine success:
**Low** for direct checks, **Moderate** for joins and calculations, and **High** for
semantic or interaction assessment. Objectivity is **Exact**, **Mixed** when exact
and semantic checks are combined, or **Rubric-based** when success depends on
subjective judgment. Task difficulty and verification difficulty are independent:
a difficult optimization task can still have an exact verifier.

A **database query** in the catalog means a query over catalog records, seeded
records, or episode snapshots. It does not require a SQL service.

## Current Status

The existing implementation has ten seed skills and supports episode-isolated
shopping carts, customer and address reads, order history, simulated checkout,
and inventory changes. Grading supports text, URL, locator, snapshot, and opt-in
LLM checks. [C1] [C3] [C4] [C5] [C6]

The backend and shared storefront template implement registration,
password-based login, and logout. The task runner can sign in before the agent
starts; the current `account` seed uses this setup and only asks the agent to
read profile information. Registration, login, and logout therefore have
environment support but no dedicated seed tasks or success checks. Each generated
shop still needs validation of its account pages and seeded credentials.
[C1] [C9] [C14] [C15]

The current explorer proposes tasks and rechecks page reachability and locators.
It does not persist a page-state interaction graph or validate full workflows.
Browser snapshots and episode reset/state APIs provide inputs for the proposed
graph builder. [C11] [C17] [C18] [C19]

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

### Selected generation design

We will combine **1. Human-authored tasks / parameterized scenarios**,
**2. Product- or answer-first generation**, and
**5. Page-functionality-first generation + 7. Site-graph / state-machine search**.
The numbers refer to the eight approaches compared in
[Appendix B](#b-existing-work-and-task-generation-approaches).

| Selected approach | Role in the pipeline | Output |
| --- | --- | --- |
| **5 + 7: Page functionality and graph search** | An exploration agent inspects a generated SandboxShop while BFS schedules unexplored pages and states. It records interactive elements and tests transitions. | A reusable interaction graph, page capabilities, and replayable paths. |
| **2: Product or answer first** | Bind products, variants, policy facts, customer records, or orders to requirements; compute the valid answers and outcomes. | Grounded parameters, constraints, and supporting evidence. |
| **1: Parameterized scenarios** | Define realistic shopper goals, required capabilities, initial state, requested changes, and success conditions. | A task instance combining a scenario, grounded data, and a supported workflow. |

An LLM writes the request after grounded requirements and success conditions
have been established.

```mermaid
flowchart TD
    A[Generated SandboxShop] --> B[Agent + BFS: methods 5 + 7]
    B --> C[Interaction graph]
    D[Product and answer data: method 2] --> E[Construct task and verifier]
    F[Scenario templates: method 1] --> E
    C --> E
    E --> G[Write shopper request]
    G --> H[Replay, verifier tests, and difficulty annotation]
    H --> I[Benchmark inclusion]
```

### Explore the SandboxShop and build the interaction graph

Exploration runs on the **generated SandboxShop**, using representative home,
collection, search, product, shopping cart, policy, account, and checkout pages.
The agent inspects content and interactive elements, supplies meaningful inputs,
and interprets observed results. BFS maintains the frontier and visited set,
expanding discovered states in order of depth.

A node represents a **page type and key interaction state**: for example, an
empty or populated shopping cart, or a signed-out or signed-in account. Product
and order IDs remain parameters. Pages with different controls or behavior are
split even when their URL patterns match.

Record each control's name, type, input requirements, and enabled state. Test
actions from reproducible source states and record resulting UI and backend
changes. Untested controls remain discovery candidates. The graph supports
workflow search within recorded exploration bounds; task verifiers check actual
answers and commerce outcomes.
[Appendix G](#g-interaction-graph-and-exploration-details) specifies records,
branch replay, deduplication, and coverage boundaries.

### Construct tasks from the graph, data, and scenarios

1. **Select a scenario and supported workflow.** The scenario defines the goal,
   required capabilities, initial state, and permitted changes. Match these to
   graph transitions; compose supported actions for longer workflows. An
   uncovered capability triggers further exploration or defers the candidate.
2. **Bind grounded parameters.** Sample products, variants, policies, customers,
   and orders; derive satisfiable constraints and valid outcome predicates.
   Recommendation scenarios supply a purpose and suitability rubric, with
   product evidence supporting each claim. Multi-item scenarios need a feasible
   selection.
3. **Write the request.** Verbalize the fixed requirements as a shopper goal.
   Keep reference answers, replay paths, and verifier details in the validation
   record. The agent chooses its own valid route and solution.

For “Replace the large coffee pack with two small packs and keep everything
else,” the graph supplies observed quantity/removal controls, the catalog supplies
variants, and the scenario supplies the initial shopping cart and preservation
rule. The verifier checks the resulting lines and quantities.

Metadata records the scenario, method IDs, required capabilities, shop/graph
version, source records, and verification requirements. These fields require task
schema extensions. [C2]

### Validate generated candidates

Each candidate enters the benchmark after four checks:

1. **Evidence and action support.** Required facts must be accessible through the
   permitted UI, and required actions must work with the bound parameters. A
   size-selection task needs an accessible size chart; a representative product
   transition does not establish that every variant is purchasable.
2. **Feasibility and replay.** Independently query or solve the constraints and
   replay a solution in a fresh episode. Graph paths provide candidates for this
   replay. For an impossible request, retain an empty-result proof or conflicting
   constraints and review an evidence-gathering run.
3. **Verifier tests.** Accept valid alternatives and reject targeted mistakes:
   wrong variants, extra lines, stale orders, incorrect totals, and unintended
   changes to unrelated records. Exact checks and semantic rubrics are tested
   separately.
4. **Realism and coverage.** Confirm that the request expresses a plausible need
   and that its requirements are stated or discoverable. Record its family,
   variations, reference action count, difficulty, and required abilities.

### Task difficulty

We propose reusing the **action-difficulty** bands from
[VisualWebArena §4.2](https://arxiv.org/html/2401.13649#S4.SS2), based on the
estimated number of browser actions a human needs to complete a task:

- **Easy:** 3 or fewer actions.
- **Medium:** 4–9 actions.
- **Hard:** 10 or more actions.

For ShopGym, an efficient, human-reviewed reference replay supplies the count.
Record the initial page, login and shopping cart state, and action interface.
Count individual browser operations; exclude setup, observations, and evaluated
agent retries. Graph edges can contain multiple operations, so graph distance
does not set the tier.

Separately record the abilities a task requires, drawing on
[WorkArena++ §3.2](https://arxiv.org/html/2407.05291#S3.SS2): planning, information
retrieval, data-driven reasoning, memory, and contextual understanding. A short
compatibility query can require substantial reasoning; a long form can require
little.

Catalog ranges are **generation targets**, not measured labels for the examples.
Each instance receives its tier after reference replay.
[Appendix F](#f-difficulty-definitions-and-annotation) compares published definitions
and specifies counting rules.

### Unified task catalog

The catalog compares target behavior, support gaps, and verification requirements.
Generators can instantiate an example only when its required facts and actions
exist in the target shop. Each row gives two separate example requests.

**Basic** means the core operations exist, **Partial** means a useful subset
exists, and **Missing** means the core workflow needs implementation. **Later**
identifies expansion beyond the initial single-shop scope. These labels describe
environment support, not completed generators or verifiers. Rows V1–V6 are
scenario variations that can be combined with the base families.

| ID | Category | Task family and realistic examples | Target difficulty range | Current ShopGym support and gaps | Proposed task generation approach | Required verifier(s) | Verification difficulty / objectivity |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | Discovery and decision | **Known-item discovery.**<br>Find the TrailLite 20L backpack.<br>Find its available navy variant, distinguishing it from the older model. | Easy–Medium | **Basic:** search and variant selection exist; current seeds accept any variant. [C1] | Sample an available product and similar models, then derive identifying attributes from the catalog. | Query product and variant IDs; check the answer or URL, and shopping cart contents when requested. | **Low / Exact.** |
| 02 | Discovery and decision | **Constraint-based discovery.**<br>Find a cotton shirt under $30.<br>Find black, machine-washable trousers in my size under $80, excluding wool. | Easy–Hard | **Partial:** filters exist; combined constraints and evidence for care instructions or materials need stronger checks. [C1] [C10] | Derive constraints from a feasible item, then enumerate all matching products and near misses. | Query attributes, price, size, and stock; check supporting text for claims outside structured fields. | **Low–Moderate / Exact; Mixed** for prose. |
| 03 | Discovery and decision | **Recommendations for a purpose or occasion.**<br>Suggest a housewarming gift under $25.<br>Choose a gift for a beginner gardener with a small balcony and no storage space. | Easy–Hard | **Partial:** browsing exists; generation from shopper needs and suitability rubrics are absent. [C1] | Sample a shopper need and preferences; identify suitable products using catalog evidence and an explicit rubric. | Check budget and stock with queries; use an LLM judge to assess suitability and the explanation. | **High / Rubric-based.** |
| 04 | Discovery and decision | **Comparison and value.**<br>Which of two coffee packs is cheaper per kilogram?<br>Compare three backpacks on capacity, weight, price, and warranty using my stated priorities. | Easy–Hard | **Partial:** prices and descriptions exist; unit conversion, warranty evidence, and comparison checks need work. [C10] | Select candidates and shopper priorities; calculate comparable values and rankings before writing the request. | Check facts, unit conversions, and rankings; use an LLM judge for qualitative trade-offs. | **Moderate / Exact or Mixed.** |
| 05 | Discovery and decision | **Substitution and unavailability.**<br>Find a cheaper alternative to this mug.<br>My preferred shoe is unavailable; preserve size, material, and fit within budget. | Easy–Hard | **Partial:** similarity seeds and stock data exist; substitutes need checks for the attributes the shopper wants to preserve. [C1] | Select an original item, specify which attributes can change, and enumerate available alternatives. | Query price, stock, and required attributes; exclude the original item; judge functional similarity when needed. | **Moderate–High / Mixed.** |
| 06 | Discovery and decision | **Sizing, fit, and compatibility.**<br>Use my measurements and the size chart to choose a shirt size.<br>Find a replacement filter for my exact appliance model and reject a similar incompatible filter. | Medium–Hard | **Partial:** descriptions and options exist; reliable size charts and compatibility data depend on the shop. [C10] | Validate size charts or model compatibility data, then sample valid choices and similar but invalid choices. | Query size ranges or compatibility relations; assess fit claims and uncertainty against the source evidence. | **Moderate / Exact; Mixed** for fit. |
| 07 | Discovery and decision | **Review-grounded research.**<br>Summarize recurring sizing complaints for these shoes.<br>Compare recent verified-purchase reviews, distinguishing repeated defects from isolated complaints. | Medium–Hard | **Missing:** review records, filtering, and review pages need support. [C10] | Prepare dated reviews with purchase flags and recurring or conflicting findings, then generate research questions. | Query the relevant reviews and check cited passages; use an LLM judge to assess whether the summary represents them faithfully. | **High / Mixed.** |
| 08 | Discovery and decision | **Policy and store information.**<br>What is the return window?<br>For a discounted gift shipped internationally, explain the applicable shipping and return conditions. | Easy–Hard | **Partial:** policy pages and navigation seeds exist; answers and policy exceptions need additional checks. [C1] | Extract rules, exceptions, and supporting passages; calculate the applicable outcome for a shopper scenario. | Evaluate policy rules and calculations; judge answers against source passages. Use URL checks for navigation-only goals. | **Low / Exact** to **High / Mixed.** |
| 09 | Shopping cart and purchase | **Variant and quantity selection.**<br>Add two blue mugs.<br>Add one medium black shirt and two large white shirts, using available variants only. | Easy–Hard | **Basic:** variant selection and shopping cart mutations exist; seeds need exact quantity and variant checks. [C1] [C8] | Sample available variants and quantities, then generate a request for those items. | Compare shopping cart lines by variant ID and quantity, including checks for unwanted items. | **Low / Exact.** |
| 10 | Shopping cart and purchase | **Shopping cart revision.**<br>Remove the duplicate mug.<br>Replace the large pack with two small packs, preserve all other lines, and keep the total under $70. | Easy–Hard | **Basic:** shopping cart setup and mutations exist; revision tasks need before-and-after checks. [C2] [C8] | Seed an initial shopping cart and define the requested changes, budget, and items that must remain unchanged. | Compare initial and final shopping carts; calculate the total and check preserved lines. | **Low–Moderate / Exact.** |
| 11 | Shopping cart and purchase | **Multi-item shopping cart planning.**<br>Choose a notebook and pen for under $20.<br>Build a cooking kit for four campers, covering required roles with compatible items within budget. | Medium–Hard | **Partial:** multi-item shopping carts exist; planning needs checks for required functions, compatibility, and the complete selection. [C1] | Validate one feasible shopping cart before deriving the request and budget; retain success conditions independent of that solution. | Check quantities, budget, required functions, and compatibility; judge suitability where product facts require interpretation. | **Moderate–High / Exact or Mixed.** |
| 12 | Shopping cart and purchase | **Promotions and total-cost optimization.**<br>Apply an eligible 10% coupon.<br>Choose the best legal coupon combination for my shopping cart, including shipping and a useful threshold top-up if it lowers the payable total. | Medium–Hard | **Partial:** tax and shipping calculations work; coupon eligibility, discounts, and stacking rules are missing. [C7] [C8] | Define promotion rules and a feasible shopping cart; compute the optimum within an explicit set of candidate choices. | Use pricing calculations, eligibility rules, and an optimizer; check that any added item serves the stated need. | **Moderate–High / Exact.** |
| 13 | Shopping cart and purchase | **Delivery, pickup, and deadlines.**<br>Does the shop deliver to my country?<br>Find the cheapest option arriving before Friday, with pickup as a fallback. | Easy–Hard | **Partial:** policies and flat shipping rates exist; destination eligibility, arrival dates, and pickup need support. [C5] [C10] | Generate policy questions first; after extending logistics, sample destinations, deadlines, and feasible delivery or pickup slots. | Check policy evidence, destination eligibility, dates, and the selected delivery or pickup option. | **Moderate / Exact; Mixed** for prose. |
| 14 | Shopping cart and purchase | **Checkout and order placement.**<br>Complete guest checkout for this shopping cart using supplied details.<br>Place the order to my office with the specified shipping and payment options and final amount. | Medium–Hard | **Basic:** simulated guest and customer checkout exist; the current seed starts signed in with a prefilled shopping cart. [C1] [C5] | Seed the shopping cart and customer details; calculate the expected total and order state after checkout. | Identify the new order; check lines, customer details, shipping and payment options, total, and inventory. Reject duplicate orders. | **Low–Moderate / Exact.** |
| 15 | Accounts and repeat shopping | **Account access.**<br>Register with these details without marketing opt-in.<br>Sign in, report the default-address city, then sign out. | Easy–Medium | **Basic:** backend and template routes implement registration, password login, and logout. The runner signs in for the account seed; these actions need dedicated tasks and checks. [C9] [C14] [C15] | Seed credentials or an unused email and define the expected account and session changes. | Check customer records, marketing consent, browser session state, and the required sequence of account actions. | **Low–Moderate / Exact.** |
| 16 | Accounts and repeat shopping | **Profile, addresses, and payment preferences.**<br>Save my office address.<br>Make it the default for future purchases, remove an obsolete address, and preserve existing orders. | Easy–Hard | **Missing for edits:** profile and address reads exist; editing, default selection, and saved-payment management need mutations and UI. [C4] [C9] | Seed customer records and define the intended edits and records that must remain unchanged. | Compare profile, address, and payment records; check the default address reference and preservation of existing orders. | **Low–Moderate / Exact.** |
| 17 | Accounts and repeat shopping | **Wishlist and saved plans.**<br>Save these two products for later.<br>Move available saved items below $30 into my shopping cart while retaining unavailable items in the wishlist. | Easy–Hard | **Missing:** wishlist records, persistence, mutations, and UI need support. [C6] | Seed saved items and derive the requested changes from stock and price constraints. | Compare wishlist and shopping cart contents; check quantities, retained items, and duplicates. | **Low–Moderate / Exact.** |
| 18 | Accounts and repeat shopping | **Order lookup, status, and spending.**<br>Report my latest order status.<br>Calculate kitchen-category spending last quarter after partial refunds. | Easy–Hard | **Partial:** order history and detail seeds exist; aggregate checks and a partial-refund ledger need adding. [C1] [C6] | Seed dated orders with product categories and calculate reference totals; include refunds once the ledger exists. | Query the customer’s orders by date and category; calculate spending using the declared refund rules. | **Low–Moderate / Exact.** |
| 19 | Accounts and repeat shopping | **Reordering.**<br>Add the coffee from my last order to my shopping cart.<br>Repeat the office order without pens, double the paper, and substitute an unavailable item. | Easy–Hard | **Partial:** order history, shopping carts, and checkout exist; reordering needs generation and stock-aware checks. [C6] [C8] | Start from a previous order, apply exclusions and quantity changes, then validate available substitutes. | Compare the shopping cart or new order with the source order; check quantities, exclusions, stock, and substitutions. | **Moderate / Exact or Mixed.** |
| 20 | After-sales | **Order modification and cancellation.**<br>Cancel my unshipped order.<br>Cancel only the duplicate order and change the other order's address if policy permits. | Easy–Hard | **Missing:** order editing and cancellation need lifecycle rules, mutations, and inventory and payment effects. [C5] [C6] | Seed orders with different eligibility states and derive permitted changes from the shop’s policy. | Check order changes, eligibility, inventory, and payment effects; verify that unrelated orders remain unchanged. | **Moderate / Exact.** |
| 21 | After-sales | **Returns, exchanges, and refunds.**<br>Request a return for a damaged mug.<br>Exchange a shirt's size, return one of two mugs, and explain why another line is ineligible. | Easy–Hard | **Missing:** return, exchange, and refund actions need support; policy lookup already exists. [C1] [C6] | Build scenarios from purchased items, dates, reasons, policy exceptions, and replacement stock. | Check each line’s status, amount, and inventory effects; evaluate policy rules and the explanation. | **Moderate–High / Mixed.** |
| 22 | After-sales | **Review submission and management.**<br>Submit a four-star review using my supplied feedback.<br>Update my own review after a replacement while preserving its purchase relationship. | Easy–Medium | **Missing:** reviews need records, authorship and purchase links, mutations, and UI. [C6] [C10] | Seed an authenticated customer, purchase, and optional existing review; generate edits from user-supplied feedback. | Check authorship, purchase links, rating, and updates; use an LLM judge to check fidelity to the supplied feedback. | **Low / Exact; High / Mixed** for text. |
| 23 | After-sales | **Subscriptions and recurring replenishment.**<br>Set coffee delivery to every four weeks.<br>Skip the next shipment and reduce future quantity while keeping the subscription active. | Medium–Hard | **Later:** subscription records, recurring schedules, and UI are absent. [C6] [C10] | Define subscription transitions with a controlled clock and an expected future shipment schedule. | Query subscription state and scheduled shipments; check recurrence calculations and preserved history. | **Moderate / Exact.** |
| V1 | Scenario variation | **Personalization and memory.**<br>Use the size from my last purchase.<br>Recommend items respecting preferences supplied across earlier sessions. | Medium–Hard | **Partial:** customer and order history exist; preference memory and control across sessions do not. [C2] [C6] | Fix shopper preferences, history, and the information available in each session before generating a personalized request. | Check history and preference constraints; judge soft preferences and verify which memory the agent could access. | **Moderate–High / Mixed.** |
| V2 | Scenario variation | **Clarification and confirmation.**<br>Clarify which coffee I mean by “my usual.”<br>Resolve an ambiguous delivery address and obtain the required confirmation before order placement. | Medium–Hard | **Missing:** the runner needs shopper dialogue, rules for revealing hidden requirements, and confirmation checks. [C2] [C12] | Withhold a required field from a feasible task; define the shopper’s answers and disclosure rules before the run. | Check questions, answers, and confirmation order against the disclosure log and final task state. | **High / Exact or Mixed.** |
| V3 | Scenario variation | **Incremental requirement changes.**<br>Switch my coffee request to decaf mid-task.<br>Tighten the budget after a proposed shopping cart and preserve the remaining requirements. | Medium–Hard | **Missing:** the runner needs controlled follow-up messages and versioned requirements. [C2] [C12] | Define a requirement change and its trigger before the run; validate a solution under the revised requirements. | Check when the change was disclosed, which requirements were active, and whether obsolete choices were removed. | **High / Exact or Mixed.** |
| V4 | Scenario variation | **Infeasibility and recovery.**<br>Report that no available product meets all constraints without purchasing.<br>Recover from an insufficient-stock checkout error by selecting an allowed alternative. | Medium–Hard | **Partial:** checkout can reject insufficient stock; task generation and controlled failure injection need work. [C5] | Prove that no product matches, or seed a stock shortage; specify permitted alternatives for recovery. | Check the infeasibility proof or observed error, final state, preserved records, and explanation. | **Moderate–High / Mixed.** |
| V5 | Scenario variation | **Action boundaries and collateral effects.**<br>Research options without changing my shopping cart.<br>Update only the specified address while preserving every unrelated address and order. | Easy–Hard | **Partial:** snapshots exist; general state comparisons and checks for transient actions do not. [C3] [C6] | Define permitted changes and forbidden actions; seed unrelated records whose state must be preserved. | Compare initial and final state; use trusted events to check forbidden actions and required confirmation order. | **Low–Moderate / Exact; High / Mixed** for traces. |
| V6 | Scenario variation | **Cross-shop shopping.**<br>Compare the delivered price of the same product at two shops.<br>Split a compatible shopping cart across shops while including separate shipping charges. | Medium–Hard | **Later:** coordinated setup and grading across shops are absent. [C2] [C12] | Align product identities across validated catalogs; calculate fees and a feasible allocation of purchases. | Query prices and state across shops; check equivalence and compatibility, and optimize within a bounded allocation space. | **Moderate–High / Exact or Mixed.** |

### Verification and coverage

Structured facts and state changes use deterministic checks: compare shopping
cart variants and quantities, or identify a new order and check its lines and
total. Recommendations and explanations also use an LLM judge with source
evidence. Check hard constraints separately from semantic quality. All outcomes
satisfying the request remain acceptable.

Temporal requirements need trusted events; a final snapshot cannot show whether
an item was temporarily added and removed. Interactive requirements and
disclosure rules must be fixed before the run.
[Appendix C](#c-verifier-design-notes) covers these extensions and domain cases.

Report results by family, difficulty, and variation, alongside product domains,
evidence sources, initial states, and interacting constraints. Include valid
alternatives, ties, infeasible cases, and recoverable errors where appropriate.
Simple operations do not need artificial Hard variants. Pilot runs should check
reference counts and distinguish environment failures from agent failures.
Family weights and sample counts remain open until the pilot.

## Alternative

Expanding only the deterministic seeds would be the smallest implementation
change. It fits exact discovery and simple state changes, but would continue to
underrepresent suitability, trade-offs, and interaction. Using one LLM to
generate every task and judge every result would cover more language and goals,
but would make feasibility and state correctness harder to establish.

Defining a formal FSM before exploration would make transition rules explicit,
as in AutoWebWorld. That would require maintaining a model for each storefront
and commerce domain as the generated implementation changes. The proposed
interaction graph is built from observed browser behavior, with backend state
checks and independent task replay supplying outcome validation.

## Execution Table

The rollout starts with existing capabilities and adds domains independently.
Each phase would generate only tasks supported by the target shop. This proposal
defines scope and sequencing; generator implementation remains separate.

| Phase | Proposed scope | Required work | Completion criteria |
| --- | --- | --- | --- |
| 0. Interaction graph | Typical pages and supported guest/customer states | Build agent-guided BFS, page/state deduplication, control annotations, reset/replay, observed transitions, and graph versioning. | Reproduce recorded transitions; distinguish untested controls from working actions; report page, state, and action coverage within exploration bounds. |
| 1. Baseline pilot | 01–02, 08–10, 14–15, basic 18–19; supported subsets of 04–06, V4–V5 | Combine parameterized scenarios and grounded data with graph-supported workflows; add reference action counts, ability tags, and outcome checks. Add account-access tasks and verify their session changes. | Replay tasks in fresh episodes; verify difficulty annotations; accept valid alternatives; reject targeted errors; validate infeasible cases; report coverage. |
| 2. Richer decisions | 03–06, 11; complex 02, 08, 18–19 | Validate product attributes, compatibility, and policies; add solution search, calculations, and semantic rubrics. | Independently audit feasibility and evidence, and calibrate semantic checks against human judgments. |
| 3. Interactive scenarios | V1–V5 on supported base families | Add shopper dialogue, disclosure rules, controlled changes, memory fixtures, and event checks. | Replay scripted interactions, verify event order, and measure user-simulator violations. |
| 4. Commerce workflows | 07, full 12–13, 16–17, refund-aware 18, 20–22 | Add each domain’s records, rules, mutations, and UI before its generator. | Validate the domain contract, browser workflow, and verifier for each family. |
| 5. Later expansion | 23, V6 | Add subscription schedules and coordinated episodes across shops. | Review domain semantics and verify isolation, replay, and calculations across domains. |

The remaining design decisions are the pilot’s allocation across families and
tiers, how subjective scores contribute to the aggregate metric, and which
missing commerce workflow to prioritize first.

## Appendix

### A. Baseline capability audit

The support assessment uses the existing implementation at the commit recorded
above. The audit uses code inspection; account support was also checked on
2026-10-23 with nine backend tests and two storefront HTTP smoke tests. These
exercise registration, credential validation, token revocation, protected account
pages, and episode isolation against fixtures. [C14] [C16]

Environment capabilities and benchmark coverage are assessed separately.
Generated shops can expose fewer features or extend the backend, so
each shop needs its own data and browser validation before receiving tasks.

The baseline provides:

- Ten deterministic seed skills: `exact`, `substitute`, `browse`, `filter`,
  `shipping`, `returns`, `e2e`, `account`, `checkout`, and `order_history`.
  These names cover narrower behavior than some proposed families: `returns`,
  for example, locates a policy page rather than executing a return. [C1]
- Shopping carts isolated by episode, customer and address reads, order history,
  simulated order placement, inventory changes, reset, and grader snapshots.
  [C4] [C5] [C6]
- Backend registration and credential validation, access-token creation and
  revocation, and storefront routes that store or clear the session cookie.
  These routes use sandbox customer records and episode-scoped sessions.
  [C9] [C14]
- `string_match`, `url_match`, `locator_probe`, `state_check`, and explicit
  `llm_judge` checks. `state_check` supports equality, subsets, and array
  membership. All configured checks must pass. Fuzzy text matching also invokes
  a judge. [C2] [C3]
- An explorer that proposes tasks and checks page reachability and locators in a
  fresh browser. It does not replay a full solution or establish feasibility
  and semantic correctness for every check type. [C11]

The following limits affect the proposed catalog:

- The runner posts credentials to `/account/login` before handing control to the
  agent for account seeds. The seed checks the reported email and default-address
  city; it does not evaluate the agent's ability to register, log in, or log out.
  These actions need dedicated generators and checks. Profile and address editing,
  default-address changes, and saved-payment management also need mutations and
  UI. [C1] [C4] [C9] [C15]
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

### B. Existing work and task generation approaches

This table retains the eight approach IDs used in the research discussion.
Approaches overlap: a paper can use templates, exploration, and validation in
one pipeline. **Selected** marks a component of ShopGym's proposed generation
pipeline; the other rows provide context or supporting techniques.

| ID | Approach | Construction process | Representative work and its task generation approach | Strengths and limitations | Role in ShopGym |
| --- | --- | --- | --- | --- | --- |
| 1 | Human-authored tasks / parameterized scenarios | Define a shopper goal and scenario template; bind products, customers, and orders; prepare initial state and success conditions. | [WebArena](https://arxiv.org/html/2307.13854#S3.SS1) authors intent templates and variable instances. [AppWorld](https://arxiv.org/html/2407.18901#S3) uses scenario-specific Setup, Evaluation, and Solution programs. | Gives explicit semantics and controllable state changes; coverage depends on the scenario library and authoring effort. | **Selected:** define task families, parameterized goals, initial states, and expected outcomes. |
| 2 | Product- or answer-first generation | Sample products or an answer; extract evidence; derive satisfiable requirements; write a shopper request. | [ShoppingBench](https://arxiv.org/html/2508.04266v1) samples products, extracts fields, and simulates intent-specific queries. [EComAgentBench](https://arxiv.org/html/2606.17698v1#S4) fixes the answer and typed criteria before generating the query, profile, and clarification text. | Grounds constraints in catalog facts; needs independent checks for alternatives and realistic language rather than a restatement of product fields. | **Selected:** bind grounded product, policy, and order facts to scenarios and compute valid answers before verbalization. |
| 3 | User-purpose-first generation | Infer a shopper purpose; decompose it into activity steps; associate purchase intentions and suitable products. | [EcomScriptBench](https://arxiv.org/html/2505.15196v1#S4) mines objectives and purchase intentions from reviews, generates scripts, aligns steps with products, and adds human annotations. | Produces natural, cross-category needs; purpose, purchase necessity, and product suitability require semantic review. | Context for purpose-based scenarios in the catalog; a separate purpose-mining pipeline is not selected. |
| 4 | Feasible-solution-first generation | Construct a valid selection or plan; derive constraints, budgets, and the shopper request around it. | [ComboShoppingBench](https://arxiv.org/html/2608.09282v1#S3) validates a purchasable shopping cart before deriving a budget, coupons, and request; evaluation accepts other valid selections. [DeepPlanning](https://arxiv.org/html/2601.18137v1#S3.SS2) progressively injects constraints and adjusts candidates to retain one optimum. | Establishes at least one solution; requires explicit rules for valid alternatives, ties, and optimization. | Supporting feasibility checks for planning scenarios; a standalone solution-first generator is not selected. |
| 5 | Page-functionality-first generation | Explore pages; inspect content, controls, forms, and accessibility trees; propose tasks using observed functionality. | [Amazon-Bench](https://arxiv.org/html/2508.15832v1#S3) uses BFS exploration, page categorization, functionality-diversity sampling, LLM query generation, and human refinement. | Covers account and shopping workflows absent from catalog records; a visible control alone does not establish a working action. | **Selected, combined with 7:** annotate interactive elements and confirm their behavior during exploration. |
| 6 | Trajectory-first generation | Execute exploratory interactions; infer tasks from the resulting changes, or refine tasks and trajectories together. | [NNetNav](https://arxiv.org/html/2410.02907v1) retrospectively labels exploration trajectories. [SynWeaver](https://arxiv.org/html/2608.12429v1#S3) builds a website map with DFS, learns UI priors, and jointly refines tasks and trajectories. | Can produce demonstrations at scale; may favor actions the explorer already performs and turn requests into procedural descriptions. | Reference replay is retained for validation; retrospective labeling and website-prior training are not selected as generation components. |
| 7 | Site-graph / state-machine search | Build a page or state graph; search for evidence and reachable goals; retain paths; replay and write the task. | [GTA](https://arxiv.org/html/2605.29218v1#S2.SS1) uses BFS to cache pages and accessibility trees, then generates multi-page questions from retrieved page pairs. [AutoWebWorld](https://arxiv.org/html/2602.14296v1#S4.SS3) generates an explicit FSM and website, then uses BFS to enumerate goal-reaching action paths. | Makes reachability and composition explicit; coverage depends on exploration bounds and the state abstraction. A hyperlink graph and an executable FSM provide different guarantees. | **Selected, combined with 5:** use agent-guided BFS to build a graph of typical pages, relevant states, and observed interactions, then use it to ground task generation. |
| 8 | Joint environment, task, and verifier generation | Generate or clone an executable environment; expose internal state or an SDK; generate tasks and programmatic checks. | [VeriEnv](https://github.com/kyle8581/VeriEnv) clones frontend, backend, and database and generates tasks with SDK-based validation. [WebArena-Infinity](https://github.com/web-arena-x/webarena-infinity) generates applications and verifiable tasks with iterative testing and auditing. | Enables resettable environments and state-based checks; shared generation errors can affect the environment, task, and verifier. | ShopArena supplies the environment. Joint generation is not selected as the task-generation strategy in this proposal. |

The combined design selects **1 + 2 + (5 + 7)**. These are complementary roles:
scenarios define shopper goals; product or answer data supplies grounded
parameters; page exploration supplies observed controls; graph search supplies
reachability and candidate workflows. ShopGym must still validate task outcomes
independently of the graph and request writer.

The graph methods differ in what they assume. GTA's graph represents hyperlinks
and supporting pages. AutoWebWorld searches a formal FSM defined before the
website is generated. ShopGym will explore generated SandboxShops, grouping nodes
by page type and key interaction state while retaining concrete entity bindings
and replay evidence. Graph coverage and observed state changes must be recorded
explicitly.

For V1–V3, start with a grounded base scenario and define preferences, hidden
requirements, and changes before interaction. Work on long-horizon shopping
personalization motivates testing consistency across interactions; ShopGym needs
the runner protocol described in this proposal to support these evaluations.
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
- [C14: Customer resolvers][C14] — registration, credential validation, token creation,
  and revocation; [backend tests](../../../packages/shop_backend/src/resolvers/customer.test.ts).
- [C15: Task setup][C15] — login through the storefront before the agent starts.
- [C16: Storefront HTTP smoke test][C16] — registration, logout, login, protected
  account pages, and episode isolation against the shared template.
- [C17: Existing explorer][C17] — browser-driven task proposals without a persisted
  interaction graph.
- [C18: Backend client][C18] — per-episode reset and state reads.
- [C19: Browser snapshots][C19] — URL, title, and accessibility tree with temporary
  element references.

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
[C14]: ../../../packages/shop_backend/src/resolvers/customer.ts
[C15]: ../../../packages/shop-guru/src/solve/setup.ts
[C16]: ../../../packages/shop-arena/src/templates.test.ts
[C17]: ../../../packages/shop-guru/src/explore/explore.ts
[C18]: ../../../packages/shop-guru/src/backend.ts
[C19]: ../../../packages/browser/src/snapshot.ts

### E. Research scope and prior context

Method selection builds on the
[previous ShopGym research review](https://shop-gym.quick.shopify.io/public/specs/docs/shop-gym/shopgym_v2/shopgym_v2_task_research_review.html#methods)
and the primary papers and repositories above, including 2026 work through
October. The hosted review redirected to authentication during this research;
its local counterpart was available as context, but is not part of the base
branch. Current support was assessed from code. This is a focused synthesis for
the proposed catalog; the cited benchmark results have not been replicated.

### F. Difficulty definitions and annotation

The reviewed benchmarks use several different definitions:

| Work | Definition | Use in ShopGym |
| --- | --- | --- |
| [WebArena §3.1](https://arxiv.org/html/2307.13854#S3.SS1) | Organizes tasks by information seeking, navigation, and content or configuration operations; it does not prescribe an Easy/Medium/Hard scale. | Retain the distinction between task category and difficulty. |
| [VisualWebArena §4.2](https://arxiv.org/html/2401.13649#S4.SS2) | Action difficulty uses estimated human actions: Easy ≤3, Medium 4–9, Hard ≥10. It also annotates visual difficulty. | Reuse the action bands for the three task tiers. |
| [SAGE §5.3, Table 3](https://yxw.cs.illinois.edu/files/SAGE_NeurIPS2025.pdf#page=8) | Groups WebArena tasks by human-annotated minimum steps: Easy <7, Medium 7–15, Hard >15. | An alternative step-based convention; use one published set of thresholds consistently. |
| [WorkArena++ §3.1–3.2](https://arxiv.org/html/2407.05291#S3.SS1) | L1 contains atomic tasks. L2 composes workflows with explicit instructions; L3 presents them through tickets and a knowledge base. It separately identifies the abilities being tested. | Reuse its ability categories and distinguish explicit workflows from goals requiring procedure retrieval. |

VisualWebArena provides a directly reusable three-band action definition.
WorkArena++ explains another source of difficulty: how much of the procedure the
agent must infer. We will record instruction explicitness and required abilities
alongside the action tier, preserving both short reasoning tasks and long
execution tasks in coverage reports. These ShopGym annotations do not establish
score comparability across benchmarks.

The following counting rules are proposed ShopGym conventions:

1. **Fix the setup.** Record the shop version, initial URL, authentication,
   shopping cart and other seeded state, and permitted browser operations.
2. **Replay an efficient solution.** A reviewer checks that the run succeeds
   without avoidable detours, using the same visible evidence and permitted
   actions as the agent. Count navigation, clicks, typing or filling a
   field, key presses, scrolling, and tab operations individually. Unpack batched
   tool calls; exclude fixture setup, screenshots, read-only observations,
   waiting, reasoning, and the final textual answer.
3. **Assign the tier.** Apply the published 3/9 boundaries to the reference count.
   Retain the trace and reviewer decision. It estimates efficient human effort;
   it does not claim a mathematically shortest solution. Recheck the count when
   the UI, setup, or action interface changes.
4. **Annotate additional demands.** Record abilities, instruction explicitness,
   interacting constraints, and required shopper exchanges. Dialogue turns remain
   separate from browser actions. For infeasible tasks, review an efficient
   evidence-gathering run that establishes the absence of a valid choice.
5. **Validate in the pilot.** Report success by action tier and ability tag, with
   the agent configuration and budget. Low success on a short task can reveal a
   reasoning gap without changing the task’s action tier.

### G. Interaction graph and exploration details

The graph is a proposed ShopGuru artifact for a generated SandboxShop. Existing
browser observations, episode isolation, and backend reset/state reads provide
building blocks; the graph schema, BFS controller, state abstraction, and
transition validation still need implementation. [C6] [C17] [C18] [C19]

#### Graph records

| Record | Required information | Purpose |
| --- | --- | --- |
| Page-state node | Page type, route pattern, representative URL and entity bindings, key interaction state, visible facts, screenshot/accessibility evidence, and a setup/replay recipe. | Distinguish states with different available actions while sharing structure across similar products or orders. |
| Interactive element | Role, accessible name, control type, relevant locator/context, allowed inputs, required fields, enabled/disabled state, prerequisites, and observation status. | Identify how a control can be used and distinguish discovered elements from confirmed functionality. |
| Observed transition | Source and destination node, concrete bindings, semantic action and primitive browser operations, observed prerequisites, UI result, backend state difference where relevant, and replay result. | Record how an interaction behaved for the tested case and provide an executable path segment. |
| Graph provenance and coverage | Storefront/backend/data versions, exploration setups, depth and action budgets, discovered page types/states, tested controls, failures, and unexpanded frontier. | Identify the graph's scope and determine when changed shops require re-exploration. |

The node key uses page type and key state. Useful state distinctions include a
selected variant being available or unavailable, a shopping cart being empty or
populated, a drawer being open or closed, and an account being signed in or out.
Entity IDs and concrete shopping cart lines remain in the representative
bindings and replay record. A new control signature or a different relevant
behavior requires a separate state or page subtype.

This abstraction reduces repeated exploration, but an observed transition for
one product does not prove that every product supports it. Task construction
must check the concrete bindings and replay the complete workflow. Similarly,
a path through abstract nodes is a candidate workflow until its intermediate
states and prerequisites are shown to compose.

#### Agent-guided BFS

1. **Prepare entry states.** Fix the generated shop version. Identify available
   page types and initialize representative guest and customer setups. Each
   queue entry carries the setup and action prefix needed to reproduce its
   source state.
2. **Inspect the next state.** Dequeue in BFS order, reproduce the state, and
   capture its accessibility tree and rendered evidence. The exploration agent
   classifies the page, annotates controls, and proposes meaningful action and
   input candidates. BFS owns queue order and duplicate detection.
3. **Test each branch independently.** Use a fresh browser context and reset the
   episode, reapply setup, and replay the source prefix before testing a
   candidate. Capture before/after UI and relevant backend state. Record working,
   rejected, failed, and untested interactions separately. Backend reset reseeds
   an episode; the existing API does not import arbitrary saved snapshots.
   [C18]
4. **Expand and deduplicate.** Store observed edges, including cycles. Queue a new
   page-state key when further exploration is needed. Retain concrete evidence
   for distinct control behavior and sample additional representatives where
   the abstraction may hide a capability difference.
5. **Stop with explicit bounds.** Stop when the selected frontier is exhausted
   or an exploration budget is reached. Persist the remaining frontier and
   unresolved actions. Report coverage of discovered page types, key states,
   and tested interactions without claiming complete coverage of the shop.

Element references in browser snapshots are temporary. Persist semantic control
identification and evidence, then resolve fresh references during replay. [C19]

#### Using the graph for task generation

Scenario requirements select relevant graph capabilities; graph search retrieves
or composes workflow candidates. Product- or answer-first construction supplies
concrete facts and parameters. The generator then fixes the initial state,
requirements, and independent success predicates before writing the request.
Graph paths and backend records remain generation/validation artifacts. The
evaluated agent receives the shopper request and permitted observations.

A replay failure is evidence about the candidate or graph: it may reveal an
invalid binding, a missing prerequisite, a stale transition, or an environment
bug. Correct the relevant record or defer the task. A successful replay provides
a reference solution and action count, while the verifier accepts any outcome
satisfying the request. Abstract graph distance does not determine difficulty;
the reference replay counts the primitive browser actions under the rules in
[Appendix F](#f-difficulty-definitions-and-annotation).
