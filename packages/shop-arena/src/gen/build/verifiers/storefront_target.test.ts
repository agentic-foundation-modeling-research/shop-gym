import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { readApplicableDiscountCode } from './storefront_target.js';

const FREESHIP = {
  code: 'FREESHIP',
  kind: 'free_shipping',
  amount: '0',
  minimum_subtotal: null,
  hint: 'Free shipping',
};
const SAVE5_OVER_30 = {
  code: 'SAVE5',
  kind: 'fixed_amount',
  amount: '5.00',
  minimum_subtotal: '30.00',
  hint: '$5 off orders over $30',
};
const WELCOME10 = {
  code: 'WELCOME10',
  kind: 'percentage',
  amount: '10',
  minimum_subtotal: null,
  hint: '10% off',
};

let dataDir: string | undefined;

afterEach(async () => {
  if (dataDir !== undefined) await fs.rm(dataDir, { recursive: true, force: true });
  dataDir = undefined;
});

async function datasetWith(commerceJson: string | undefined): Promise<string> {
  dataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'applicable-code-'));
  if (commerceJson !== undefined) {
    await fs.writeFile(path.join(dataDir, 'commerce.json'), commerceJson);
  }
  return dataDir;
}

function commerce(codes: readonly object[]): string {
  return JSON.stringify({ tax_rate: 0, discount_codes: codes });
}

describe('readApplicableDiscountCode', () => {
  it('picks a percent or fixed code with no minimum before a free-shipping code', async () => {
    const dir = await datasetWith(commerce([FREESHIP, SAVE5_OVER_30, WELCOME10]));

    expect(await readApplicableDiscountCode(dir)).toBe('WELCOME10');
  });

  it('falls back to a free-shipping code when every other code has a minimum', async () => {
    const dir = await datasetWith(commerce([SAVE5_OVER_30, FREESHIP]));

    expect(await readApplicableDiscountCode(dir)).toBe('FREESHIP');
  });

  it('finds no code when every code has a minimum', async () => {
    const dir = await datasetWith(commerce([SAVE5_OVER_30]));

    expect(await readApplicableDiscountCode(dir)).toBeUndefined();
  });

  it('finds no code when the Dataset has no commerce.json', async () => {
    const dir = await datasetWith(undefined);

    expect(await readApplicableDiscountCode(dir)).toBeUndefined();
  });

  it('throws when commerce.json is not a valid commerce settings file', async () => {
    const dir = await datasetWith(JSON.stringify({ discount_codes: [{ code: 'NOKIND' }] }));

    await expect(readApplicableDiscountCode(dir)).rejects.toThrow();
  });
});
