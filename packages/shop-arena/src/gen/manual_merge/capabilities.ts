/**
 * Merges the `capabilities.json` of several Shop Manuals into one.
 *
 * Every leaf has a deterministic rule keyed by its dotted path. The only
 * LLM-driven decisions are the merged `shop.descriptor` when seeds disagree
 * and the `*_layout` / `*_style` enums when the vote is tied; both go
 * through the injected `Tiebreaker` so the merge itself stays pure.
 */

import {
  type Capabilities,
  CapabilitiesValidationError,
  parseCapabilities,
} from '../../explore/capabilities.js';

export type MergeRule =
  | 'bool_union'
  | 'scalar_majority'
  | 'max'
  | 'list_union'
  | 'list_union_cap_tone'
  | 'list_union_cap_section_types'
  | 'layout_style_enum'
  | 'llm_descriptor';

export interface MergeConflict {
  readonly path: string;
  readonly rule: MergeRule;
  /** `seed_<i>` to the value that seed contributed (seeds without a value omitted). */
  readonly seedValues: Readonly<Record<string, unknown>>;
  readonly chosenValue: unknown;
  readonly tiebreak: 'first_seed' | 'max' | 'llm' | null;
}

/** LLM callbacks for the two non-deterministic rules. */
export interface Tiebreaker {
  descriptor(tone: readonly string[], descriptors: readonly string[]): Promise<string>;
  /** Must return one of `candidates`; anything else keeps the first seed's value. */
  layout(path: string, candidates: readonly string[], descriptor: string): Promise<string>;
}

export interface CapabilitiesMerge {
  readonly capabilities: Capabilities;
  readonly conflicts: readonly MergeConflict[];
}

const TONE_CAP = 3;

export const MERGE_RULES: Readonly<Record<string, MergeRule>> = {
  'shop.descriptor': 'llm_descriptor',
  'shop.category': 'scalar_majority',
  'shop.currency': 'scalar_majority',
  'shop.tone': 'list_union_cap_tone',
  'site_shell.has_announcement_bar': 'bool_union',
  'site_shell.header_style': 'layout_style_enum',
  'site_shell.has_mega_menu': 'bool_union',
  'site_shell.nav_depth': 'max',
  'site_shell.footer_groups': 'scalar_majority',
  'homepage.section_types': 'list_union_cap_section_types',
  'homepage.section_count': 'scalar_majority',
  'homepage.has_popup_modal': 'bool_union',
  'collection.layout': 'layout_style_enum',
  'collection.columns_desktop': 'scalar_majority',
  'collection.filters': 'list_union',
  'collection.sort': 'list_union',
  'collection.pagination': 'scalar_majority',
  'product.gallery_style': 'layout_style_enum',
  'product.variant_selectors': 'list_union',
  'product.has_quantity_selector': 'bool_union',
  'product.description_layout': 'layout_style_enum',
  'product.has_reviews': 'bool_union',
  'product.has_recommendations': 'bool_union',
  'product.has_personalization': 'bool_union',
  'cart.type': 'scalar_majority',
  'cart.has_promo_input': 'bool_union',
  'cart.has_upsells': 'bool_union',
  'cart.has_shipping_estimate': 'bool_union',
  'search.trigger': 'scalar_majority',
  'search.has_predictive': 'bool_union',
  'search.predictive_types': 'list_union',
  'search.results_layout': 'layout_style_enum',
  'floating.has_chat_widget': 'bool_union',
  'floating.has_age_gate': 'bool_union',
  'floating.has_cookie_banner': 'bool_union',
  'floating.has_newsletter_popup': 'bool_union',
  'intl.has_locale_switcher': 'bool_union',
  'intl.has_currency_switcher': 'bool_union',
  'account.has_login': 'bool_union',
  'account.has_signup': 'bool_union',
  'account.has_profile': 'bool_union',
  'account.has_addresses': 'bool_union',
  'account.has_order_history': 'bool_union',
  'checkout.has_guest_checkout': 'bool_union',
  'checkout.payment_methods': 'list_union',
  'checkout.has_discount_code': 'bool_union',
  'checkout.shipping_options': 'list_union',
  info_pages_present: 'list_union',
};

