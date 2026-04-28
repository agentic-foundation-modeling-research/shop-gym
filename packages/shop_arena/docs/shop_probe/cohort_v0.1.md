# ShopProbe v0.1 cohort decisions — T5.1

Status: **Decided** · Cohort version: **0.1**
Spec: [`docs/specs/shop_arena/web_probe.md`](../../../../docs/specs/shop_arena/web_probe.md) §8.5
Plan: [`docs/impl/web_probe_implementation.md`](../../../../docs/impl/web_probe_implementation.md) **T5.1**

This file is the v0.1 README the T5.1 acceptance check requires. It
records the four decisions that close spec §8.5 open questions before
the M5 cohort run, plus pointers to the anonymization-sufficiency
ablation (`outputs/web_probe/anonymization_ablation/`).

The corresponding cohort.yaml ships with these decisions wired in;
`tests/test_cohort.py` validates structural invariants.

Concrete merchant URLs and pair identifiers are scrubbed in the
public repo and replaced with `*.example.invalid` placeholders and
numeric `pair_<n>` ids; the operator deployment maps the placeholders
to the real targets at run time.

---

## 1. Three unpaired real shops (spec §8.5 Q1)

**Decision.** The v0.1 unpaired-real population is

| Slot | Label | URL | Selection axis |
|---|---|---|---|
| Stock-leaning OS 2.0 / Dawn-derivative | `real/1` | https://real-1.example.invalid | "close-to-default Shopify shop"; smaller catalog. |
| Heavily customised | `real/2` | https://real-2.example.invalid | Shopify Plus; bespoke theme; AJAX-rich UX. |
| Multi-market | `real/3` | https://real-3.example.invalid | Hydrogen-based; locale switcher; multi-currency. |

These three together span the theme / catalog / i18n axes the spec
§8.5 Q1 calls for and complement the three paired sources
(`source-1.example.invalid`, `source-2.example.invalid`,
`source-3.example.invalid`) so the 6-real-shop reference population
(§5.2) is balanced.

**Selection criteria.** Each row must be:

1. Shopify-powered (verified at M5 dry-run via the standard
   `cdn.shopify.com` asset signature on `/`).
2. Publicly browseable headlessly (no auth wall for `/`,
   `/collections/*`, `/products/*`).
3. Diverse on theme (Dawn-shaped vs. heavily customised) **and** on
   catalog combinatorics (small vs. large; single-market vs.
   multi-market).
4. Stable enough that re-runs across an N=3 reproducibility sweep
   (T5.2) produce flake < 1% per probe.

**Alternates** (used only if (1)–(4) fail on the M5 dry-run, in order):

1. Shopify Plus / heavy-customisation alternate. Replaces `real/2`.
2. Small-CPG / Dawn-shaped alternate. Replaces `real/1`.
3. Multi-market apparel alternate. Replaces `real/3`.

The dry-run is gated by T5.2 ("N=3 reruns of axes A and B"); any swap
bumps the cohort version to **0.1.1** and updates this file in lockstep.

## 2. Bot-detection mitigation for `source-2` and `source-3` (spec §8.5 Q2)

**Decision.** Apply spec §8.5 option **(b)** — residential proxy +
slowed probes + cached HAR — uniformly to both targets. Spec option
**(c)** (skip the merchant, pick alternates) is the documented
fallback if option (b) yields > 5% probe failure rate on the M5
dry-run.

| Lever | Configuration |
|---|---|
| Egress | Residential proxy (provider chosen at deploy time; pinned in `BrowserMeta.notes`). Probe traffic must look like a residential client, not a datacentre IP. |
| Pacing | `≥ 1 s` floor between probe requests on these two targets (overrides the 10 s timeout default; default 0 s pacing). |
| Caching | Mandatory HAR capture per crawl (already required by spec §5.8). HARs are committed under `outputs/web_probe/cohort_v0.1/<target>/run_<n>/network.har` so reviewers can re-score offline if the live target later blocks. |
| User-Agent | Pinned via `BrowserMeta.user_agent` (default `ShopProbe/0.1 (Chromium/<version>)`). Not rotated — reproducibility beats stealth at v0.1. |
| Concurrency | The `source-2` and `source-3` probes run **serially** (one Playwright context at a time per target). |

**Why not option (a) — cooperating-merchant access?** v0.1 is an
open-source paper artifact; relying on merchant cooperation would make
the result non-reproducible by external researchers and would couple
ShopProbe to merchant SLA.

**Why not always option (c)?** `source-2` and `source-3` are the two
paired sources for `pair_2` and `pair_3` — swapping them would break
the `(source, sandbox)` calibration relationship that the sandbox
build pipeline depends on. Option (c) is reserved for the unpaired
population in §1.

