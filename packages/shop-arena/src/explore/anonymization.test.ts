import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  AnonymizationLeakError,
  anonymizationVerifier,
  brandTokens,
  leakScanner,
  publishedLeaks,
} from './anonymization.js';

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

let runDir: string;
let artifactDir: string;

beforeEach(() => {
  runDir = mkdtempSync(join(tmpdir(), 'anon-'));
  artifactDir = join(runDir, 'artifact');
  mkdirSync(join(artifactDir, 'prefetch'), { recursive: true });
  mkdirSync(join(artifactDir, 'parts'));
  writeFileSync(join(artifactDir, 'prefetch', 'index.html'), HTML);
});

afterEach(() => {
  rmSync(runDir, { recursive: true, force: true });
});

describe('brandTokens', () => {
  it('derives tokens from the host, the brand segment, and og:site_name', () => {
    const tokens = brandTokens(HOST, HTML);
    expect(tokens).toContain('brand-leakcanary');
    expect(tokens).toContain('leakcanary');
    expect(tokens).toContain('brandleakcanary');
    expect(tokens).not.toContain('brutalist');
    expect(tokens).not.toContain('www');
    expect(tokens).not.toContain('com');
  });

  const page = (title: string) => `<html><head><title>${title}</title></head></html>`;

  it.each([
    {
      shape: 'brand segment, then a tagline of sentences',
      host: 'fixturemart.localhost',
      title: 'Fixture Mart. Spend less. Shop more.',
      brand: ['fixture', 'mart', 'fixturemart'],
      tagline: ['spend', 'less', 'more'],
    },
    {
      shape: 'brand segment with the top-level domain',
      host: 'www.fixturemart.com',
      title: 'FixtureMart.com. Spend less. Shop more.',
      brand: ['fixturemart', 'fixturemartcom'],
      tagline: ['spend', 'less', 'more'],
    },
    {
      shape: 'tagline first, brand segment after a separator',
      host: 'www.fixture-mart.example',
      title: 'Deals every day | Fixture Mart',
      brand: ['fixture', 'mart', 'fixturemart'],
      tagline: ['deals', 'every', 'day'],
    },
    {
      shape: 'question and exclamation marks',
      host: 'fixturemart.localhost',
      title: 'Bored? Play more! Fixture Mart',
      brand: ['fixture', 'mart'],
      tagline: ['bored', 'play', 'more'],
    },
  ])('keeps only the brand segment: $shape', ({ host, title, brand, tagline }) => {
    const tokens = brandTokens(host, page(title));
    expect(tokens).toEqual(expect.arrayContaining(brand));
    for (const word of tagline) expect(tokens).not.toContain(word);
  });

  it('uses every title segment when no segment matches a hostname label', () => {
    const tokens = brandTokens('127.0.0.1', page('Fixture Mart. Spend less. Shop more.'));
    expect(tokens).toEqual(expect.arrayContaining(['fixture', 'mart', 'spend', 'less', 'more']));
  });

  it('always takes og:site_name', () => {
    const html = `<html><head><title>Fixture Mart. Spend less.</title>
<meta property="og:site_name" content="Fixture Outlet"></head></html>`;
    const tokens = brandTokens('fixturemart.localhost', html);
    expect(tokens).toEqual(expect.arrayContaining(['fixture', 'outlet', 'fixtureoutlet']));
    expect(tokens).not.toContain('spend');
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
    'LeakCanary-Brutalist-Vase-Limited-Edition',
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

  describe('with brand terms', () => {
    const scanTerms = leakScanner(HOST, HTML, ['Nova Pass', 'Zephyr']);

    it.each([
      ['Nova Pass members', 'nova pass'],
      ['nova-pass badge', 'nova pass'],
      ['NOVA PASS', 'nova pass'],
      ['Zephyr TV', 'zephyr'],
    ])('flags %s as [%s]', (text, marker) => {
      expect(scanTerms('p.md', text)).toEqual([{ file: 'p.md', line: 1, marker, text }]);
    });

    it.each(['a nova sale and a hall pass', 'pass nova', 'novapass', 'zephyrs'])(
      'does not flag %s',
      (text) => {
        expect(scanTerms('p.md', text)).toEqual([]);
      },
    );

    it('rejects a term with no letter or digit', () => {
      expect(() => leakScanner(HOST, HTML, ['--'])).toThrow(/brand term "--"/);
      expect(() => anonymizationVerifier(`https://${HOST}`, [' '])).toThrow(/brand term " "/);
    });
  });
});

describe('publishedLeaks', () => {
  // With no hostname label in the title, every title word is a brand token.
  const scan = leakScanner('127.0.0.1', '<title>Free Shipping Outlet</title>');

  it('reads the values of a JSON file, not its keys', () => {
    const capabilities = `${JSON.stringify(
      { has_shipping_estimate: true, shop: { descriptor: 'free shipping on every order' } },
      null,
      2,
    )}\n`;
    expect(publishedLeaks(scan, { 'capabilities.json': capabilities })).toEqual([
      {
        file: 'capabilities.json',
        line: 4,
        marker: 'free',
        text: '"descriptor": "free shipping on every order"',
      },
    ]);
  });

  it('reads every line of a markdown file', () => {
    expect(publishedLeaks(scan, { 'manual.md': '# Manual\n\n## Shipping\n' })).toEqual([
      { file: 'manual.md', line: 3, marker: 'shipping', text: '## Shipping' },
    ]);
  });

  it('names every leak in the error message', () => {
    const leaks = publishedLeaks(scan, { 'manual.md': 'Shipping\nOutlet\n' });
    expect(new AnonymizationLeakError(leaks).message).toBe(
      [
        'the final anonymization scan found 2 leak(s) in the published files:',
        '- manual.md:1 [shipping]: Shipping',
        '- manual.md:2 [outlet]: Outlet',
      ].join('\n'),
    );
  });
});

describe('anonymizationVerifier', () => {
  const verifier = anonymizationVerifier(`https://${HOST}`);
  const ctx = (selectedTaskId = 'cart_drawer') => ({
    runDir,
    iterId: 'exec-0001',
    selectedTaskId,
    plan: [],
    artifactDir,
  });
  const leakyCart = `${CLEAN_PART}\nSee https://${HOST}/cart for details.\n`;

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

  it('blocks the task and names its fragment after two reopens', async () => {
    writeFileSync(join(artifactDir, 'parts', 'cart_drawer.md'), leakyCart);
    const first = await verifier.run(ctx());
    expect(first.verdict).toBe('fail');
    expect(first.blockNote).toBeUndefined();
    expect(first.feedback).toContain('1 of 2 reopens');
    const second = await verifier.run(ctx());
    expect(second.blockNote).toBeUndefined();
    expect(second.feedback).toContain('2 of 2 reopens');
    const third = await verifier.run(ctx());
    expect(third).toMatchObject({
      verdict: 'fail',
      blockNote: 'parts/cart_drawer.md still identifies the storefront after 2 reopens',
    });
    expect(third.feedback).toContain('parts/cart_drawer.md:24');
  });

  it('keeps the reopen count for a new verifier, as a resumed run does', async () => {
    writeFileSync(join(artifactDir, 'parts', 'cart_drawer.md'), leakyCart);
    await verifier.run(ctx());
    await verifier.run(ctx());
    const resumed = await anonymizationVerifier(`https://${HOST}`).run(ctx());
    expect(resumed.blockNote).toBeDefined();
  });

  it('counts the reopens of each task on its own', async () => {
    writeFileSync(join(artifactDir, 'parts', 'cart_drawer.md'), leakyCart);
    writeFileSync(join(artifactDir, 'parts', 'footer.md'), leakyCart);
    await verifier.run(ctx());
    await verifier.run(ctx());
    const footer = await verifier.run(ctx('footer'));
    expect(footer.blockNote).toBeUndefined();
    expect(footer.feedback).toContain('1 of 2 reopens');
  });

  it('checks only the markdown fragment of the current task', async () => {
    writeFileSync(join(artifactDir, 'parts', 'cart_drawer.md'), CLEAN_PART);
    writeFileSync(
      join(artifactDir, 'parts', 'cart_drawer.caps.json'),
      `{"shop":{"descriptor":"${HOST}"}}`,
    );
    writeFileSync(join(artifactDir, 'parts', 'footer.md'), `## Footer\n\nMade by ${HOST}.\n`);
    await expect(verifier.run(ctx())).resolves.toEqual({ verdict: 'pass' });
    expect((await verifier.run(ctx('footer'))).verdict).toBe('fail');
  });
});
