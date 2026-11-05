import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import type { LlmClient } from '@shop-gym/agent';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { capabilitiesSchema } from '../../explore/capabilities.js';
import { SynthError } from '../llm.js';
import { type Tiebreaker, mergeCapabilities } from './capabilities.js';
import { parseManualSections } from './prose.js';
import { MANUAL_PARTS, splitManual } from './split.js';
import { STANDARD_SUB_MANUAL_FILE, STANDARD_SUB_MANUAL_PATH } from './standard_sub_manual.js';
import { mergeStats } from './stats.js';

const seed = (overrides: Record<string, unknown>) => capabilitiesSchema.parse(overrides);

describe('mergeCapabilities', () => {
  it('returns the single seed unchanged', async () => {
    const only = seed({ shop: { descriptor: 'Homeware', currency: 'USD' } });
    const { capabilities, conflicts } = await mergeCapabilities([only]);
    expect(capabilities).toEqual(only);
    expect(conflicts).toEqual([]);
  });

  it('applies bool_union, scalar_majority with first-seed tiebreak, max, and capped list unions', async () => {
    const seeds = [
      seed({
        shop: { descriptor: 'Homeware', currency: 'USD', tone: ['calm', 'warm'] },
        site_shell: { has_mega_menu: false, nav_depth: 1 },
        cart: { type: 'drawer' },
        homepage: { section_types: ['hero', 'grid'], section_count: 2 },
      }),
      seed({
        shop: { descriptor: 'Homeware', currency: 'EUR', tone: ['bold', 'quiet'] },
        site_shell: { has_mega_menu: true, nav_depth: 3 },
        cart: { type: 'page' },
        homepage: { section_types: ['video'], section_count: 1 },
      }),
    ];
    const { capabilities, conflicts } = await mergeCapabilities(seeds);
    expect(capabilities.site_shell.has_mega_menu).toBe(true);
    expect(capabilities.site_shell.nav_depth).toBe(3);
    expect(capabilities.shop.currency).toBe('USD');
    expect(capabilities.cart.type).toBe('drawer');
    expect(capabilities.shop.tone).toEqual(['calm', 'warm', 'bold']);
    expect(capabilities.homepage.section_types).toEqual(['hero', 'grid']);
    expect(conflicts.map((c) => c.path)).toContain('shop.currency');
    expect(conflicts.find((c) => c.path === 'shop.currency')?.tiebreak).toBe('first_seed');
  });

  it('asks the tiebreaker for descriptors and tied layouts, falling back on out-of-set replies', async () => {
    const calls: string[] = [];
    const tiebreaker: Tiebreaker = {
      descriptor: async (_tone, descriptors) => {
        calls.push(`descriptor:${descriptors.join('|')}`);
        return 'Modern Homeware';
      },
      layout: async (p, candidates) => {
        calls.push(`layout:${p}:${candidates.join('|')}`);
        return p === 'collection.layout' ? 'list' : 'not-a-candidate';
      },
    };
    const seeds = [
      seed({
        shop: { descriptor: 'Homeware' },
        collection: { layout: 'grid' },
        product: { gallery_style: 'stack' },
      }),
      seed({
        shop: { descriptor: 'Home Goods' },
        collection: { layout: 'list' },
        product: { gallery_style: 'carousel' },
      }),
    ];
    const { capabilities, conflicts } = await mergeCapabilities(seeds, tiebreaker);
    expect(capabilities.shop.descriptor).toBe('Modern Homeware');
    expect(capabilities.collection.layout).toBe('list');
    expect(capabilities.product.gallery_style).toBe('stack');
    expect(calls).toContain('descriptor:Homeware|Home Goods');
    expect(conflicts.find((c) => c.path === 'collection.layout')?.tiebreak).toBe('llm');
  });

  it('throws when descriptors differ and no tiebreaker is given', async () => {
    await expect(
      mergeCapabilities([seed({ shop: { descriptor: 'A' } }), seed({ shop: { descriptor: 'B' } })]),
    ).rejects.toThrow();
  });
});

