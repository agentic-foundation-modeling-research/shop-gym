import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { capabilitiesSchema } from '../../explore/capabilities.js';
import { type Tiebreaker, mergeCapabilities } from './capabilities.js';
import { MANUAL_PARTS, splitManual } from './split.js';
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

  it('copies a single manual and writes parts and manifest', async () => {
    const { writeManualFixture } = await import('../testing.js');
    const { manualMergeStep } = await import('./index.js');
    const seedDir = await writeManualFixture(path.join(root, 'seed'));
    const outDir = path.join(root, 'shop');
    await fs.mkdir(outDir);
    const step = manualMergeStep([seedDir]);
    await step.run({
      outDir,
      context: { manualDirs: [seedDir] } as never,
      log: () => undefined,
      signal: new AbortController().signal,
    });
    const files = (await fs.readdir(path.join(outDir, 'manual'))).sort();
    expect(files).toEqual([
      'capabilities.json',
      'manifest.json',
      'manual.md',
      'parts',
      'stats.json',
    ]);
    expect((await fs.readdir(path.join(outDir, 'manual', 'parts'))).length).toBe(6);
    const manifest = JSON.parse(
      await fs.readFile(path.join(outDir, 'manual', 'manifest.json'), 'utf-8'),
    );
    expect(manifest.schemaVersion).toBe(1);
    expect(manifest.seeds).toEqual([seedDir]);
  });
});
