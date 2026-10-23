# Shopping Task Generation Proposal

Status: **Proposed** · Audience: **ShopGym developers**

## Overview

ShopGuru’s ten seed skills mostly fill fixed templates: named-product search,
policy-page navigation, and simple shopping cart edits. They provide little
coverage of product selection, policy reasoning, or purchase planning.

We propose **23 task families and six scenario variations**, generated from
shopper scenarios, catalog data, and observed page interactions. The design has
two stages: explore a generated SandboxShop to build a reusable interaction graph,
then combine its supported workflows with grounded data and shopper scenarios.
Every resulting task receives an independently tested verifier.

This review covers **task coverage, the generation workflow, and the initial
pilot**. The [full catalog](#h-detailed-task-catalog) contains examples, support
assessments, generation recipes, and verifiers for every family.

## Terminology

- **Task family:** a type of shopper goal, such as product comparison or order cancellation.
- **Scenario variation:** an added condition, such as clarification or recovery. A task combines a base family with zero or more variations.
- **Validated solution:** a completion that demonstrates feasibility. The verifier accepts any outcome satisfying the request.
- **Interaction graph:** page types and relevant states connected by observed browser actions, with controls and replay evidence attached.

## Current Status

The table summarizes the shared implementation. Generated shops can expose
fewer features or extend the backend; each needs data and UI validation before
receiving tasks. The [capability audit](#a-baseline-capability-audit) and
[implementation references](#d-implementation-references) provide the evidence.

| Area | Existing implementation | Missing work |
| --- | --- | --- |
| Commerce | Isolated shopping carts, customer/address reads, order history, simulated checkout, inventory changes. | Profile edits, wishlists, reviews, after-sales, coupon pricing, richer logistics. |
| Account access | Backend/template registration, login, logout; seed reads a pre-authenticated profile. | Dedicated account-action tasks and verifiers. |
| Exploration | Browser-driven task proposals; reachability and locator checks. | Persistent interaction graph and full-workflow replay. |
| Evaluation | Text, URL, locator, snapshot, and LLM checks. | Constraint queries, optimization, state diffs, trusted events, shopper dialogue. |

For example, account login is implemented in the environment, but the current
account task does not test whether the agent can log in. Environment support,
generator coverage, and verifier readiness therefore need separate tracking.

## Desired Status

Generate plausible shopper goals across shopping stages and difficulty levels.
Each task needs accessible evidence, reproducible setup, a solution or
infeasibility proof, and a verifier tested against valid alternatives and likely
mistakes. Missing commerce and runner capabilities will be developed with ShopGym v2.

## Proposal

### Task generation workflow

Combine **developer-authored scenario templates**, **product- or answer-first
generation**, and **page exploration with breadth-first search (BFS)**.
Each supplies information the other approaches lack:

| Source | What it establishes | Limitation on its own |
| --- | --- | --- |
| Scenario templates | Realistic goals, initial state, constraints, and permitted changes. | A plausible request may require functionality the shop lacks. |
| Product or answer data | Feasible choices, supporting facts, and valid outcomes before writing the request. | Catalog facts do not describe all account, shopping cart, or after-sales workflows. |
| Page exploration and graph search | Available controls, observed state changes, and candidate workflows. | Reachable action sequences do not necessarily express useful shopper goals. |

[Appendix B](#b-existing-work-and-task-generation-approaches) compares these
approaches with related work and marks the selected components.

```mermaid
flowchart TD
    A[Generated SandboxShop] --> B[Explore pages and interactions]
    B -->|Reusable interaction graph| C[Construct task and verifier]
    D[Catalog facts and valid answers] --> C
    E[Parameterized shopper scenarios] --> C
    C --> F[Write shopper request]
    F --> G[Independent replay and verifier tests]
    G --> H[Benchmark task]
```

The interaction graph is reused across task instances for the same shop version.
Task construction binds concrete products, records, and initial state to a
scenario template. Developers author the goal structure and parameter slots;
the generator fills those slots from the target shop. Fix requirements and
success conditions before an LLM writes the request; keep reference answers
and replay paths outside the agent-visible goal.

### Interaction graph

Exploration runs on the **generated SandboxShop**, where episode reset and
backend state reads allow repeatable interaction checks. The agent inspects pages
and proposes meaningful inputs; the BFS controller manages the frontier and
visited states.

![Example interaction graph showing page types, stock states, shopping cart states, controls, and browser actions](assets/task-generation-interaction-graph.svg)

The example separates in-stock and out-of-stock product pages, and empty and
populated shopping carts, because their available actions differ. Product and
variant IDs remain parameters rather than creating a node for every item.

- **Node = page type + key interaction state.** Split nodes when controls or relevant behavior differ, even if the route pattern is shared.
- **Controls describe what can be attempted:** name, type, input requirements, enabled state, and prerequisites. A visible button alone does not establish that the action works.
- **Edges record tested behavior:** action, concrete bindings, resulting UI/backend changes, and a replay recipe. An edge may contain several primitive browser operations.

For each branch, reset the episode, recreate the browser session, and replay the
source prefix before testing the next action. Queue newly observed page/state
combinations in BFS order. Record exploration budgets, the remaining frontier,
and untested controls so graph coverage is explicit.

A graph path is a candidate workflow. It may fail with different products or
intermediate state, so each concrete task still requires independent replay.
[Appendix G](#g-interaction-graph-and-exploration-details) specifies the records,
state abstraction, and replay mechanics.

### Construct a task

| Step | Input and operation | Output |
| --- | --- | --- |
| Choose a scenario | Select the shopper goal, initial state, required capabilities, and permitted changes; find a candidate workflow in the graph. | A task specification supported by observed functionality. |
| Bind grounded data | Select products, variants, policy facts, customers, or orders; solve the constraints and check that the required evidence is visible. | Concrete parameters, a feasible solution, and valid outcome conditions. |
| Define verification | Check structured outcomes with queries/calculations; add an evidence-based rubric or event checks where needed. | A verifier derived from the fixed requirements, accepting valid alternative routes and outcomes. |
| Write and validate | Express the fixed requirements as a shopper request; replay in a fresh episode and test valid alternatives and targeted mistakes. | A benchmark candidate with provenance, verification evidence, and difficulty annotation. |

**Product- or answer-first** means establishing feasibility before generating
language. For “find a cotton shirt under $30,” the generator can start from one
matching item, derive the constraints, and enumerate every valid match. The
verifier accepts all matching choices, including products other than the one
used to construct the task.

For recommendations, scenarios also specify the shopper’s purpose and a
suitability rubric. For multi-item planning, validate a feasible selection before
deriving budgets and constraints. If required evidence or actions are missing,
explore further or defer the task.

Validation must also check that the written request preserves the fixed
requirements. Reject wording that omits a constraint or introduces a new one;
otherwise the verifier could grade a different task from the one the agent sees.

**Example: revise an existing shopping cart.**

| Part | Concrete task instance |
| --- | --- |
| Initial state | One 1 kg House Blend coffee pack and one mug in the shopping cart. |
| Catalog facts | The same coffee is sold in 500 g packs; at least two are available. |
| Graph support | Product variant selection, adding items, quantity changes, and removal have working replay paths. |
| Shopper request | “Replace the 1 kg House Blend pack with two 500 g packs. Keep the mug.” |
| Success conditions | No 1 kg pack; two 500 g packs; the mug remains at quantity one; no extra lines. |
| Validation | Replay a solution, accept other successful routes, and reject wrong quantities, unchanged large packs, or changes to the mug. |

The example shows the division of work: the graph establishes supported actions,
the catalog provides real options, the scenario defines the requested change,
and the verifier checks the final shopping cart.

### Task coverage

| Category | Families | Goals covered | Main additions needed |
| --- | --- | --- | --- |
| Discovery and decision | 01–08 | Find, recommend, compare, substitute; assess fit, reviews, and policies. | Grounded constraints, suitability rubrics, review data. |
| Shopping cart and purchase | 09–14 | Select variants, revise a shopping cart, plan purchases, optimize totals, check out. | Planning checks, promotion rules, delivery/pickup models. |
| Accounts and repeat shopping | 15–19 | Access accounts, manage preferences, save products, inspect orders, reorder. | Account-action tasks; profile and wishlist mutations. |
| After-sales | 20–23 | Modify/cancel orders, return/exchange, manage reviews and subscriptions. | Commerce records, lifecycle rules, mutations, and UI. |
| Scenario variations | V1–V6 | Memory, clarification, changing requirements, recovery, action boundaries, cross-shop shopping. | Dialogue, controlled events, memory, coordinated episodes. |

The [full catalog](#h-detailed-task-catalog) gives two examples per row and
separate assessments of generation, environment support, and verification.
Variations compose with base families: reordering can also require remembering a
preference, clarifying an address, or recovering from unavailable stock.

Diversity comes from different goals, evidence, initial states, and interacting
constraints. Product substitutions and paraphrases alone do not establish new
coverage. Include multiple valid outcomes, ties, infeasible requests, and recovery
cases where they represent plausible user needs.

### Difficulty

Reuse [VisualWebArena’s action bands](https://arxiv.org/html/2401.13649#S4.SS2):

| Easy | Medium | Hard |
| --- | --- | --- |
| ≤3 browser actions | 4–9 browser actions | ≥10 browser actions |

Assign each instance from an efficient, human-reviewed replay with fixed setup.
Count individual browser operations; exclude observations, fixture setup, and
agent retries. Graph distance does not determine difficulty. Catalog ranges are
generation targets, not measured labels for the example sentences.

Action count measures interaction length. Separately annotate the
[WorkArena++ abilities](https://arxiv.org/html/2407.05291#S3.SS2): planning,
information retrieval, data-driven reasoning, memory, and contextual understanding.
A short compatibility question may require substantial reasoning; a long form
may require little. [Appendix F](#f-difficulty-definitions-and-annotation)
defines the counting conventions.

### Verification and benchmark inclusion

| Requirement | Verification | Typical grading effort |
| --- | --- | --- |
| Structured facts and commerce outcomes | Database queries, calculations, initial/final state comparisons. | Low for direct checks; Moderate for joins, constraints, or optimization. |
| Suitability and explanations | Evidence-grounded LLM judge, with hard constraints checked separately and human calibration. | High; conclusions include subjective judgments. |
| Confirmation, disclosure, forbidden actions | Trusted event history and checks against active requirements. | Moderate–High; final snapshots cannot establish event order. |

Task difficulty and grading effort are independent. A long workflow can have an
exact final-state check, while a short recommendation can require a subjective
rubric. The catalog records verification effort and objectivity separately.

Before inclusion, confirm that the evidence is accessible, replay a solution in
a fresh episode, and test the verifier against correct alternatives and likely
errors. For infeasible requests, retain a proof and review an evidence-gathering
run. [Appendix C](#c-verifier-design-notes) covers domain-specific checks.

Report coverage and results by **family, action tier, and variation**. Separate
environment failures from agent failures; do not add artificial Hard variants
to simple operations. Interactive tasks also require validated shopper responses
and disclosure rules fixed before the run.

## Alternative

| Option | Main trade-off |
| --- | --- |
| Expand seed templates only | Lowest effort; limited coverage of decisions and interaction. |
| LLM-only generation and judging | Broad language coverage; harder to establish feasibility and state correctness. |
| Define a formal state machine first | Explicit transitions; requires a maintained model for each generated implementation. |

The proposed graph is built from observed browser behavior. This reduces the
need to maintain a complete model alongside every generated shop, but requires
bounded coverage reports and concrete task replay to catch missing prerequisites.

## Execution Table

| Phase | Deliverable | Ready when |
| --- | --- | --- |
| 0. Graph | Typical pages, key states, annotated controls. | Recorded transitions replay; exploration limits are reported. |
| 1. Baseline pilot | Tasks for supported discovery, shopping cart, checkout, account access, and order history. | Verifiers reject targeted errors; replay establishes difficulty. |
| 2. Richer decisions | Recommendations, compatibility, multi-item planning. | Evidence and feasibility pass audit; semantic judges are calibrated. |
| 3. Interaction | Clarification, memory, changing requirements, recovery. | Dialogue and event checks replay consistently. |
| 4. Commerce | Reviews, promotions, logistics, profile edits, after-sales. | Domain behavior, browser workflow, and verifiers pass validation. |
| 5. Expansion | Subscriptions and cross-shop tasks. | Scheduling and coordinated episodes are reproducible. |

Generate only tasks supported by the target shop; add generators as ShopGym v2
adds the corresponding capabilities. [Appendix I](#i-detailed-rollout) maps
phases to catalog IDs. Generator implementation is separate from this proposal.

Reviewers should resolve the pilot’s allocation across families and tiers,
how subjective scores contribute to aggregate results, and which missing commerce
workflow to prioritize first.

## Appendix

### A. Baseline capability audit

The audit covers the existing implementation at
[`230c185a`](https://github.com/agentic-foundation-modeling-research/shop-gym/commit/230c185a6fd7f1616bb18cdf276d451f03c976ab),
inspected on 2026-10-22. Account support was also checked on 2026-10-23 with nine
backend tests and two storefront HTTP smoke tests. These exercise registration,
credential validation, token revocation, protected account
pages, and episode isolation against fixtures. [customer resolvers](../../../packages/shop_backend/src/resolvers/customer.ts), [storefront smoke tests](../../../packages/shop-arena/src/templates.test.ts)

Environment capabilities and benchmark coverage are assessed separately.
Generated shops can expose fewer features or extend the backend, so
each shop needs its own data and browser validation before receiving tasks.

The baseline provides:

- Ten deterministic seed skills: `exact`, `substitute`, `browse`, `filter`,
  `shipping`, `returns`, `e2e`, `account`, `checkout`, and `order_history`.
  These names cover narrower behavior than some proposed families: `returns`,
  for example, locates a policy page rather than executing a return. [seed generators](../../../packages/shop-guru/src/seed/index.ts)
- Shopping carts isolated by episode, customer and address reads, order history,
  simulated order placement, inventory changes, reset, and grader snapshots.
  [customer schema](../../../packages/shop_backend/src/schema/customer.ts), [checkout resolver](../../../packages/shop_backend/src/resolvers/checkout.ts), [episode state snapshots](../../../packages/shop_backend/src/sandbox/snapshot.ts)
- Backend registration and credential validation, access-token creation and
  revocation, and storefront routes that store or clear the session cookie.
  These routes use sandbox customer records and episode-scoped sessions.
  [account routes](../../../packages/shop-arena/templates/storefront/app/routes/account), [customer resolvers](../../../packages/shop_backend/src/resolvers/customer.ts)
- `string_match`, `url_match`, `locator_probe`, `state_check`, and explicit
  `llm_judge` checks. `state_check` supports equality, subsets, and array
  membership. All configured checks must pass. Fuzzy text matching also invokes
  a judge. [task and check schema](../../../packages/core/src/schema/task.ts), [grading dispatcher](../../../packages/shop-guru/src/grade/grade.ts)
- An explorer that proposes tasks and checks page reachability and locators in a
  fresh browser. It does not replay a full solution or establish feasibility
  and semantic correctness for every check type. [explorer verification](../../../packages/shop-guru/src/explore/verify.ts)

The following limits affect the proposed catalog:

- The runner posts credentials to `/account/login` before handing control to the
  agent for account seeds. The seed checks the reported email and default-address
  city; it does not evaluate the agent's ability to register, log in, or log out.
  These actions need dedicated generators and checks. Profile and address editing,
  default-address changes, and saved-payment management also need mutations and
  UI. [seed generators](../../../packages/shop-guru/src/seed/index.ts), [customer schema](../../../packages/shop_backend/src/schema/customer.ts), [account routes](../../../packages/shop-arena/templates/storefront/app/routes/account), [task setup](../../../packages/shop-guru/src/solve/setup.ts)
- Checkout uses configured shipping and payment handles with simulated payment.
  Pricing supports flat tax and shipping rates and a free-shipping threshold.
  Discount codes are stored and reported as applicable, but have no eligibility
  checks or price effects. Delivery dates, geographic eligibility, and pickup
  slots are absent from commerce settings. [checkout resolver](../../../packages/shop_backend/src/resolvers/checkout.ts), [pricing rules](../../../packages/shop_backend/src/state/pricing.ts), [shopping cart resolver](../../../packages/shop_backend/src/resolvers/cart.ts), [dataset schemas](../../../packages/shop_backend/src/data/schema.ts)
- The shared state and schema have no wishlist, review, subscription,
  cancellation, return, exchange, or refund workflows. A seeded financial-status
  label does not provide the records needed to calculate partial refunds. [customer schema](../../../packages/shop_backend/src/schema/customer.ts), [episode state snapshots](../../../packages/shop_backend/src/sandbox/snapshot.ts), [dataset schemas](../../../packages/shop_backend/src/data/schema.ts)
- The task contract has one goal, optional login and shopping cart setup, and
  evaluation checks. It lacks typed difficulty, generation-method metadata,
  shopper dialogue, disclosure rules, and a memory contract across sessions. [task and check schema](../../../packages/core/src/schema/task.ts), [agent runner](../../../packages/shop-guru/src/solve/agent.ts)
- Built-in grading lacks arbitrary constraint queries, optimization, state diffs,
  and event-order checks. The judge receives the goal, rubric, final answer and
  URL, prior check results, and an optional final screenshot. Supplying source
  evidence and interaction history requires additional plumbing. [grading dispatcher](../../../packages/shop-guru/src/grade/grade.ts), [agent runner](../../../packages/shop-guru/src/solve/agent.ts)

### B. Existing work and task generation approaches

Methods can overlap within a pipeline. **Selected** identifies components of
ShopGym's proposed generator.

| Approach | Construction process | Representative work and its task generation approach | Strengths and limitations | Role in ShopGym |
| --- | --- | --- | --- | --- |
| Human-authored tasks / parameterized scenarios | Define a shopper goal and scenario template; bind products, customers, and orders; prepare initial state and success conditions. | [WebArena](https://arxiv.org/html/2307.13854#S3.SS1) authors intent templates and variable instances. [AppWorld](https://arxiv.org/html/2407.18901#S3) uses scenario-specific Setup, Evaluation, and Solution programs. | Gives explicit semantics and controllable state changes; coverage depends on the scenario library and authoring effort. | **Selected:** define task families, parameterized goals, initial states, and expected outcomes. |
| Product- or answer-first generation | Sample products or an answer; extract evidence; derive satisfiable requirements; write a shopper request. | [ShoppingBench](https://arxiv.org/html/2508.04266v1) samples products, extracts fields, and simulates intent-specific queries. [EComAgentBench](https://arxiv.org/html/2606.17698v1#S4) fixes the answer and typed criteria before generating the query, profile, and clarification text. | Grounds constraints in catalog facts; needs independent checks for alternatives and realistic language rather than a restatement of product fields. | **Selected:** bind grounded product, policy, and order facts to scenarios and compute valid answers before verbalization. |
| User-purpose-first generation | Infer a shopper purpose; decompose it into activity steps; associate purchase intentions and suitable products. | [EcomScriptBench](https://arxiv.org/html/2505.15196v1#S4) mines objectives and purchase intentions from reviews, generates scripts, aligns steps with products, and adds human annotations. | Produces natural, cross-category needs; purpose, purchase necessity, and product suitability require semantic review. | Context for purpose-based scenarios in the catalog; a separate purpose-mining pipeline is not selected. |
| Feasible-solution-first generation | Construct a valid selection or plan; derive constraints, budgets, and the shopper request around it. | [ComboShoppingBench](https://arxiv.org/html/2608.09282v1#S3) validates a purchasable shopping cart before deriving a budget, coupons, and request; evaluation accepts other valid selections. [DeepPlanning](https://arxiv.org/html/2601.18137v1#S3.SS2) progressively injects constraints and adjusts candidates to retain one optimum. | Establishes at least one solution; requires explicit rules for valid alternatives, ties, and optimization. | Supporting feasibility checks for planning scenarios; a standalone solution-first generator is not selected. |
| Page-functionality-first generation | Explore pages; inspect content, controls, forms, and accessibility trees; propose tasks using observed functionality. | [Amazon-Bench](https://arxiv.org/html/2508.15832v1#S3) uses BFS exploration, page categorization, functionality-diversity sampling, LLM query generation, and human refinement. | Covers account and shopping workflows absent from catalog records; a visible control alone does not establish a working action. | **Selected with site-graph search:** annotate interactive elements and confirm their behavior during exploration. |
| Trajectory-first generation | Execute exploratory interactions; infer tasks from the resulting changes, or refine tasks and trajectories together. | [NNetNav](https://arxiv.org/html/2410.02907v1) retrospectively labels exploration trajectories. [SynWeaver](https://arxiv.org/html/2608.12429v1#S3) builds a website map with DFS, learns UI priors, and jointly refines tasks and trajectories. | Can produce demonstrations at scale; may favor actions the explorer already performs and turn requests into procedural descriptions. | Reference replay is retained for validation; retrospective labeling and website-prior training are not selected as generation components. |
| Site-graph / state-machine search | Build a page or state graph; search for evidence and reachable goals; retain paths; replay and write the task. | [GTA](https://arxiv.org/html/2605.29218v1#S2.SS1) uses BFS to cache pages and accessibility trees, then generates multi-page questions from retrieved page pairs. [AutoWebWorld](https://arxiv.org/html/2602.14296v1#S4.SS3) generates an explicit finite-state machine (FSM) and website, then uses BFS to enumerate goal-reaching action paths. | Makes reachability and composition explicit; coverage depends on exploration bounds and the state abstraction. A hyperlink graph and an executable FSM provide different guarantees. | **Selected with page-functionality discovery:** use agent-guided BFS to build a graph of typical pages, relevant states, and observed interactions, then use it to ground task generation. |
| Joint environment, task, and verifier generation | Generate or clone an executable environment; expose internal state or an SDK; generate tasks and programmatic checks. | [VeriEnv](https://github.com/kyle8581/VeriEnv) clones frontend, backend, and database and generates tasks with SDK-based validation. [WebArena-Infinity](https://github.com/web-arena-x/webarena-infinity) generates applications and verifiable tasks with iterative testing and auditing. | Enables resettable environments and state-based checks; shared generation errors can affect the environment, task, and verifier. | ShopArena supplies the environment. Joint generation is not selected as the task-generation strategy in this proposal. |

The graph methods differ in what they assume. GTA's graph represents hyperlinks
and supporting pages. AutoWebWorld searches a formal FSM defined before the
website is generated. ShopGym will explore generated SandboxShops, grouping nodes
by page type and key interaction state while retaining concrete entity bindings
and replay evidence. Graph coverage and observed state changes must be recorded
explicitly.

For long-horizon personalization context, see
[Personalization Matters](https://arxiv.org/html/2610.11375v1).
V1–V3 require fixed disclosure rules and validated runner dialogue.

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
here. [task and check schema](../../../packages/core/src/schema/task.ts), [grading dispatcher](../../../packages/shop-guru/src/grade/grade.ts), [task validation](../../../packages/shop-guru/src/validate.ts)

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
are needed to determine what happened during the episode. [episode state snapshots](../../../packages/shop_backend/src/sandbox/snapshot.ts), [agent runner](../../../packages/shop-guru/src/solve/agent.ts)

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

### D. Implementation references

These source links support the capability audit and catalog support assessments.
They refer to the audited implementation identified in Appendix A.

| Component | Source | What to inspect |
| --- | --- | --- |
| Task generation | [Seed generators](../../../packages/shop-guru/src/seed/index.ts), [explorer](../../../packages/shop-guru/src/explore/explore.ts), [proposal verification](../../../packages/shop-guru/src/explore/verify.ts), [task validation](../../../packages/shop-guru/src/validate.ts) | Current task coverage, reachability/locator checks, and validation limits. |
| Task contract and grading | [Task schema](../../../packages/core/src/schema/task.ts), [grader](../../../packages/shop-guru/src/grade/grade.ts) | Setup fields, supported checks, judge inputs, and metadata gaps. |
| Episode runner | [Setup](../../../packages/shop-guru/src/solve/setup.ts), [agent runner](../../../packages/shop-guru/src/solve/agent.ts), [episode execution](../../../packages/shop-guru/src/solve/solve.ts) | Pre-authentication, isolated execution, and trajectory recording. |
| Backend state | [State snapshots](../../../packages/shop_backend/src/sandbox/snapshot.ts), [state transitions](../../../packages/shop_backend/src/state/shop_state.ts), [backend client](../../../packages/shop-guru/src/backend.ts) | Episode state, reset, and state reads. |
| Accounts | [Customer schema](../../../packages/shop_backend/src/schema/customer.ts), [resolvers](../../../packages/shop_backend/src/resolvers/customer.ts), [account routes](../../../packages/shop-arena/templates/storefront/app/routes/account) | Registration, credential validation, sessions, and account reads. |
| Shopping cart and pricing | [Shopping cart resolver](../../../packages/shop_backend/src/resolvers/cart.ts), [pricing rules](../../../packages/shop_backend/src/state/pricing.ts) | Line mutations, tax/shipping, and placeholder discount codes. |
| Checkout | [Checkout resolver](../../../packages/shop_backend/src/resolvers/checkout.ts), [checkout route](../../../packages/shop-arena/templates/storefront/app/routes/checkout.tsx) | Validation, simulated order placement, and inventory effects. |
| Data and browser observations | [Dataset schemas](../../../packages/shop_backend/src/data/schema.ts), [browser snapshots](../../../packages/browser/src/snapshot.ts) | Available records, accessibility observations, and temporary element references. |
| Authentication tests | [Backend customer tests](../../../packages/shop_backend/src/resolvers/customer.test.ts), [storefront smoke tests](../../../packages/shop-arena/src/templates.test.ts) | Registration, login/logout, protected pages, and episode isolation. |

### E. Research scope

This proposal builds on the [ShopGym task-generation research review](https://shop-gym.quick.shopify.io/public/specs/docs/shop-gym/shopgym_v2/shopgym_v2_task_research_review.html#methods)
and the primary papers and repositories linked above, covering work through
October 2026. Implementation support comes from the code audit in Appendix A.
Published benchmark results have not been replicated.

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
transition validation still need implementation. [episode state snapshots](../../../packages/shop_backend/src/sandbox/snapshot.ts), [existing explorer](../../../packages/shop-guru/src/explore/explore.ts), [backend client](../../../packages/shop-guru/src/backend.ts), [browser snapshots](../../../packages/browser/src/snapshot.ts)

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
   [backend client](../../../packages/shop-guru/src/backend.ts)
4. **Expand and deduplicate.** Store observed edges, including cycles. Queue a new
   page-state key when further exploration is needed. Retain concrete evidence
   for distinct control behavior and sample additional representatives where
   the abstraction may hide a capability difference.
5. **Stop with explicit bounds.** Stop when the selected frontier is exhausted
   or an exploration budget is reached. Persist the remaining frontier and
   unresolved actions. Report coverage of discovered page types, key states,
   and tested interactions without claiming complete coverage of the shop.

Element references in browser snapshots are temporary. Persist semantic control
identification and evidence, then resolve fresh references during replay. [browser snapshots](../../../packages/browser/src/snapshot.ts)

#### Using the graph for task generation

Task metadata records family, category, variations, action count and tier,
required abilities, scenario, generation methods, required capabilities,
shop/graph version, source records, and verification requirements. These fields
require schema extensions. [Task schema](../../../packages/core/src/schema/task.ts)

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

### H. Detailed task catalog

Support assessments are grounded in the [capability audit](#a-baseline-capability-audit)
and [implementation references](#d-implementation-references).
Each row gives two independent shopper requests. Generate an instance only when
its required facts and actions exist in the target shop. Difficulty ranges are
generation targets; concrete instances receive labels after reference replay.

**Environment support:** Basic = core operations exist; Partial = a useful subset
exists; Missing = core workflow needs implementation; Later = expansion beyond
the initial single-shop scope. These labels do not imply generator or verifier
readiness. V1–V6 can be combined with base families.

**Verification difficulty:** Low = direct checks; Moderate = joins/calculations;
High = semantic/interaction assessment. **Objectivity:** Exact = deterministic
criteria; Mixed = exact and semantic checks; Rubric-based = subjective judgment.
Task and verification difficulty are independent. A **database query** may read
catalog records, seeded records, or episode snapshots; no SQL service is required.

| ID | Category | Task family and realistic examples | Target difficulty range | Current ShopGym support and gaps | Proposed task generation approach | Required verifier(s) | Verification difficulty / objectivity |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | Discovery and decision | **Known-item discovery.**<br>Find the TrailLite 20L backpack.<br>Find its available navy variant, distinguishing it from the older model. | Easy–Medium | **Basic:** search and variant selection exist; current seeds accept any variant. | Sample an available product and similar models, then derive identifying attributes from the catalog. | Query product and variant IDs; check the answer or URL, and shopping cart contents when requested. | **Low / Exact.** |
| 02 | Discovery and decision | **Constraint-based discovery.**<br>Find a cotton shirt under $30.<br>Find black, machine-washable trousers in my size under $80, excluding wool. | Easy–Hard | **Partial:** filters exist; combined constraints and evidence for care instructions or materials need stronger checks. | Derive constraints from a feasible item, then enumerate all matching products and near misses. | Query attributes, price, size, and stock; check supporting text for claims outside structured fields. | **Low–Moderate / Exact; Mixed** for prose. |
| 03 | Discovery and decision | **Recommendations for a purpose or occasion.**<br>Suggest a housewarming gift under $25.<br>Choose a gift for a beginner gardener with a small balcony and no storage space. | Easy–Hard | **Partial:** browsing exists; generation from shopper needs and suitability rubrics are absent. | Sample a shopper need and preferences; identify suitable products using catalog evidence and an explicit rubric. | Check budget and stock with queries; use an LLM judge to assess suitability and the explanation. | **High / Rubric-based.** |
| 04 | Discovery and decision | **Comparison and value.**<br>Which of two coffee packs is cheaper per kilogram?<br>Compare three backpacks on capacity, weight, price, and warranty using my stated priorities. | Easy–Hard | **Partial:** prices and descriptions exist; unit conversion, warranty evidence, and comparison checks need work. | Select candidates and shopper priorities; calculate comparable values and rankings before writing the request. | Check facts, unit conversions, and rankings; use an LLM judge for qualitative trade-offs. | **Moderate / Exact or Mixed.** |
| 05 | Discovery and decision | **Substitution and unavailability.**<br>Find a cheaper alternative to this mug.<br>My preferred shoe is unavailable; preserve size, material, and fit within budget. | Easy–Hard | **Partial:** similarity seeds and stock data exist; substitutes need checks for the attributes the shopper wants to preserve. | Select an original item, specify which attributes can change, and enumerate available alternatives. | Query price, stock, and required attributes; exclude the original item; judge functional similarity when needed. | **Moderate–High / Mixed.** |
| 06 | Discovery and decision | **Sizing, fit, and compatibility.**<br>Use my measurements and the size chart to choose a shirt size.<br>Find a replacement filter for my exact appliance model and reject a similar incompatible filter. | Medium–Hard | **Partial:** descriptions and options exist; reliable size charts and compatibility data depend on the shop. | Validate size charts or model compatibility data, then sample valid choices and similar but invalid choices. | Query size ranges or compatibility relations; assess fit claims and uncertainty against the source evidence. | **Moderate / Exact; Mixed** for fit. |
| 07 | Discovery and decision | **Review-grounded research.**<br>Summarize recurring sizing complaints for these shoes.<br>Compare recent verified-purchase reviews, distinguishing repeated defects from isolated complaints. | Medium–Hard | **Missing:** review records, filtering, and review pages need support. | Prepare dated reviews with purchase flags and recurring or conflicting findings, then generate research questions. | Query the relevant reviews and check cited passages; use an LLM judge to assess whether the summary represents them faithfully. | **High / Mixed.** |
| 08 | Discovery and decision | **Policy and store information.**<br>What is the return window?<br>For a discounted gift shipped internationally, explain the applicable shipping and return conditions. | Easy–Hard | **Partial:** policy pages and navigation seeds exist; answers and policy exceptions need additional checks. | Extract rules, exceptions, and supporting passages; calculate the applicable outcome for a shopper scenario. | Evaluate policy rules and calculations; judge answers against source passages. Use URL checks for navigation-only goals. | **Low / Exact** to **High / Mixed.** |
| 09 | Shopping cart and purchase | **Variant and quantity selection.**<br>Add two blue mugs.<br>Add one medium black shirt and two large white shirts, using available variants only. | Easy–Hard | **Basic:** variant selection and shopping cart mutations exist; seeds need exact quantity and variant checks. | Sample available variants and quantities, then generate a request for those items. | Compare shopping cart lines by variant ID and quantity, including checks for unwanted items. | **Low / Exact.** |
| 10 | Shopping cart and purchase | **Shopping cart revision.**<br>Remove the duplicate mug.<br>Replace the large pack with two small packs, preserve all other lines, and keep the total under $70. | Easy–Hard | **Basic:** shopping cart setup and mutations exist; revision tasks need before-and-after checks. | Seed an initial shopping cart and define the requested changes, budget, and items that must remain unchanged. | Compare initial and final shopping carts; calculate the total and check preserved lines. | **Low–Moderate / Exact.** |
| 11 | Shopping cart and purchase | **Multi-item shopping cart planning.**<br>Choose a notebook and pen for under $20.<br>Build a cooking kit for four campers, covering required roles with compatible items within budget. | Medium–Hard | **Partial:** multi-item shopping carts exist; planning needs checks for required functions, compatibility, and the complete selection. | Validate one feasible shopping cart before deriving the request and budget; retain success conditions independent of that solution. | Check quantities, budget, required functions, and compatibility; judge suitability where product facts require interpretation. | **Moderate–High / Exact or Mixed.** |
| 12 | Shopping cart and purchase | **Promotions and total-cost optimization.**<br>Apply an eligible 10% coupon.<br>Choose the best legal coupon combination for my shopping cart, including shipping and a useful threshold top-up if it lowers the payable total. | Medium–Hard | **Partial:** tax and shipping calculations work; coupon eligibility, discounts, and stacking rules are missing. | Define promotion rules and a feasible shopping cart; compute the optimum within an explicit set of candidate choices. | Use pricing calculations, eligibility rules, and an optimizer; check that any added item serves the stated need. | **Moderate–High / Exact.** |
| 13 | Shopping cart and purchase | **Delivery, pickup, and deadlines.**<br>Does the shop deliver to my country?<br>Find the cheapest option arriving before Friday, with pickup as a fallback. | Easy–Hard | **Partial:** policies and flat shipping rates exist; destination eligibility, arrival dates, and pickup need support. | Generate policy questions first; after extending logistics, sample destinations, deadlines, and feasible delivery or pickup slots. | Check policy evidence, destination eligibility, dates, and the selected delivery or pickup option. | **Moderate / Exact; Mixed** for prose. |
| 14 | Shopping cart and purchase | **Checkout and order placement.**<br>Complete guest checkout for this shopping cart using supplied details.<br>Place the order to my office with the specified shipping and payment options and final amount. | Medium–Hard | **Basic:** simulated guest and customer checkout exist; the current seed starts signed in with a prefilled shopping cart. | Seed the shopping cart and customer details; calculate the expected total and order state after checkout. | Identify the new order; check lines, customer details, shipping and payment options, total, and inventory. Reject duplicate orders. | **Low–Moderate / Exact.** |
| 15 | Accounts and repeat shopping | **Account access.**<br>Register with these details without marketing opt-in.<br>Sign in, report the default-address city, then sign out. | Easy–Medium | **Basic:** backend and template routes implement registration, password login, and logout. The runner signs in for the account seed; these actions need dedicated tasks and checks. | Seed credentials or an unused email and define the expected account and session changes. | Check customer records, marketing consent, browser session state, and the required sequence of account actions. | **Low–Moderate / Exact.** |
| 16 | Accounts and repeat shopping | **Profile, addresses, and payment preferences.**<br>Save my office address.<br>Make it the default for future purchases, remove an obsolete address, and preserve existing orders. | Easy–Hard | **Missing for edits:** profile and address reads exist; editing, default selection, and saved-payment management need mutations and UI. | Seed customer records and define the intended edits and records that must remain unchanged. | Compare profile, address, and payment records; check the default address reference and preservation of existing orders. | **Low–Moderate / Exact.** |
| 17 | Accounts and repeat shopping | **Wishlist and saved plans.**<br>Save these two products for later.<br>Move available saved items below $30 into my shopping cart while retaining unavailable items in the wishlist. | Easy–Hard | **Missing:** wishlist records, persistence, mutations, and UI need support. | Seed saved items and derive the requested changes from stock and price constraints. | Compare wishlist and shopping cart contents; check quantities, retained items, and duplicates. | **Low–Moderate / Exact.** |
| 18 | Accounts and repeat shopping | **Order lookup, status, and spending.**<br>Report my latest order status.<br>Calculate kitchen-category spending last quarter after partial refunds. | Easy–Hard | **Partial:** order history and detail seeds exist; aggregate checks and a partial-refund ledger need adding. | Seed dated orders with product categories and calculate reference totals; include refunds once the ledger exists. | Query the customer’s orders by date and category; calculate spending using the declared refund rules. | **Low–Moderate / Exact.** |
| 19 | Accounts and repeat shopping | **Reordering.**<br>Add the coffee from my last order to my shopping cart.<br>Repeat the office order without pens, double the paper, and substitute an unavailable item. | Easy–Hard | **Partial:** order history, shopping carts, and checkout exist; reordering needs generation and stock-aware checks. | Start from a previous order, apply exclusions and quantity changes, then validate available substitutes. | Compare the shopping cart or new order with the source order; check quantities, exclusions, stock, and substitutions. | **Moderate / Exact or Mixed.** |
| 20 | After-sales | **Order modification and cancellation.**<br>Cancel my unshipped order.<br>Cancel only the duplicate order and change the other order's address if policy permits. | Easy–Hard | **Missing:** order editing and cancellation need lifecycle rules, mutations, and inventory and payment effects. | Seed orders with different eligibility states and derive permitted changes from the shop’s policy. | Check order changes, eligibility, inventory, and payment effects; verify that unrelated orders remain unchanged. | **Moderate / Exact.** |
| 21 | After-sales | **Returns, exchanges, and refunds.**<br>Request a return for a damaged mug.<br>Exchange a shirt's size, return one of two mugs, and explain why another line is ineligible. | Easy–Hard | **Missing:** return, exchange, and refund actions need support; policy lookup already exists. | Build scenarios from purchased items, dates, reasons, policy exceptions, and replacement stock. | Check each line’s status, amount, and inventory effects; evaluate policy rules and the explanation. | **Moderate–High / Mixed.** |
| 22 | After-sales | **Review submission and management.**<br>Submit a four-star review using my supplied feedback.<br>Update my own review after a replacement while preserving its purchase relationship. | Easy–Medium | **Missing:** reviews need records, authorship and purchase links, mutations, and UI. | Seed an authenticated customer, purchase, and optional existing review; generate edits from user-supplied feedback. | Check authorship, purchase links, rating, and updates; use an LLM judge to check fidelity to the supplied feedback. | **Low / Exact; High / Mixed** for text. |
| 23 | After-sales | **Subscriptions and recurring replenishment.**<br>Set coffee delivery to every four weeks.<br>Skip the next shipment and reduce future quantity while keeping the subscription active. | Medium–Hard | **Later:** subscription records, recurring schedules, and UI are absent. | Define subscription transitions with a controlled clock and an expected future shipment schedule. | Query subscription state and scheduled shipments; check recurrence calculations and preserved history. | **Moderate / Exact.** |
| V1 | Scenario variation | **Personalization and memory.**<br>Use the size from my last purchase.<br>Recommend items respecting preferences supplied across earlier sessions. | Medium–Hard | **Partial:** customer and order history exist; preference memory and control across sessions do not. | Fix shopper preferences, history, and the information available in each session before generating a personalized request. | Check history and preference constraints; judge soft preferences and verify which memory the agent could access. | **Moderate–High / Mixed.** |
| V2 | Scenario variation | **Clarification and confirmation.**<br>Clarify which coffee I mean by “my usual.”<br>Resolve an ambiguous delivery address and obtain the required confirmation before order placement. | Medium–Hard | **Missing:** the runner needs shopper dialogue, rules for revealing hidden requirements, and confirmation checks. | Withhold a required field from a feasible task; define the shopper’s answers and disclosure rules before the run. | Check questions, answers, and confirmation order against the disclosure log and final task state. | **High / Exact or Mixed.** |
| V3 | Scenario variation | **Incremental requirement changes.**<br>Switch my coffee request to decaf mid-task.<br>Tighten the budget after a proposed shopping cart and preserve the remaining requirements. | Medium–Hard | **Missing:** the runner needs controlled follow-up messages and versioned requirements. | Define a requirement change and its trigger before the run; validate a solution under the revised requirements. | Check when the change was disclosed, which requirements were active, and whether obsolete choices were removed. | **High / Exact or Mixed.** |
| V4 | Scenario variation | **Infeasibility and recovery.**<br>Report that no available product meets all constraints without purchasing.<br>Recover from an insufficient-stock checkout error by selecting an allowed alternative. | Medium–Hard | **Partial:** checkout can reject insufficient stock; task generation and controlled failure injection need work. | Prove that no product matches, or seed a stock shortage; specify permitted alternatives for recovery. | Check the infeasibility proof or observed error, final state, preserved records, and explanation. | **Moderate–High / Mixed.** |
| V5 | Scenario variation | **Action boundaries and collateral effects.**<br>Research options without changing my shopping cart.<br>Update only the specified address while preserving every unrelated address and order. | Easy–Hard | **Partial:** snapshots exist; general state comparisons and checks for transient actions do not. | Define permitted changes and forbidden actions; seed unrelated records whose state must be preserved. | Compare initial and final state; use trusted events to check forbidden actions and required confirmation order. | **Low–Moderate / Exact; High / Mixed** for traces. |
| V6 | Scenario variation | **Cross-shop shopping.**<br>Compare the delivered price of the same product at two shops.<br>Split a compatible shopping cart across shops while including separate shipping charges. | Medium–Hard | **Later:** coordinated setup and grading across shops are absent. | Align product identities across validated catalogs; calculate fees and a feasible allocation of purchases. | Query prices and state across shops; check equivalence and compatibility, and optimize within a bounded allocation space. | **Moderate–High / Exact or Mixed.** |

### I. Detailed rollout

Generate only tasks supported by the target shop. This table specifies the pilot
subsets and domain work behind the main rollout; implementation remains separate.

| Phase | Proposed scope | Required work | Completion criteria |
| --- | --- | --- | --- |
| 0. Interaction graph | Typical pages and supported guest/customer states | Build agent-guided BFS, page/state deduplication, control annotations, reset/replay, observed transitions, and graph versioning. | Reproduce recorded transitions; distinguish untested controls from working actions; report page, state, and action coverage within exploration bounds. |
| 1. Baseline pilot | 01–02, 08–10, 14–15, basic 18–19; supported subsets of 04–06, V4–V5 | Combine parameterized scenarios and grounded data with graph-supported workflows; add reference action counts, ability tags, and outcome checks. Add account-access tasks and verify their session changes. | Replay tasks in fresh episodes; verify difficulty annotations; accept valid alternatives; reject targeted errors; validate infeasible cases; report coverage. |
| 2. Richer decisions | 03–06, 11; complex 02, 08, 18–19 | Validate product attributes, compatibility, and policies; add solution search, calculations, and semantic rubrics. | Independently audit feasibility and evidence, and calibrate semantic checks against human judgments. |
| 3. Interactive scenarios | V1–V5 on supported base families | Add shopper dialogue, disclosure rules, controlled changes, memory fixtures, and event checks. | Replay scripted interactions, verify event order, and measure user-simulator violations. |
| 4. Commerce workflows | 07, full 12–13, 16–17, refund-aware 18, 20–22 | Add each domain’s records, rules, mutations, and UI before its generator. | Validate the domain contract, browser workflow, and verifier for each family. |
| 5. Later expansion | 23, V6 | Add subscription schedules and coordinated episodes across shops. | Review domain semantics and verify isolation, replay, and calculations across domains. |