describe('splitManual', () => {
  it('routes H2 sections into six parts with placeholders for empty ones', () => {
    const manual =
      '# Shop Manual - X\n\n## Overview\n\nintro\n\n## Site shell\n\nnav body\n\n## Cart\n\ncart body\n\n## Extra\n\nx\n';
    const warnings: string[] = [];
    const parts = splitManual(manual, (line) => warnings.push(line));
    expect(Object.keys(parts).sort()).toEqual([...MANUAL_PARTS].sort());
    expect(parts.navigation).toContain('nav body');
    expect(parts.cart_and_search).toContain('cart body');
    expect(parts.product).toContain('no sections');
    expect(warnings.some((w) => w.includes('"Extra"'))).toBe(true);
  });

  it('leaves the Account and Checkout sections to fusion and does not report them', () => {
    const manual =
      '# Shop Manual - X\n\n## Cart\n\ncart body\n\n## Checkout\n\ncheckout notes\n\n## Account\n\naccount notes\n';
    const warnings: string[] = [];
    const parts = splitManual(manual, (line) => warnings.push(line));
    expect(warnings).toEqual([]);
    for (const part of MANUAL_PARTS) {
      expect(parts[part]).not.toMatch(/checkout notes|account notes/);
    }
  });
});

describe('mergeStats', () => {
  it('takes medians and unions, and recomputes structural counts from capabilities', () => {
    const base = {
      products_total: 10,
      collections_total: 2,
      products_per_collection: { avg: 5, median: 5, max: 6 },
      price: { min: 1, max: 10, median: 5, currency: 'USD' },
      products_with_variants_pct: 50,
      variant_axes_observed: ['Size'],
      navigation_depth_max: 1,
      homepage_section_count: 2,
      info_pages_count: 1,
      feature_count: 3,
    };
    const merged = mergeStats(
      [
        base,
        {
          ...base,
          products_total: 30,
          variant_axes_observed: ['Color'],
          price: { ...base.price, max: 40 },
        },
      ],
      seed({ site_shell: { nav_depth: 2 }, homepage: { section_count: 4 } }),
    );
    expect(merged.products_total).toBe(20);
    expect(merged.price.max).toBe(40);
    expect(merged.variant_axes_observed).toEqual(['Size', 'Color']);
    expect(merged.navigation_depth_max).toBe(2);
    expect(merged.homepage_section_count).toBe(4);
  });
});

