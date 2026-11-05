/**
 * `account_flow` and `discount_flow` in a real browser against the gen
 * stub storefront, which keeps the template's forms, labels and messages.
 * A stub route that answers 500, a renamed label, or a dropped code check
 * stands in for a page a task broke.
 */

import * as fs from 'node:fs/promises';
import type * as http from 'node:http';
import * as os from 'node:os';
import * as path from 'node:path';

import type { VerifierContext, VerifierResult } from '@shop-gym/harness';
import { afterEach, describe, expect, it } from 'vitest';

import { type StubStorefrontOptions, stubStorefront } from '../../testing.js';
import { defaultBackendTemplateDir } from '../seed.js';
import { accountFlowVerifier } from './account_flow.js';
import type { StepRecord } from './browser_steps.js';
import { discountFlowVerifier } from './discount_flow.js';

const FIXTURE_DIR = path.join(defaultBackendTemplateDir(), 'tests', 'fixtures', 'sandbox_shop_v0');
const DATASET_FILES = ['collections.json', 'products.json', 'pages.json', 'policies.json'];

let server: http.Server | undefined;
const tempDirs: string[] = [];

afterEach(async () => {
  await new Promise<void>((resolve) => (server ? server.close(() => resolve()) : resolve()));
  server = undefined;
  await Promise.all(tempDirs.splice(0).map((dir) => fs.rm(dir, { recursive: true, force: true })));
});

async function serve(options?: StubStorefrontOptions): Promise<string> {
  server = stubStorefront(options);
  await new Promise<void>((resolve) => server?.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (address === null || typeof address === 'string') throw new Error('no port');
  return `http://127.0.0.1:${address.port}`;
}

async function ctx(selectedTaskId: string): Promise<VerifierContext> {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'browser-flow-'));
  tempDirs.push(runDir);
  return { runDir, iterId: 'exec-0001', selectedTaskId, plan: [], artifactDir: runDir };
}

function steps(result: VerifierResult): [string, string][] {
  const records = (result.details as { steps: StepRecord[] }).steps;
  return records.map((record) => [record.name, record.status]);
}

/** A copy of the fixture data in which every Discount code needs a 500.00 subtotal. */
async function noApplicableCodeDir(): Promise<string> {
  const dataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'discount-flow-'));
  tempDirs.push(dataDir);
  for (const name of DATASET_FILES) {
    await fs.copyFile(path.join(FIXTURE_DIR, name), path.join(dataDir, name));
  }
  const commerce = JSON.parse(
    await fs.readFile(path.join(FIXTURE_DIR, 'commerce.json'), 'utf-8'),
  ) as { discount_codes: object[] };
  commerce.discount_codes = commerce.discount_codes.map((code) => ({
    ...code,
    minimum_subtotal: '500.00',
  }));
  await fs.writeFile(path.join(dataDir, 'commerce.json'), JSON.stringify(commerce));
  return dataDir;
}

describe('appliesTo', () => {
  it('gates account_flow on gen_account and visual_fix', () => {
    const verifier = accountFlowVerifier({ target: { url: 'http://127.0.0.1:1' } });
    expect(['gen_account', 'visual_fix', 'gen_checkout'].map(verifier.appliesTo)).toEqual([
      true,
      true,
      false,
    ]);
  });

  it('gates discount_flow on gen_checkout and visual_fix', () => {
    const verifier = discountFlowVerifier({
      target: { url: 'http://127.0.0.1:1' },
      dataDir: FIXTURE_DIR,
    });
    expect(['gen_checkout', 'visual_fix', 'gen_account'].map(verifier.appliesTo)).toEqual([
      true,
      true,
      false,
    ]);
  });
});

