import { describe, expect, it } from 'vitest';

import {
  brandSafetyBlock,
  findAllowlistedToken,
  isAllowedBrand,
  loadAllowlist,
  pickBrandName,
  scanBrandLeaks,
} from './allowlist.js';

describe('allowlist', () => {
  it('loads the fake brands and safe nouns', () => {
    const allowlist = loadAllowlist();
    expect(allowlist.brands).toContain('AisleArena');
    expect(allowlist.brands.length).toBe(10);
    expect(isAllowedBrand('Cartanvil')).toBe(true);
    expect(isAllowedBrand('cartanvil')).toBe(false);
    expect(brandSafetyBlock()).toContain('AisleArena');
  });

  it('finds allowlisted tokens inside prose', () => {
    expect(findAllowlistedToken('A Shopodrome classic')).toBe('Shopodrome');
    expect(findAllowlistedToken('A plain oak bowl')).toBeUndefined();
  });

  it('scans for capitalised tokens outside the allowlist and safe nouns', () => {
    const hits = scanBrandLeaks('The Blue bowl by Zorblax ships from Carthaeum. Zorblax again.');
    expect(hits.map((h) => h.token)).toEqual(['Zorblax']);
    expect(hits[0]?.start).toBeGreaterThan(0);
  });

  it('skips sentence-initial words', () => {
    expect(scanBrandLeaks('Zorblax makes bowls. Zorblax is nice.')).toEqual([]);
  });

  it('picks a brand name deterministically from a key', () => {
    const a = pickBrandName('shop-a\0Minimal Homeware');
    expect(a).toBe(pickBrandName('shop-a\0Minimal Homeware'));
    expect(isAllowedBrand(a)).toBe(true);
  });
});
