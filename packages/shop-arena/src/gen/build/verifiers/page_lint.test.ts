/**
 * `page_lint` in a real `BrowserSession`: the rules on small hand-written
 * pages loaded with `setContent`, and the verifier over the gen stub
 * storefront, whose styled pages and open cart drawer pass. A relabel of
 * the stub's stylesheet stands in for a restyle that broke the drawer.
 */

import * as fs from 'node:fs/promises';
import type * as http from 'node:http';
import * as os from 'node:os';
import * as path from 'node:path';

import { BrowserSession } from '@shop-gym/browser';
import type { VerifierContext } from '@shop-gym/harness';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { type StubStorefrontOptions, stubStorefront } from '../../testing.js';
import { defaultBackendTemplateDir } from '../seed.js';
import {
  type LintScope,
  type PageLintResult,
  lintLoadedPage,
  pageLintVerifier,
} from './page_lint.js';

const FIXTURE_DIR = path.join(defaultBackendTemplateDir(), 'tests', 'fixtures', 'sandbox_shop_v0');

/** Shop styles for every checked control type. */
const SHOP_STYLES = `<style>
button,input,select,textarea{background:#fff;border:1px solid #223344;border-radius:4px}
input[type=checkbox],input[type=radio]{accent-color:#223344}
</style>`;

/** An open cart drawer; `backdrop` and `drawer` add CSS to the two components. */
function drawerPage(options: { backdrop?: string; drawer?: string; body?: string } = {}): string {
  return `<!doctype html><html><head>${SHOP_STYLES}<style>
body{margin:0}
.cart-backdrop{position:fixed;inset:0;border:0;border-radius:0;background:rgba(0,0,0,.4);${options.backdrop ?? ''}}
.cart-drawer{position:fixed;top:0;right:0;bottom:0;width:320px;padding:16px;box-sizing:border-box;background:#fff;${options.drawer ?? ''}}
</style></head><body><main><button class="buy">Add to cart</button></main>
<div class="cart-popup"><button type="button" class="cart-backdrop" aria-label="Close cart drawer"></button>
<aside id="cart-drawer" class="cart-drawer" role="dialog"><h2>Cart</h2>${options.body ?? '<p>1 x Oak Bowl</p>'}<button type="button">Close</button></aside></div>
</body></html>`;
}

let session: BrowserSession;

beforeAll(async () => {
  session = await BrowserSession.launch({ episodeId: 'page-lint-test' });
});

afterAll(async () => {
  await session.close();
});

async function lint(html: string, scope: LintScope = 'page') {
  await session.page.setContent(html);
  return lintLoadedPage(session.page, scope);
}

