/**
 * Fake-brand allowlist and brand-shaped token scanner.
 *
 * `fake_brands.json` (next to this module) lists the only proper nouns a
 * generated shop may use as a brand, plus capitalised common nouns the
 * scanner treats as safe. The scanner is intentionally strict: any other
 * capitalised multi-letter token that does not start a sentence counts as
 * a possible leak.
 */

import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

export interface Allowlist {
  readonly version: string;
  /** Allowed brand tokens, sorted. */
  readonly brands: readonly string[];
  /** Safe-noun groups in file order (colors, materials, ...). */
  readonly safeNounGroups: Readonly<Record<string, readonly string[]>>;
  readonly safeNouns: ReadonlySet<string>;
}

export interface BrandHit {
  readonly token: string;
  readonly start: number;
  readonly end: number;
}

const TOKEN_RE = /[A-Z][A-Za-z]+/g;

/** Group labels used in the prompt block, in rendering order. */
const GROUP_LABELS: Readonly<Record<string, string>> = {
  colors: 'Colors',
  materials: 'Materials',
  units: 'Sizes & units',
  countries: 'Country abbreviations',
  stopwords: 'Common stopwords',
  ui_nouns: 'Storefront UI nouns',
};

let cached: Allowlist | undefined;

/** Loads `fake_brands.json` once per process. */
export function loadAllowlist(): Allowlist {
  if (cached === undefined) {
    const file = new URL('./fake_brands.json', import.meta.url);
    const raw = JSON.parse(readFileSync(file, 'utf-8')) as {
      version: string;
      brands: { token: string }[];
      safe_nouns: Record<string, unknown>;
    };
    const groups: Record<string, string[]> = {};
    for (const [name, values] of Object.entries(raw.safe_nouns)) {
      if (Array.isArray(values)) {
        groups[name] = [...new Set(values.filter((v): v is string => typeof v === 'string'))];
      }
    }
    cached = {
      version: raw.version,
      brands: raw.brands.map((b) => b.token).sort(),
      safeNounGroups: groups,
      safeNouns: new Set(Object.values(groups).flat()),
    };
  }
  return cached;
}

export function isAllowedBrand(token: string, allowlist: Allowlist = loadAllowlist()): boolean {
  return allowlist.brands.includes(token);
}

/** First allowlisted brand token appearing in `text`, if any. */
export function findAllowlistedToken(
  text: string,
  allowlist: Allowlist = loadAllowlist(),
): string | undefined {
  for (const match of text.matchAll(TOKEN_RE)) {
    if (allowlist.brands.includes(match[0])) {
      return match[0];
    }
  }
  return undefined;
}

function isSentenceInitial(text: string, start: number): boolean {
  if (start === 0) {
    return true;
  }
  let i = start - 1;
  if (!/\s/.test(text[i] ?? '')) {
    return false;
  }
  while (i >= 0 && /\s/.test(text[i] ?? '')) {
    i -= 1;
  }
  return i < 0 || '.!?'.includes(text[i] ?? '');
}

/** Capitalised tokens that are neither sentence-initial, safe nouns, nor allowlisted brands. */
export function scanBrandLeaks(text: string, allowlist: Allowlist = loadAllowlist()): BrandHit[] {
  const hits: BrandHit[] = [];
  for (const match of text.matchAll(TOKEN_RE)) {
    const token = match[0];
    const start = match.index;
    if (isSentenceInitial(text, start)) continue;
    if (allowlist.safeNouns.has(token)) continue;
    if (allowlist.brands.includes(token)) continue;
    hits.push({ token, start, end: start + token.length });
  }
  return hits;
}

/** Markdown block appended to synthesis prompts describing the allowlist. */
export function brandSafetyBlock(allowlist: Allowlist = loadAllowlist()): string {
  const lines = [
    '**Brand-safety reference**',
    '',
    'The following fake-brand tokens are the ONLY allowlisted proper nouns. Use exact case; do not invent new tokens; do not use any real-world brand:',
    '',
    ...allowlist.brands.map((b) => `- \`${b}\``),
    '',
    'Capitalized common nouns the post-pass scanner treats as safe (use freely as descriptive vocabulary; they are NOT flagged as brand-shaped):',
    '',
  ];
  for (const [group, label] of Object.entries(GROUP_LABELS)) {
    const values = allowlist.safeNounGroups[group];
    if (values !== undefined && values.length > 0) {
      lines.push(`- ${label}: ${values.map((v) => `\`${v}\``).join(', ')}`);
    }
  }
  lines.push(
    '',
    'Any other capitalized multi-letter token in your output is treated as a brand leak by the post-pass scanner.',
  );
  return `${lines.join('\n')}\n`;
}

/** Deterministically picks the shop's brand name from the allowlist. */
export function pickBrandName(key: string, allowlist: Allowlist = loadAllowlist()): string {
  const digest = createHash('sha256').update(key).digest('hex');
  const index = Number(BigInt(`0x${digest}`) % BigInt(allowlist.brands.length));
  return allowlist.brands[index] as string;
}