type Contribution = { readonly seed: string; readonly value: unknown };

function keyOf(value: unknown): string {
  return JSON.stringify(value);
}

function getPath(record: Record<string, unknown>, dotted: string): unknown {
  let current: unknown = record;
  for (const part of dotted.split('.')) {
    if (typeof current !== 'object' || current === null || Array.isArray(current)) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[part];
  }
  return current ?? undefined;
}

function setPath(record: Record<string, unknown>, dotted: string, value: unknown): void {
  const parts = dotted.split('.');
  let current = record;
  for (const part of parts.slice(0, -1)) {
    const next = current[part];
    if (typeof next !== 'object' || next === null) {
      current[part] = {};
    }
    current = current[part] as Record<string, unknown>;
  }
  current[parts[parts.length - 1] as string] = value;
}

function disagree(values: readonly Contribution[]): boolean {
  return new Set(values.map((c) => keyOf(c.value))).size > 1;
}

/** Plurality vote; ties go to the earliest seed among the tied values. */
function majority(values: readonly Contribution[]): {
  value: unknown;
  tiebreak: 'first_seed' | null;
} {
  const votes = new Map<string, number>();
  for (const c of values) {
    votes.set(keyOf(c.value), (votes.get(keyOf(c.value)) ?? 0) + 1);
  }
  const top = Math.max(...votes.values());
  const tied = [...votes.entries()].filter(([, n]) => n === top).map(([k]) => k);
  const winner = values.find((c) => tied.includes(keyOf(c.value))) as Contribution;
  return { value: winner.value, tiebreak: tied.length > 1 ? 'first_seed' : null };
}

function unionLists(
  values: readonly Contribution[],
  path: string,
  cap: number | undefined,
): unknown[] {
  const seen = new Set<string>();
  const merged: unknown[] = [];
  for (const c of values) {
    if (!Array.isArray(c.value)) {
      throw new CapabilitiesValidationError(`${path}: list rule expects arrays`);
    }
    for (const item of c.value) {
      if (!seen.has(keyOf(item))) {
        seen.add(keyOf(item));
        merged.push(item);
      }
    }
  }
  return cap === undefined ? merged : merged.slice(0, cap);
}

function listsDisagree(values: readonly Contribution[]): boolean {
  if (values.length < 2) return false;
  const first = new Set((values[0]?.value as unknown[]).map(keyOf));
  return values.slice(1).some((c) => {
    const other = new Set((c.value as unknown[]).map(keyOf));
    return other.size !== first.size || [...other].some((k) => !first.has(k));
  });
}

/**
 * Merges validated seed capability documents in seed order.
 *
 * @param seeds Raw `capabilities.json` documents (validated here).
 * @param tiebreaker Required only when seeds disagree on the descriptor or
 *   tie on a layout enum; without it, layout ties keep the first seed.
 */