describe('lintLoadedPage', () => {
  it('fails a bare button and names its selector and text', async () => {
    const findings = await lint('<main><button class="buy">Add to cart</button></main>');
    expect(findings).toEqual([
      {
        rule: 'unstyled_control',
        selector: 'main > button.buy',
        text: 'Add to cart',
        detail: expect.stringContaining('browser default look of a bare `button`'),
      },
    ]);
  });

  it('fails a bare checkbox and names it by its label', async () => {
    const findings = await lint(
      '<form id="gift"><label><input type="checkbox" name="gift"> This is a gift</label></form>',
    );
    expect(findings).toEqual([
      {
        rule: 'unstyled_control',
        selector: '#gift > label > input',
        text: 'This is a gift',
        detail: expect.stringContaining('`input[type="checkbox"]`'),
      },
    ]);
  });

  it('passes styled controls of every checked type', async () => {
    const findings = await lint(`${SHOP_STYLES}<form>
      <button>Buy</button>
      ${['text', 'number', 'email', 'password', 'search', 'checkbox', 'radio']
        .map((type) => `<input type="${type}" name="${type}">`)
        .join('')}
      <select name="sort"><option>Newest</option></select><textarea name="note"></textarea>
    </form>`);
    expect(findings).toEqual([]);
  });

  it('passes a checkbox drawn with appearance none', async () => {
    const findings = await lint(
      '<input type="checkbox" style="appearance:none;width:16px;height:16px;border:1px solid #223344">',
    );
    expect(findings).toEqual([]);
  });

  it('still fails a button whose only change is a round radius', async () => {
    const findings = await lint(
      '<button style="border-radius:999px;padding:8px 16px">Buy</button>',
    );
    expect(findings.map((finding) => finding.rule)).toEqual(['unstyled_control']);
  });

  it('ignores hidden, transparent and off-screen controls', async () => {
    const findings = await lint(`<main>
      <button style="display:none">Hidden</button>
      <button style="visibility:hidden">Invisible</button>
      <label><input type="radio" name="variant" style="opacity:0"> Small</label>
      <button style="position:absolute;left:-9999px">Off screen</button>
      <div style="opacity:0"><button>Faded</button></div>
      <details><summary>More</summary><input type="text" name="closed"></details>
      <input type="hidden" name="intent" value="add">
    </main>`);
    expect(findings).toEqual([]);
  });

  it('fails the visible placeholder variant title "Default Title"', async () => {
    const findings = await lint(
      '<div class="cart-line"><p class="muted">Default Title</p><p hidden>Default Title</p></div>',
    );
    expect(findings).toEqual([
      {
        rule: 'placeholder_title',
        selector: 'div.cart-line > p.muted',
        text: 'Default Title',
        detail: expect.stringContaining('"Default Title"'),
      },
    ]);
  });

  describe('in the open cart drawer', () => {
    it('passes a backdrop that covers the viewport with square corners', async () => {
      expect(await lint(drawerPage(), 'cartDrawer')).toEqual([]);
    });

    it('fails the giant-pill backdrop', async () => {
      const findings = await lint(drawerPage({ backdrop: 'border-radius:999px' }), 'cartDrawer');
      expect(findings).toEqual([
        {
          rule: 'drawer_backdrop',
          selector: 'div.cart-popup > button.cart-backdrop',
          text: 'Close cart drawer',
          detail: expect.stringContaining('rounded corners (999px'),
        },
      ]);
    });

    it('fails a backdrop that does not cover the whole viewport', async () => {
      const findings = await lint(drawerPage({ backdrop: 'bottom:50%' }), 'cartDrawer');
      expect(findings.map((finding) => [finding.rule, finding.detail])).toEqual([
        ['drawer_backdrop', expect.stringContaining('does not cover the whole viewport')],
      ]);
    });

    it('fails a drawer without a backdrop', async () => {
      const findings = await lint(drawerPage({ backdrop: 'display:none' }), 'cartDrawer');
      expect(findings.map((finding) => finding.rule)).toEqual(['drawer_backdrop']);
    });

    it('fails an image wider than the drawer content box', async () => {
      const findings = await lint(
        drawerPage({
          body: '<img class="cart-line-image" alt="Oak Bowl" style="display:block;width:400px;height:40px">',
        }),
        'cartDrawer',
      );
      expect(findings).toEqual([
        {
          rule: 'drawer_image',
          selector: '#cart-drawer > img.cart-line-image',
          text: 'Oak Bowl',
          detail: expect.stringContaining('400px wide, wider than the 288px'),
        },
      ]);
    });

    it('checks the controls and text inside the drawer only', async () => {
      const findings = await lint(
        drawerPage({
          backdrop: 'background:rgba(0,0,0,.4)',
          body: '<p>Default Title</p><label><input type="checkbox"> This is a gift</label>',
        }).replace(SHOP_STYLES, '<style>.cart-drawer button{border:0}</style>'),
        'cartDrawer',
      );
      expect(findings.map((finding) => [finding.rule, finding.text])).toEqual([
        ['unstyled_control', 'This is a gift'],
        ['placeholder_title', 'Default Title'],
      ]);
    });

    it('fails when the drawer is not open', async () => {
      const findings = await lint('<main><h1>Oak Bowl</h1></main>', 'cartDrawer');
      expect(findings.map((finding) => finding.rule)).toEqual(['drawer_closed']);
    });
  });
});

