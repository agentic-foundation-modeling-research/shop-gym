import { describe, expect, it } from 'vitest';

import { allowedGlobs, globToRegExp, ownedFileViolations } from './owned_files.js';

describe('globToRegExp', () => {
  it('matches any depth with ** and one segment with *', () => {
    expect(globToRegExp('backend/src/sandbox/**').test('backend/src/sandbox/a/b.ts')).toBe(true);
    expect(globToRegExp('backend/src/**/*.test.ts').test('backend/src/x.test.ts')).toBe(true);
    expect(globToRegExp('backend/src/**/*.test.ts').test('backend/src/a/b.test.ts')).toBe(true);
    expect(
      globToRegExp('storefront/app/routes/checkout*.tsx').test(
        'storefront/app/routes/checkout-confirmation.tsx',
      ),
    ).toBe(true);
    expect(globToRegExp('storefront/app/root.tsx').test('storefront/app/root.tsx.bak')).toBe(false);
    expect(globToRegExp('storefront/tailwind.config.*').test('storefront/tailwind.config.ts')).toBe(
      true,
    );
  });
});

describe('ownedFileViolations', () => {
  it('allows gen_backend to edit schema, resolvers, state, and tests', () => {
    expect(
      ownedFileViolations('gen_backend', [
        'backend/src/schema/loyalty.ts',
        'backend/src/resolvers/loyalty.ts',
        'backend/src/resolvers/loyalty.test.ts',
        'backend/src/state/loyalty.ts',
        'backend/src/__generated__/resolvers-types.ts',
        'backend/package.json',
      ]),
    ).toEqual([]);
  });

  it('flags protected backend paths for every task', () => {
    for (const taskId of ['gen_backend', 'backend_fix', 'gen_homepage', 'visual_fix']) {
      expect(ownedFileViolations(taskId, ['backend/src/data/schema.ts'])).toEqual([
        { path: 'backend/src/data/schema.ts', kind: 'protected' },
      ]);
      expect(ownedFileViolations(taskId, ['backend/tests/contract/cart.test.ts'])).toEqual([
        { path: 'backend/tests/contract/cart.test.ts', kind: 'protected' },
      ]);
    }
  });

  it('treats paths outside the template copies as protected', () => {
    expect(ownedFileViolations('gen_theme', ['data/products.json', 'manual/manual.md'])).toEqual([
      { path: 'data/products.json', kind: 'protected' },
      { path: 'manual/manual.md', kind: 'protected' },
    ]);
  });

  it('reports storefront edits by a backend task as cross-slice', () => {
    expect(ownedFileViolations('gen_backend', ['storefront/app/routes/home.tsx'])).toEqual([
      { path: 'storefront/app/routes/home.tsx', kind: 'cross_slice' },
    ]);
  });

  it('reports backend edits by a storefront task as cross-slice', () => {
    expect(ownedFileViolations('gen_product', ['backend/src/schema/shop.ts'])).toEqual([
      { path: 'backend/src/schema/shop.ts', kind: 'cross_slice' },
    ]);
  });

  it('keeps storefront slices per task and shares lib, components, and routes.ts', () => {
    expect(
      ownedFileViolations('gen_homepage', [
        'storefront/app/routes/home.tsx',
        'storefront/app/lib/queries.ts',
        'storefront/app/components/storefront.tsx',
        'storefront/app/routes.ts',
      ]),
    ).toEqual([]);
    expect(ownedFileViolations('gen_homepage', ['storefront/app/routes/product.tsx'])).toEqual([
      { path: 'storefront/app/routes/product.tsx', kind: 'cross_slice' },
    ]);
    expect(ownedFileViolations('visual_fix', ['storefront/app/routes/product.tsx'])).toEqual([]);
  });

  it('gives shop-specific tasks the whole app tree', () => {
    expect(allowedGlobs('gift_card_purchase')).toContain('storefront/app/**');
    expect(ownedFileViolations('gift_card_purchase', ['storefront/app/routes/gift.tsx'])).toEqual(
      [],
    );
  });
});
