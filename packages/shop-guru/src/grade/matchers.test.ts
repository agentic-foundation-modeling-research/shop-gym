import { describe, expect, it } from 'vitest';

import {
  deepEquals,
  isSubset,
  matchState,
  matchText,
  matchUrl,
  resolvePointer,
} from './matchers.js';

describe('isSubset', () => {
  it('matches partial objects and ignores extra keys', () => {
    expect(isSubset({ a: 1 }, { a: 1, b: 2 })).toBe(true);
    expect(isSubset({ a: 1, c: 3 }, { a: 1, b: 2 })).toBe(false);
    expect(isSubset({}, { a: 1 })).toBe(true);
    expect(isSubset({}, 'x')).toBe(false);
  });

  it('matches array elements injectively', () => {
    const lines = [
      { quantity: 1, id: 'a' },
      { quantity: 2, id: 'b' },
    ];
    expect(isSubset([{ quantity: 2 }, {}], lines)).toBe(true);
    expect(isSubset([{ quantity: 2 }, { quantity: 2 }], lines)).toBe(false);
    expect(isSubset([{}, {}, {}], lines)).toBe(false);
    expect(isSubset([], lines)).toBe(true);
  });
});

describe('deepEquals', () => {
  it('compares structurally regardless of key order', () => {
    expect(deepEquals({ a: [1, { b: 2 }] }, { a: [1, { b: 2 }] })).toBe(true);
    expect(deepEquals({ a: 1, b: 2 }, { b: 2, a: 1 })).toBe(true);
    expect(deepEquals([1, 2], [2, 1])).toBe(false);
    expect(deepEquals({ a: 1 }, { a: 1, b: undefined })).toBe(false);
  });
});

describe('resolvePointer', () => {
  const doc = { carts: [{ lines: [{ quantity: 2 }] }], 'a/b': { '~x': 1 } };

  it('walks objects and arrays', () => {
    expect(resolvePointer(doc, '')).toBe(doc);
    expect(resolvePointer(doc, '/carts/0/lines/0/quantity')).toBe(2);
    expect(resolvePointer(doc, '/carts/1')).toBeUndefined();
    expect(resolvePointer(doc, '/carts/0/lines/0/quantity/x')).toBeUndefined();
  });

  it('unescapes ~1 and ~0', () => {
    expect(resolvePointer(doc, '/a~1b/~0x')).toBe(1);
  });
});

describe('matchState', () => {
  it('implements equals, subset, and some', () => {
    expect(matchState('equals', [], []).passed).toBe(true);
    expect(matchState('subset', { a: 1 }, { a: 1, b: 2 }).passed).toBe(true);
    expect(matchState('some', { a: 1 }, [{ a: 2 }, { a: 1, b: 3 }]).passed).toBe(true);
    expect(matchState('some', { a: 1 }, { a: 1 })).toMatchObject({
      passed: false,
      detail: expect.stringContaining('not an array'),
    });
  });
});

describe('matchText', () => {
  it('is case-insensitive for mustInclude and trims exactMatch', () => {
    expect(matchText('The Blue Collar', { mustInclude: ['blue', 'COLLAR'] }).passed).toBe(true);
    expect(matchText('The Blue Collar', { mustInclude: ['red'] })).toEqual({
      passed: false,
      detail: 'missing: "red"',
    });
    expect(matchText('  42 \n', { exactMatch: '42' }).passed).toBe(true);
    expect(matchText('42.0', { exactMatch: '42' }).passed).toBe(false);
  });
});

describe('matchUrl', () => {
  const base = 'http://shop.test';

  it('resolves relative checks against the base url', () => {
    expect(matchUrl(`${base}/cart/`, '/cart', 'exact', base).passed).toBe(true);
    expect(matchUrl(`${base}/cart?x=1`, '/cart', 'exact', base).passed).toBe(false);
    expect(
      matchUrl(`${base}/collections/dogs?page=2`, '/collections/dogs', 'prefix', base).passed,
    ).toBe(true);
    expect(matchUrl(`${base}/collections/dogs`, 'dogs', 'contains', base).passed).toBe(true);
    expect(matchUrl(`${base}/products/x`, '/cart', 'contains', base).passed).toBe(false);
  });
});