describe('page_lint', () => {
  let server: http.Server | undefined;
  const runDirs: string[] = [];

  afterEach(async () => {
    await new Promise<void>((resolve) => (server ? server.close(() => resolve()) : resolve()));
    server = undefined;
    await Promise.all(runDirs.splice(0).map((dir) => fs.rm(dir, { recursive: true, force: true })));
  });

  async function serve(options?: StubStorefrontOptions): Promise<string> {
    server = stubStorefront(options);
    await new Promise<void>((resolve) => server?.listen(0, '127.0.0.1', resolve));
    const address = server.address();
    if (address === null || typeof address === 'string') throw new Error('no port');
    return `http://127.0.0.1:${address.port}`;
  }

  async function ctx(selectedTaskId: string): Promise<VerifierContext> {
    const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'page-lint-'));
    runDirs.push(runDir);
    return { runDir, iterId: 'exec-0001', selectedTaskId, plan: [], artifactDir: runDir };
  }

  function pagesOf(details: unknown): PageLintResult[] {
    return (details as { pages: PageLintResult[] }).pages;
  }

  it('applies to storefront page tasks only', () => {
    const verifier = pageLintVerifier({
      target: { url: 'http://127.0.0.1:1' },
      dataDir: FIXTURE_DIR,
    });
    expect(verifier.appliesTo('gen_homepage')).toBe(true);
    expect(verifier.appliesTo('visual_fix')).toBe(true);
    expect(verifier.appliesTo('gen_theme')).toBe(false);
    expect(verifier.appliesTo('gen_backend')).toBe(false);
  });

  it('passes every canonical page of the stub shop, the open cart drawer included', async () => {
    const url = await serve();
    const result = await pageLintVerifier({ target: { url }, dataDir: FIXTURE_DIR }).run(
      await ctx('visual_fix'),
    );
    expect(result.verdict, result.feedback).toBe('pass');
    const pages = pagesOf(result.details);
    expect(pages.map((page) => [page.name, page.status])).toEqual([
      ['home', 'pass'],
      ['collection', 'pass'],
      ['product', 'pass'],
      ['search', 'pass'],
      ['accountLogin', 'pass'],
      ['accountRegister', 'pass'],
      ['policy', 'pass'],
      ['cartDrawer', 'pass'],
      ['cart', 'pass'],
      ['checkout', 'pass'],
      ['thankYou', 'pass'],
      ['accountProfile', 'pass'],
      ['orderList', 'pass'],
      ['orderDetail', 'pass'],
      ['addresses', 'pass'],
    ]);
    expect(pages.find((page) => page.name === 'cartDrawer')?.route).toBe(
      '/products/shopliseum-mushroom-dog-toys?cart=open',
    );
  }, 120_000);

  it("lints only the pages of the task's buckets", async () => {
    const url = await serve();
    const verifier = pageLintVerifier({ target: { url }, dataDir: FIXTURE_DIR });
    const cartSearch = await verifier.run(await ctx('gen_cart_search'));
    expect(pagesOf(cartSearch.details).map((page) => page.name)).toEqual([
      'search',
      'cartDrawer',
      'cart',
    ]);
    const navigation = await verifier.run(await ctx('gen_navigation'));
    expect(pagesOf(navigation.details).map((page) => page.name)).toEqual(['home']);
  }, 120_000);

  it('fails the giant-pill backdrop and names the page, the selector and the text', async () => {
    const url = await serve({
      relabel: { '.cart-backdrop{border-radius:0': '.cart-backdrop{border-radius:999px' },
    });
    const result = await pageLintVerifier({ target: { url }, dataDir: FIXTURE_DIR }).run(
      await ctx('gen_cart_search'),
    );
    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain('`page_lint`: 1 problem(s) on 1 of 3 page(s)');
    expect(result.feedback).toContain(
      '`cartDrawer` (`/products/shopliseum-mushroom-dog-toys?cart=open`)',
    );
    expect(result.feedback).toContain('To fix:');
    expect(result.feedback).toContain(
      'drawer_backdrop at desktop, mobile: `main > div.cart-popup > button.cart-backdrop` "Close cart drawer"',
    );
  }, 120_000);

  it('fails a bare control on a page of the task', async () => {
    const url = await serve({
      relabel: { '<h1>Cart</h1>': '<h1>Cart</h1><button style="all:revert">Note</button>' },
    });
    const verifier = pageLintVerifier({ target: { url }, dataDir: FIXTURE_DIR });
    const result = await verifier.run(await ctx('gen_cart_search'));
    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain('`cart` (`/cart`)');
    expect(result.feedback).toContain(
      'unstyled_control at desktop, mobile: `main > button` "Note"',
    );
  }, 120_000);
});
