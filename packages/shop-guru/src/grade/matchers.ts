/**
 * Pure comparison helpers shared by the graders. No I/O, no browser.
 */

/** Result of a programmatic comparison. */
export interface MatchResult {
  readonly passed: boolean;
  readonly detail: string;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** Structural deep equality over JSON values (object key order ignored). */
export function deepEquals(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((item, i) => deepEquals(item, b[i]));
  }
  if (isObject(a) && isObject(b)) {
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every((k) => deepEquals(a[k], b[k]));
  }
  return false;
}

/**
 * Whether `expected` is a partial description of `actual`: objects may omit
 * keys, arrays match when every expected element matches a distinct actual
 * element (order-free, injective), and primitives must be equal.
 */
export function isSubset(expected: unknown, actual: unknown): boolean {
  if (isObject(expected)) {
    return isObject(actual) && Object.keys(expected).every((k) => isSubset(expected[k], actual[k]));
  }
  if (Array.isArray(expected)) {
    return Array.isArray(actual) && matchInjectively(expected, actual, new Set());
  }
  return Object.is(expected, actual);
}

function matchInjectively(expected: unknown[], actual: unknown[], used: Set<number>): boolean {
  if (expected.length === 0) return true;
  const [head, ...rest] = expected;
  for (let i = 0; i < actual.length; i++) {
    if (used.has(i) || !isSubset(head, actual[i])) continue;
    used.add(i);
    if (matchInjectively(rest, actual, used)) return true;
    used.delete(i);
  }
  return false;
}

/** Resolve an RFC 6901 JSON pointer; `undefined` when a segment is missing. */
export function resolvePointer(root: unknown, pointer: string): unknown {
  if (pointer === '') return root;
  let current: unknown = root;
  for (const raw of pointer.slice(1).split('/')) {
    const key = raw.replaceAll('~1', '/').replaceAll('~0', '~');
    if (Array.isArray(current)) {
      current = current[Number(key)];
    } else if (isObject(current)) {
      current = current[key];
    } else {
      return undefined;
    }
    if (current === undefined) return undefined;
  }
  return current;
}

/** Apply a `state_check` rule to the value found at its pointer. */
export function matchState(
  rule: 'equals' | 'subset' | 'some',
  expected: unknown,
  actual: unknown,
): MatchResult {
  const seen = `found ${JSON.stringify(actual) ?? 'undefined'}`;
  switch (rule) {
    case 'equals':
      return { passed: deepEquals(expected, actual), detail: seen };
    case 'subset':
      return { passed: isSubset(expected, actual), detail: seen };
    case 'some': {
      if (!Array.isArray(actual)) return { passed: false, detail: `not an array: ${seen}` };
      const hit = actual.some((item) => isSubset(expected, item));
      return {
        passed: hit,
        detail: `${actual.length} element(s), match ${hit ? 'found' : 'missing'}`,
      };
    }
  }
}

/** Case-insensitive `mustInclude` / trimmed `exactMatch` over a text. */
export function matchText(
  text: string,
  required: {
    readonly mustInclude?: readonly string[] | undefined;
    readonly exactMatch?: string | undefined;
  },
): MatchResult {
  if (required.exactMatch !== undefined && text.trim() !== required.exactMatch.trim()) {
    return { passed: false, detail: `expected exactly "${required.exactMatch}"` };
  }
  const haystack = text.toLowerCase();
  const missing = (required.mustInclude ?? []).filter((s) => !haystack.includes(s.toLowerCase()));
  if (missing.length > 0) {
    return { passed: false, detail: `missing: ${missing.map((m) => `"${m}"`).join(', ')}` };
  }
  return { passed: true, detail: 'matched' };
}

/** Compare a visited URL against a `url_match` check, both resolved against `baseUrl`. */
export function matchUrl(
  actualUrl: string,
  expected: string,
  rule: 'exact' | 'prefix' | 'contains',
  baseUrl: string,
): MatchResult {
  const actual = normalize(actualUrl, baseUrl);
  const detail = `url ${actual}`;
  switch (rule) {
    case 'exact':
      return { passed: actual === normalize(expected, baseUrl), detail };
    case 'prefix':
      return { passed: actual.startsWith(normalize(expected, baseUrl)), detail };
    case 'contains':
      return { passed: actual.includes(expected), detail };
  }
}

function normalize(url: string, baseUrl: string): string {
  const resolved = new URL(url, baseUrl).toString();
  return resolved.endsWith('/') ? resolved.slice(0, -1) : resolved;
}