export async function mergeCapabilities(
  seeds: readonly unknown[],
  tiebreaker?: Tiebreaker,
): Promise<CapabilitiesMerge> {
  if (seeds.length === 0) {
    throw new CapabilitiesValidationError('mergeCapabilities requires at least one seed');
  }
  const docs = seeds.map((seed) => parseCapabilities(seed) as unknown as Record<string, unknown>);
  const names = docs.map((_, i) => `seed_${i}`);
  const sectionCounts = docs
    .map((d) => getPath(d, 'homepage.section_count'))
    .filter((v): v is number => typeof v === 'number');
  const sectionTypesCap = sectionCounts.length > 0 ? Math.max(...sectionCounts) : undefined;

  const merged: Record<string, unknown> = {};
  const conflicts: MergeConflict[] = [];
  const ordered = [
    'shop.tone',
    'shop.descriptor',
    ...Object.keys(MERGE_RULES)
      .filter((p) => p !== 'shop.tone' && p !== 'shop.descriptor')
      .sort(),
  ];
  let mergedTone: string[] = [];
  let mergedDescriptor: string | undefined;

  for (const path of ordered) {
    const rule = MERGE_RULES[path] as MergeRule;
    const values: Contribution[] = docs
      .map((d, i) => ({ seed: names[i] as string, value: getPath(d, path) }))
      .filter((c) => c.value !== undefined && c.value !== null);
    if (values.length === 0) continue;
    const seedValues = Object.fromEntries(values.map((c) => [c.seed, c.value]));
    const record = (chosenValue: unknown, tiebreak: MergeConflict['tiebreak']) =>
      conflicts.push({ path, rule, seedValues, chosenValue, tiebreak });
    let chosen: unknown;

    switch (rule) {
      case 'bool_union': {
        chosen = values.some((c) => Boolean(c.value));
        if (disagree(values)) record(chosen, null);
        break;
      }
      case 'scalar_majority': {
        const vote = majority(values);
        chosen = vote.value;
        if (disagree(values)) record(chosen, vote.tiebreak);
        break;
      }
      case 'max': {
        const ints = values.map((c) => c.value);
        if (!ints.every((v) => typeof v === 'number' && Number.isInteger(v))) {
          throw new CapabilitiesValidationError(`${path}: max rule expects integer values`);
        }
        chosen = Math.max(...(ints as number[]));
        if (disagree(values)) record(chosen, 'max');
        break;
      }
      case 'list_union':
      case 'list_union_cap_tone':
      case 'list_union_cap_section_types': {
        const cap =
          rule === 'list_union_cap_tone'
            ? TONE_CAP
            : rule === 'list_union_cap_section_types'
              ? sectionTypesCap
              : undefined;
        chosen = unionLists(values, path, cap);
        if (listsDisagree(values)) record(chosen, null);
        if (path === 'shop.tone') mergedTone = chosen as string[];
        break;
      }
      case 'layout_style_enum': {
        const vote = majority(values);
        chosen = vote.value;
        if (disagree(values)) {
          let tiebreak: MergeConflict['tiebreak'] = vote.tiebreak;
          if (vote.tiebreak === 'first_seed' && tiebreaker && mergedDescriptor !== undefined) {
            const candidates = [...new Set(values.map((c) => String(c.value)))].sort();
            const reply = (await tiebreaker.layout(path, candidates, mergedDescriptor)).trim();
            if (candidates.includes(reply)) {
              chosen = reply;
              tiebreak = 'llm';
            }
          }
          record(chosen, tiebreak);
        }
        break;
      }
      case 'llm_descriptor': {
        const descriptors = values
          .map((c) => ({ seed: c.seed, value: String(c.value).trim() }))
          .filter((c) => c.value !== '');
        if (descriptors.length === 0) {
          throw new CapabilitiesValidationError(`${path}: requires at least one non-empty value`);
        }
        const distinct = [...new Set(descriptors.map((c) => c.value))];
        if (distinct.length === 1) {
          chosen = distinct[0];
        } else {
          if (!tiebreaker) {
            throw new CapabilitiesValidationError(`${path}: descriptor disagreement needs an LLM`);
          }
          const reply = (await tiebreaker.descriptor(mergedTone, distinct)).trim();
          chosen = reply.split('\n')[0]?.trim() ?? '';
          if (chosen === '') {
            throw new CapabilitiesValidationError(`${path}: LLM returned an empty descriptor`);
          }
          conflicts.push({
            path,
            rule,
            seedValues: Object.fromEntries(descriptors.map((c) => [c.seed, c.value])),
            chosenValue: chosen,
            tiebreak: 'llm',
          });
        }
        mergedDescriptor = chosen as string;
        break;
      }
    }
    setPath(merged, path, chosen);
  }
  return { capabilities: parseCapabilities(merged), conflicts };
}