describe('runManualMerge', () => {
  let root: string;
  beforeEach(async () => {
    root = await fs.mkdtemp(path.join(os.tmpdir(), 'manual-merge-'));
  });
  afterEach(async () => {
    await fs.rm(root, { recursive: true, force: true });
  });

  it('copies a single manual and writes the Sub-manuals and manifest', async () => {
    const { ScriptedFusionLlm, writeManualFixture } = await import('../testing.js');
    const { manualMergeStep } = await import('./index.js');
    const seedDir = await writeManualFixture(path.join(root, 'seed'));
    const outDir = path.join(root, 'shop');
    await fs.mkdir(outDir);
    const step = manualMergeStep([seedDir]);
    const llm = new ScriptedFusionLlm();
    await step.run({
      outDir,
      context: mergeContext([seedDir], llm),
      log: () => undefined,
      signal: new AbortController().signal,
    });
    // The fixture manual has no Account or Checkout notes, so nothing is fused.
    expect(llm.requests).toEqual([]);
    const files = (await fs.readdir(path.join(outDir, 'manual'))).sort();
    expect(files).toEqual([
      'capabilities.json',
      'manifest.json',
      'manual.md',
      'parts',
      'stats.json',
    ]);
    expect((await fs.readdir(path.join(outDir, 'manual', 'parts'))).sort()).toEqual(
      [...MANUAL_PARTS.map((part) => `${part}.md`), STANDARD_SUB_MANUAL_FILE].sort(),
    );
    expect(
      await fs.readFile(path.join(outDir, 'manual', 'parts', STANDARD_SUB_MANUAL_FILE), 'utf-8'),
    ).toBe(await fs.readFile(STANDARD_SUB_MANUAL_PATH, 'utf-8'));
    const manifest = JSON.parse(
      await fs.readFile(path.join(outDir, 'manual', 'manifest.json'), 'utf-8'),
    );
    expect(manifest.schemaVersion).toBe(1);
    expect(manifest.seeds).toEqual([seedDir]);
  });

  it('lists the Standard sub-manual as a step input, so an edit to it reruns the step', async () => {
    const { manualMergeStep } = await import('./index.js');
    expect(manualMergeStep([path.join(root, 'seed')]).inputs).toContain(STANDARD_SUB_MANUAL_PATH);
  });

  describe('fusion of observed Account and Checkout notes', () => {
    let standard: string;
    let sections: Map<string, string>;
    beforeEach(async () => {
      standard = await fs.readFile(STANDARD_SUB_MANUAL_PATH, 'utf-8');
      sections = parseManualSections(standard);
    });

    /** The checked-in body of `## <name>`. */
    const standardBody = (name: string): string => sections.get(name) ?? '';

    /**
     * Runs `manual_merge` on one seed whose `manual.md` ends with
     * `observed`; returns the shop's `parts/standard.md`.
     */
    async function mergeWithNotes(
      observed: string,
      llm: LlmClient,
      log: string[] = [],
    ): Promise<string> {
      const { writeManualFixture } = await import('../testing.js');
      const { manualMergeStep } = await import('./index.js');
      const seedDir = await writeManualFixture(path.join(root, 'seed'));
      await fs.appendFile(path.join(seedDir, 'manual.md'), `\n${observed}`);
      const outDir = path.join(root, 'shop');
      await fs.mkdir(outDir, { recursive: true });
      await manualMergeStep([seedDir]).run({
        outDir,
        context: mergeContext([seedDir], llm),
        log: (line) => log.push(line),
        signal: new AbortController().signal,
      });
      return fs.readFile(path.join(outDir, 'manual', 'parts', STANDARD_SUB_MANUAL_FILE), 'utf-8');
    }

    it('copies the file unchanged with no LLM call when the observed sections are blank', async () => {
      const { ScriptedFusionLlm } = await import('../testing.js');
      const llm = new ScriptedFusionLlm();
      const fused = await mergeWithNotes('## Checkout\n\n   \n\n## Account\n', llm);
      expect(llm.requests).toEqual([]);
      expect(fused).toBe(standard);
    });

    it('fuses each observed section into its own section and keeps the rest of the file', async () => {
      const { ScriptedFusionLlm } = await import('../testing.js');
      const account = standardBody('Account').replace('H1 "Login"', 'H1 "Sign in"');
      const checkout = standardBody('Checkout').replace('"Pay now"', '"Complete order"');
      const llm = new ScriptedFusionLlm({ Account: [account], Checkout: [checkout] });
      const log: string[] = [];
      const fused = await mergeWithNotes(
        [
          '## Checkout',
          '',
          '### Pay button',
          '',
          '- The button under the payment methods reads "Complete order".',
          '',
          '## Account',
          '',
          '### Login page',
          '',
          '- The heading reads "Sign in".',
          '',
        ].join('\n'),
        llm,
        log,
      );

      expect(llm.requests).toHaveLength(2);
      const [accountPrompt, checkoutPrompt] = llm.requests.map((r) => String(r.prompt));
      expect(accountPrompt).toContain('- The heading reads "Sign in".');
      expect(accountPrompt).toContain(standardBody('Account'));
      expect(accountPrompt).toContain(standardBody('Supported behavior'));
      expect(checkoutPrompt).toContain('reads "Complete order".');
      expect(checkoutPrompt).toContain(standardBody('Checkout'));
      // A section never gets the checked labels of the other section.
      expect(accountPrompt).not.toContain('"Enter a valid discount code"');
      expect(checkoutPrompt).not.toContain('"Add a new address"');

      // The observed labels win, and nothing outside the two sections changes.
      expect(fused).toBe(
        standard
          .replace(standardBody('Account'), account)
          .replace(standardBody('Checkout'), checkout),
      );
      expect(fused).toContain('H1 "Sign in"');
      expect(fused).not.toContain('H1 "Login"');
      expect(log.filter((line) => line.includes('fused the observed'))).toHaveLength(2);
      expect(log.filter((line) => line.includes('is not routed'))).toEqual([]);
    });

    it('asks once more when a reply renames a checked label, and keeps the checked label', async () => {
      const { ScriptedFusionLlm } = await import('../testing.js');
      const renamed = standardBody('Account').replaceAll(
        '"Forgot your password?"',
        '"Forgot password?"',
      );
      const kept = standardBody('Account').replace('H1 "Login"', 'H1 "Sign in"');
      const llm = new ScriptedFusionLlm({ Account: [renamed, kept] });
      const fused = await mergeWithNotes(
        '## Account\n\n- Heading "Sign in", then the link "Forgot password?".\n',
        llm,
      );

      // The retry asks again with the first prompt, after the reason for the retry.
      const [first, retry] = llm.requests.map((r) => String(r.prompt));
      expect(llm.requests).toHaveLength(2);
      expect(retry?.endsWith(first ?? '')).toBe(true);
      const reason = retry?.slice(0, retry.length - (first?.length ?? 0));
      expect(reason).toContain('"Forgot your password?"');
      expect(parseManualSections(fused).get('Account')).toBe(kept);
      expect(fused).not.toContain('"Forgot password?"');
    });

    it('fails the step when the retry still breaks a rule', async () => {
      const { ScriptedFusionLlm } = await import('../testing.js');
      const withHeading = `## Checkout\n\n${standardBody('Checkout')}`;
      const dropped = standardBody('Checkout').replaceAll('"Total"', '"Order total"');
      const llm = new ScriptedFusionLlm({ Checkout: [withHeading, dropped] });
      const error = await mergeWithNotes(
        '## Checkout\n\n- The last totals row reads "Order total".\n',
        llm,
      ).catch((err: unknown) => err);
      expect(error).toBeInstanceOf(SynthError);
      expect(String(error)).toContain('"Total"');
      expect(llm.requests).toHaveLength(2);
    });

    it('gives the LLM the supported behavior when the notes describe unsupported behavior', async () => {
      const { ScriptedFusionLlm } = await import('../testing.js');
      // The scripted fusion keeps the standard text, as the rules ask for unsupported behavior.
      const llm = new ScriptedFusionLlm();
      const fused = await mergeWithNotes(
        [
          '## Checkout',
          '',
          '- Express payment buttons sit above the form.',
          '',
          '## Account',
          '',
          '- Customers log in with a one-time code sent by email, or with a social login button.',
          '',
        ].join('\n'),
        llm,
      );

      expect(llm.requests).toHaveLength(2);
      for (const request of llm.requests) {
        expect(String(request.prompt)).toContain(standardBody('Supported behavior'));
      }
      expect(String(llm.requests[0]?.prompt)).toContain('one-time code sent by email');
      expect(String(llm.requests[1]?.prompt)).toContain('Express payment buttons sit above');
      // Replies that keep the standard text give back the checked-in file byte for byte.
      expect(fused).toBe(standard);
    });
  });
});

/** The `GenContext` fields that `manual_merge` reads. */
function mergeContext(manualDirs: readonly string[], llm: LlmClient): never {
  return {
    manualDirs,
    llm,
    model: { provider: 'fake', id: 'scripted' },
    config: { llmTimeoutMs: 10_000 },
  } as never;
}