**Acceptance for §2.** T5.2's first dry-run records per-probe success
rate against `source-2` and `source-3`; if either exceeds 5% failure
attributable to bot blocking (HTTP 403 / interstitial DOM), the
cohort drops to fallback (c), the dropped target's pair is removed
from the M5 cohort, and a v0.1.1 README revision documents the swap.

## 3. Sandbox URLs for `pair_2` and `pair_3` (spec §8.5 Q3)

**Decision.** Both sandboxes are pending `shop-gen` deployment. They
deploy the same way `pair_1`'s sandbox already deploys:

1. Run `shop-gen` against the source (one storefront at a time;
   produces `outputs/shops/mock_<n>/`).
2. Deploy the generated Hydrogen storefront to the existing Cloud Run
   service (URL prefix
   `https://shop-arena-<hash>-126018801413.us-central1.run.app`).
3. T5.2 wires the deployed URL into `cohort.yaml` (replaces `TBD`),
   bumps the cohort patch version to **0.1.1**, and triggers the M5
   cohort run.

Until step 2 lands, the cohort.yaml `sandbox.base_url` for these two
pairs is the literal string `TBD`; the loader (`shop_probe.cohort`)
accepts it because spec §5.2 only requires `base_url` to be a non-empty
string. T5.2 is the gate that flips both URLs.

**Fallback.** If either deployment slips past M5 timeline, the
M5 cohort run drops to **2 pairs** (`pair_1` + one of {`pair_2`,
`pair_3`}) plus the 3 unpaired real shops, and the v0.1.1 README
documents the reduction. Two pairs is still sufficient for the §5.7
per-pair fidelity table; the radar / surface / Turing charts (§8.4)
render with whatever pairs are populated.

## 4. Anonymization-sufficiency ablation for axis C (spec §8.5 Q4)

**Decision.** v1 anonymization (lexical rewrites over the
`Trajectory` text fields) is **sufficient** to defeat brand-recognition
on the closed leak-vector list it is designed to cover; out-of-scope
vectors (pixel content of screenshots, HAR response bodies,
accessibility-snapshot text inside on-disk evidence files) are
acknowledged as **v1.1 work**. M4–M5 axis-C judging proceeds with the
v1 anonymizer; if M4's swap-consistency check (T4.8) shows the judge
flips on swaps for >5% of pairs, the v1.1 vectors are escalated.

The full ablation report — methodology, leakage counts, reproducible
script — lives at:

[`outputs/web_probe/anonymization_ablation/report.md`](../../../../outputs/web_probe/anonymization_ablation/report.md)

with the structured leakage audit at
[`leakage_audit.json`](../../../../outputs/web_probe/anonymization_ablation/leakage_audit.json)
and the reproducible script at
[`scripts/anonymization_ablation.py`](../../scripts/anonymization_ablation.py).

The report's headline finding (excerpted):

> Across the 10-pattern v1 leak inventory (source domain, brand
> strings, theme identifiers, distinctive product titles), the
> anonymizer leaks **0 / 38** occurrences from the brand-loaded
> `pair_1` fixture trajectory (residual leakage rate 0.0%). Catalog
> handles in URL paths are hashed with a stable per-pair salt,
> preserving cross-step structure for the judge while removing
> brand identity. Out-of-scope vectors (pixel bytes, HAR bodies,
> on-disk a11y snapshot text) are not rewritten in v1; they are
> tracked as a v1.1 workstream.

---

## 5. Summary of changes against `cohort.yaml`

| Field | Before T5.1 | After T5.1 |
|---|---|---|
| `real_unpaired[*].label` | `real/TBD_1`, `real/TBD_2`, `real/TBD_3` | `real/1`, `real/2`, `real/3` |
| `real_unpaired[*].base_url` | `TBD` | `https://real-1.example.invalid`, `https://real-2.example.invalid`, `https://real-3.example.invalid` |
| `pairs.pair_2.source.notes` | bot-detection TBD | option (b) chosen + fallback documented |
| `pairs.pair_3.source.notes` | bot-detection TBD | option (b) chosen + fallback documented |
| `pairs.pair_2.sandbox.base_url` | `TBD` | `TBD` (deployment-tracked; plan documented in §3) |
| `pairs.pair_3.sandbox.base_url` | `TBD` | `TBD` (deployment-tracked; plan documented in §3) |

The `pair_1` sandbox URL is unchanged — it is the single sandbox
already deployed at v0.1 cut.

## 6. Versioning

- **0.1** — first cut with these decisions wired in (this commit).
- **0.1.1** — bump triggered by either (a) `pair_2` / `pair_3` sandbox
  deployment landing, (b) a bot-detection-driven fallback to
  alternates, or (c) the anonymization v1.1 escalation. Each 0.1.x
  patch updates §1–§4 here in lockstep with `cohort.yaml`.
- **1.0** — paper-time freeze, post-M5 cohort run.