describe('account_flow', () => {
  it('passes when every account step works', async () => {
    const result = await accountFlowVerifier({ target: { url: await serve() } }).run(
      await ctx('gen_account'),
    );
    expect(result.verdict).toBe('pass');
    expect(steps(result)).toEqual([
      ['signUp', 'pass'],
      ['logOut', 'pass'],
      ['requestPasswordReset', 'pass'],
      ['logIn', 'pass'],
      ['addAddress', 'pass'],
      ['editAddress', 'pass'],
    ]);
  }, 60_000);

  it('fails at the first broken step and names it', async () => {
    const url = await serve({ broken: ['/account/addresses'] });
    const result = await accountFlowVerifier({ target: { url } }).run(await ctx('gen_account'));
    expect(result.verdict).toBe('fail');
    expect(steps(result).slice(-2)).toEqual([
      ['logIn', 'pass'],
      ['addAddress', 'fail'],
    ]);
    expect(result.feedback).toContain(
      '`account_flow`: the account flow broke at step `addAddress`.',
    );
  }, 60_000);

  it('fails at the password reset when the restyle renames its link', async () => {
    const url = await serve({ relabel: { 'Forgot your password?': 'Reset your password' } });
    const result = await accountFlowVerifier({ target: { url } }).run(await ctx('gen_account'));
    expect(result.verdict).toBe('fail');
    expect(steps(result)).toEqual([
      ['signUp', 'pass'],
      ['logOut', 'pass'],
      ['requestPasswordReset', 'fail'],
    ]);
    expect(result.feedback).toContain('no "Forgot your password?" link on /account/login');
  }, 60_000);
});

describe('discount_flow', () => {
  it('passes when a Discount code from the Dataset changes the total and an unknown code is turned down', async () => {
    const result = await discountFlowVerifier({
      target: { url: await serve() },
      dataDir: FIXTURE_DIR,
    }).run(await ctx('gen_checkout'));
    expect(result.verdict).toBe('pass');
    expect(steps(result)).toEqual([
      ['addToCart', 'pass'],
      ['applyDiscountCode', 'pass'],
      ['rejectDiscountCode', 'pass'],
    ]);
  }, 60_000);

  it('adds to cart when the product form carries its variant in a hidden input', async () => {
    const url = await serve({
      relabel: { 'type="radio" name="merchandiseId"': 'type="hidden" name="merchandiseId"' },
    });
    const productPage = await (await fetch(`${url}/products/any`)).text();
    expect(productPage).toContain('type="hidden" name="merchandiseId"');
    const result = await discountFlowVerifier({ target: { url }, dataDir: FIXTURE_DIR }).run(
      await ctx('gen_checkout'),
    );
    expect(result.verdict).toBe('pass');
    expect(steps(result)[0]).toEqual(['addToCart', 'pass']);
  }, 60_000);

  it('fails when checkout is broken and names the step', async () => {
    const url = await serve({ broken: ['/checkout'] });
    const result = await discountFlowVerifier({ target: { url }, dataDir: FIXTURE_DIR }).run(
      await ctx('gen_checkout'),
    );
    expect(result.verdict).toBe('fail');
    expect(steps(result)).toEqual([
      ['addToCart', 'pass'],
      ['applyDiscountCode', 'fail'],
    ]);
    expect(result.feedback).toContain(
      '`discount_flow`: the discount flow broke at step `applyDiscountCode`.',
    );
  }, 60_000);

  it('skips the valid code when no Discount code from the Dataset surely applies', async () => {
    const result = await discountFlowVerifier({
      target: { url: await serve() },
      dataDir: await noApplicableCodeDir(),
    }).run(await ctx('gen_checkout'));
    expect(result.verdict).toBe('pass');
    expect(steps(result)).toEqual([
      ['addToCart', 'pass'],
      ['applyDiscountCode', 'skipped'],
      ['rejectDiscountCode', 'pass'],
    ]);
  }, 60_000);

  it('fails when checkout applies an unknown code', async () => {
    // With no valid code applied first, the unknown code changes the total at once.
    const result = await discountFlowVerifier({
      target: { url: await serve({ acceptAnyDiscountCode: true }) },
      dataDir: await noApplicableCodeDir(),
    }).run(await ctx('gen_checkout'));
    expect(result.verdict).toBe('fail');
    expect(steps(result)).toEqual([
      ['addToCart', 'pass'],
      ['applyDiscountCode', 'skipped'],
      ['rejectDiscountCode', 'fail'],
    ]);
    expect(result.feedback).toContain(
      '`discount_flow`: the discount flow broke at step `rejectDiscountCode`.',
    );
  }, 60_000);
});
