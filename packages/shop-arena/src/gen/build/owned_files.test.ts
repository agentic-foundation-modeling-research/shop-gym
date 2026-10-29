import { describe, expect, it } from 'vitest';

import { globToRegExp, ownedFileViolations } from './owned_files.js';

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
  const ON = { genBackend: true };
  const OFF = { genBackend: false };

  it('lets a backend task edit any unprotected backend path', () => {
    expect(
      ownedFileViolations(
        'gen_backend',
        [
          'backend/src/schema/loyalty.ts',
          'backend/src/resolvers/loyalty.test.ts',
          'backend/src/state/loyalty.ts',
          'backend/src/server.ts',
          'backend/package.json',
        ],
        ON,
      ),
    ).toEqual([]);
  });

  it('lets a storefront task edit any unprotected storefront path', () => {
    expect(
      ownedFileViolations(
        'gen_homepage',
        [
          'storefront/app/routes/home.tsx',
          'storefront/app/routes/product.tsx',
          'storefront/app/root.tsx',
          'storefront/app/routes/gift.tsx',
          'storefront/package.json',
        ],
        OFF,
      ),
    ).toEqual([]);
  });

  it('flags protected paths for every task', () => {
    for (const taskId of ['gen_backend', 'backend_fix', 'gen_homepage', 'visual_fix']) {
      expect(
        ownedFileViolations(
          taskId,
          ['backend/src/data/schema.ts', 'backend/tests/contract/cart.test.ts', 'storefront/.env'],
          ON,
        ),
      ).toEqual([
        { path: 'backend/src/data/schema.ts', kind: 'protected' },
        { path: 'backend/tests/contract/cart.test.ts', kind: 'protected' },
        { path: 'storefront/.env', kind: 'protected' },
      ]);
    }
  });

  it('treats paths outside the template copies as protected', () => {
    expect(
      ownedFileViolations('gen_theme', ['data/products.json', 'manual/manual.md'], ON),
    ).toEqual([
      { path: 'data/products.json', kind: 'protected' },
      { path: 'manual/manual.md', kind: 'protected' },
    ]);
  });

  it('protects the whole backend copy when backend generation is off', () => {
    for (const taskId of ['gen_product', 'gen_backend']) {
      expect(ownedFileViolations(taskId, ['backend/src/schema/shop.ts'], OFF)).toEqual([
        { path: 'backend/src/schema/shop.ts', kind: 'protected' },
      ]);
    }
  });

  it('reports edits in the other copy as not owned', () => {
    expect(ownedFileViolations('gen_backend', ['storefront/app/routes/home.tsx'], ON)).toEqual([
      { path: 'storefront/app/routes/home.tsx', kind: 'not_owned' },
    ]);
    expect(ownedFileViolations('gen_product', ['backend/src/schema/shop.ts'], ON)).toEqual([
      { path: 'backend/src/schema/shop.ts', kind: 'not_owned' },
    ]);
  });
});
