import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { anonymizationVerifier, brandTokens, leakScanner, scanParts } from './anonymization.js';

const HOST = 'brand-leakcanary.example.com';
const HTML = `<!doctype html><html><head>
<title>Brand Leakcanary | Brutalist Vases &amp; Objects</title>
<meta property="og:site_name" content="Brand Leakcanary">
</head><body></body></html>`;

const CLEAN_PART = `## Cart Drawer

The cart opens as a right-side drawer from the header icon; see
evidence/cart_drawer/snapshots/01-empty.md.

### Empty state

- **Type:** slide-in drawer
- **Layout:** single column, full viewport height
- **Content:** headline, continue-shopping link, 3 featured products
- **Behavior:** closes on overlay click or escape
- **Styling:** light surface, drop shadow on the left edge
- **UX Notes:** focus moves to the close button on open

### Edge cases & gaps

- **Type:** N/A
- **Layout:** N/A
- **Content:** N/A
- **Behavior:** N/A
- **Styling:** N/A
- **UX Notes:** shipping estimate was not reachable without a region
`;

let artifactDir: string;

beforeEach(() => {
  artifactDir = mkdtempSync(join(tmpdir(), 'anon-'));
  mkdirSync(join(artifactDir, 'prefetch'));
  mkdirSync(join(artifactDir, 'parts'));
  writeFileSync(join(artifactDir, 'prefetch', 'index.html'), HTML);
});

afterEach(() => {
  rmSync(artifactDir, { recursive: true, force: true });
});

describe('brandTokens', () => {
  it('derives tokens from the host, the title segments, and og:site_name', () => {
    const tokens = brandTokens(HOST, HTML);
    expect(tokens).toContain('brand-leakcanary');
    expect(tokens).toContain('leakcanary');
    expect(tokens).toContain('brutalist');
    expect(tokens).toContain('brandleakcanary');
    expect(tokens).not.toContain('www');
    expect(tokens).not.toContain('com');
  });
});

describe('leakScanner', () => {
  const scan = leakScanner(HOST, HTML);

  it('passes structural prose', () => {
    expect(scan('parts/cart_drawer.md', CLEAN_PART)).toEqual([]);
  });

  it.each([
    HOST,
    `www.${HOST}`,
    `https://${HOST}/collections/all`,
    'Brand Leakcanary',
    'brand leakcanary',
    'LeakCanary',
    'LeakCanary01-Brutalist-Vase-Limited-Edition',
    'support@example-shop.com',
  ])('flags %s with the file and line', (marker) => {
    const text = `${CLEAN_PART}\nSold exclusively at ${marker}.\n`;
    const leaks = scan('parts/cart_drawer.md', text);
    expect(leaks).toHaveLength(1);
    expect(leaks[0]).toMatchObject({ file: 'parts/cart_drawer.md', line: 24 });
    expect(leaks[0]?.text).toContain(marker);
  });

  it('does not flag words that merely contain a token', () => {
    expect(scan('p.md', 'a brutalistic font and a canary-yellow badge')).toEqual([]);
  });
});

describe('anonymizationVerifier', () => {
  const verifier = anonymizationVerifier(`https://${HOST}`);
  const ctx = () => ({
    runDir: join(artifactDir, '..'),
    iterId: 'exec-0001',
    selectedTaskId: 'cart_drawer',
    plan: [],
    artifactDir,
  });

  it('is named and applies to every task', () => {
    expect(verifier.name).toBe('anonymization');
    expect(verifier.appliesTo('anything')).toBe(true);
  });

  it('passes a clean parts directory', async () => {
    writeFileSync(join(artifactDir, 'parts', 'cart_drawer.md'), CLEAN_PART);
    await expect(verifier.run(ctx())).resolves.toEqual({ verdict: 'pass' });
  });

  it('fails with feedback listing every offending line', async () => {
    writeFileSync(
      join(artifactDir, 'parts', 'cart_drawer.md'),
      `${CLEAN_PART}\nSee https://${HOST}/cart for details.\nContact hello@${HOST}.\n`,
    );
    writeFileSync(join(artifactDir, 'parts', 'footer.md'), '## Footer\n\nfine\n');
    const result = await verifier.run(ctx());
    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain('parts/cart_drawer.md:24');
    expect(result.feedback).toContain('parts/cart_drawer.md:25');
    expect(result.feedback).not.toContain('footer.md');
    expect(result.details).toMatchObject({ leaks: 2 });
  });

  it('scans only markdown parts', () => {
    writeFileSync(
      join(artifactDir, 'parts', 'cart.caps.json'),
      `{"shop":{"descriptor":"${HOST}"}}`,
    );
    expect(scanParts(join(artifactDir, 'parts'), leakScanner(HOST, HTML))).toEqual([]);
  });
});
