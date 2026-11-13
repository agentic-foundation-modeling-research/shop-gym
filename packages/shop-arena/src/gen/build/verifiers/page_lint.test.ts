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
  CHECKED_INPUT_TYPES,
  type LintScope,
  type PageLintResult,
  lintLoadedPage,
  pageLintVerifier,
} from './page_lint.js';

const FIXTURE_DIR = path.join(defaultBackendTemplateDir(), 'tests', 'fixtures', 'sandbox_shop_v0');

/** Shop styles for every checked element type. */
const SHOP_STYLES = `<style>
button,input,select,textarea{background:#fff;border:1px solid #223344;border-radius:4px}
input[type=checkbox],input[type=radio],input[type=range]{appearance:none;width:16px;height:16px}
input[type=file]::file-selector-button{background:#fff;border:1px solid #223344}
summary{list-style:none}
a{color:#223344}
</style>`;

/**
 * Shop buttons whose padding keeps a 32x34 px box, and three screen-reader
 * classes of 1 px with overflow hidden: `visually-hidden` clips with
 * `clip`, `sr-clip-path` with `clip-path` and `sr-no-clip` not at all.
 */
const SORT_STYLES = `<style>
button{box-sizing:border-box;min-height:36px;padding:0 16px;background:#fff;border:1px solid #223344;font-size:14px}
.visually-hidden,.sr-clip-path,.sr-no-clip{position:absolute;width:1px;height:1px;overflow:hidden;white-space:nowrap}
.visually-hidden{clip:rect(0,0,0,0)}
.sr-clip-path{clip-path:inset(50%)}
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

  it('fails a native checkbox and radio that only set an accent color', async () => {
    const findings = await lint(`<style>
      input[type="checkbox"],input[type="radio"]{accent-color:#007185}
      .cart-gift input{width:16px;height:16px}
    </style><div class="cart-gift"><label><input type="checkbox"> This is a gift</label></div>
    <label><input type="radio" name="ship" checked> Standard</label>`);
    expect(findings.map((finding) => [finding.rule, finding.text, finding.detail])).toEqual([
      ['unstyled_control', 'This is a gift', expect.stringContaining('appearance auto')],
      ['unstyled_control', 'Standard', expect.stringContaining('`input[type="radio"]`')],
    ]);
  });

  it('passes a checkbox drawn with appearance none, a shop border, background and check mark', async () => {
    const findings = await lint(`<style>
      .gift-check{appearance:none;width:16px;height:16px;margin:0;border:1px solid #223344;border-radius:3px;background:#fff;display:inline-grid;place-content:center}
      .gift-check:checked{background:#223344}
      .gift-check:checked::before{content:"";width:4px;height:8px;border:solid #fff;border-width:0 2px 2px 0;transform:rotate(45deg)}
    </style><label><input class="gift-check" type="checkbox"> This is a gift</label>
    <label><input class="gift-check" type="checkbox" checked> Gift wrap</label>`);
    expect(findings).toEqual([]);
  });

  it('passes a visually hidden native input with a shop-drawn box on its label', async () => {
    const findings = await lint(`<style>
      .sr-only{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0)}
      .box{display:inline-block;width:16px;height:16px;border:1px solid #223344;background:#fff}
    </style><label><input class="sr-only" type="checkbox"><span class="box"></span> Verified Buyers only</label>
    <label><input type="radio" name="size" style="position:absolute;opacity:0"><span class="box"></span> Small</label>`);
    expect(findings).toEqual([]);
  });

  it('ignores a visually hidden button whose label is wider than its box', async () => {
    const findings = await lint(`${SORT_STYLES}<form class="collection-sort">
      <button class="visually-hidden" type="submit">Sort</button>
      <button class="sr-clip-path" type="submit">Sort</button>
      <span class="visually-hidden"><button type="submit" style="width:1px;overflow:hidden">Sort</button></span>
      <button class="sr-no-clip" type="submit" style="clip:rect(1px 1px 1px 1px)">Sort</button>
    </form>`);
    expect(findings).toEqual([]);
  });

  it('ignores a visually hidden native checkbox', async () => {
    const findings = await lint(`<style>
      .sr-clip-path{position:absolute;clip-path:inset(50%)}
      .visually-hidden{position:absolute;width:16px;height:16px;clip:rect(0 0 0 0)}
      .box{display:inline-block;width:16px;height:16px;border:1px solid #223344;background:#fff}
    </style><label><input class="sr-clip-path" type="checkbox"><span class="box"></span> Prime only</label>
    <label><input class="visually-hidden" type="checkbox"><span class="box"></span> In stock</label>`);
    expect(findings).toEqual([]);
  });

  it('still fails the same button when no clip empties its painted area', async () => {
    const findings = await lint(`${SORT_STYLES}<form class="collection-sort">
      <button class="sr-no-clip" type="submit">Sort</button>
      <button class="sr-no-clip" type="submit" style="clip:rect(0 auto auto 0)">Sort</button>
      <button class="sr-no-clip" type="submit" style="position:static;clip:rect(0 0 0 0)">Sort</button>
      <button class="sr-no-clip" type="submit" style="clip-path:inset(10%)">Sort</button>
      <span class="sr-no-clip"><button type="submit" style="width:1px;overflow:hidden">Sort</button></span>
    </form>`);
    expect(findings.map((finding) => [finding.rule, finding.text, finding.detail])).toEqual(
      Array.from({ length: 5 }, () => [
        'clipped_label',
        'Sort',
        expect.stringMatching(/needs \d+x\d+ px but the box shows 32x34 px/),
      ]),
    );
  });

  it('fails a bare number input against its own baseline', async () => {
    const findings = await lint(
      '<form class="qty"><label>Qty <input type="number" name="quantity" value="1"></label></form>',
    );
    expect(findings).toEqual([
      {
        rule: 'unstyled_control',
        selector: 'form.qty > label > input',
        text: 'Qty',
        detail: expect.stringContaining('browser default look of a bare `input[type="number"]`'),
      },
    ]);
  });

  it('fails every bare control type, each against its own baseline', async () => {
    const findings = await lint(`<form>
      ${CHECKED_INPUT_TYPES.map((type) => `<input type="${type}" name="${type}">`).join('')}
      <select name="sort"><option>Newest</option></select><textarea name="note"></textarea>
    </form>`);
    expect(findings.map((finding) => [finding.rule, finding.text])).toEqual(
      [...CHECKED_INPUT_TYPES, 'sort', 'note'].map((name) => ['unstyled_control', name]),
    );
    expect(findings.find((finding) => finding.text === 'file')?.detail).toContain(
      '`input[type="file"]::file-selector-button`',
    );
  });

  it('passes styled elements of every checked type', async () => {
    const findings = await lint(`${SHOP_STYLES}<form>
      <button>Buy</button>
      ${CHECKED_INPUT_TYPES.map((type) => `<input type="${type}" name="${type}">`).join('')}
      <select name="sort"><option>Newest</option></select><textarea name="note"></textarea>
    </form><details><summary>Shipping</summary></details><a href="/cart">Cart</a>`);
    expect(findings).toEqual([]);
  });

  it('passes a file input whose button has shop styles', async () => {
    const findings = await lint(
      '<input type="file" name="receipt" style="border:0" class="upload"><style>.upload::file-selector-button{background:#223344;color:#fff;border:0;border-radius:4px}</style>',
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
      <details><summary style="list-style:none">More</summary><input type="text" name="closed"></details>
      <input type="hidden" name="intent" value="add">
    </main>`);
    expect(findings).toEqual([]);
  });

  it('fails a summary that shows the browser disclosure marker', async () => {
    const findings = await lint(`<style>
      .product-info-accordion summary{cursor:pointer;background:#f2f3f3;padding:.8rem 1rem;font-weight:700}
      .webkit-only summary::-webkit-details-marker{display:none}
    </style><details class="product-info-accordion"><summary>Product description</summary><p>Text</p></details>
    <details class="product-info-accordion" open><summary>Shipping &amp; returns</summary><p>Text</p></details>
    <details class="webkit-only"><summary>See 12 more</summary></details>`);
    expect(findings).toEqual([
      {
        rule: 'unstyled_summary',
        selector: 'details.product-info-accordion > summary',
        text: 'Product description',
        detail: expect.stringContaining('list-style-type disclosure-closed'),
      },
      {
        rule: 'unstyled_summary',
        selector: 'details.product-info-accordion > summary',
        text: 'Shipping & returns',
        detail: expect.stringContaining('list-style-type disclosure-open'),
      },
      {
        rule: 'unstyled_summary',
        selector: 'details.webkit-only > summary',
        text: 'See 12 more',
        detail: expect.stringContaining('browser disclosure marker'),
      },
    ]);
  });

  it('passes a summary with a shop marker', async () => {
    const findings = await lint(`<style>
      .facet-more summary{list-style:none;cursor:pointer}
      .facet-more summary::after{content:"+";margin-left:.5rem}
      .faq summary::marker{content:"\\203A  "}
      .flex summary{display:flex;justify-content:space-between}
    </style><details class="facet-more"><summary>See 12 more</summary></details>
    <details class="faq"><summary>Returns</summary></details>
    <details class="flex"><summary>Delivery <span>+</span></summary></details>`);
    expect(findings).toEqual([]);
  });

  it('fails a link in the default link blue and passes links in shop colors', async () => {
    const findings = await lint(`<style>.brand{color:#111}.footer a{color:inherit}</style>
      <nav class="keep"><a href="/collections/all">Shop all departments</a></nav>
      <a class="brand" href="/">Shopliseum</a>
      <p class="footer"><a href="/policies/privacy">Privacy</a></p>
      <a href="/products/oak-bowl"><img alt="" style="width:40px;height:40px"></a>
      <a>Not a link</a>`);
    expect(findings).toEqual([
      {
        rule: 'unstyled_link',
        selector: 'nav.keep > a',
        text: 'Shop all departments',
        detail: expect.stringContaining('rgb(0, 0, 238)'),
      },
    ]);
  });

  it('fails a clipped "Delete" pill and passes a label that fits', async () => {
    const findings = await lint(`<style>
      .cart-inline-actions button{box-sizing:border-box;height:29px;border-radius:16px;padding:0 .7rem;border:1px solid #d5d9d9;background:#fff;white-space:nowrap;overflow:hidden;font-size:14px}
      .cart-delete{width:44px}
    </style><div class="cart-inline-actions">
      <button class="cart-delete" type="submit">Delete</button>
      <button class="cart-update" type="submit">Update</button>
      <a class="button-link" href="/checkout" style="display:inline-block;width:40px;overflow:hidden;white-space:nowrap;color:#111">Continue to checkout</a>
    </div>`);
    expect(findings).toEqual([
      {
        rule: 'clipped_label',
        selector: 'div.cart-inline-actions > button.cart-delete',
        text: 'Delete',
        detail: expect.stringMatching(/needs \d+x\d+ px but the box shows 42x27 px/),
      },
      {
        rule: 'clipped_label',
        selector: 'div.cart-inline-actions > a.button-link',
        text: 'Continue to checkout',
        detail: expect.stringContaining('overflow hidden'),
      },
    ]);
  });

  it('passes a label that overflows visibly, an icon-only button and an ellipsis on purpose', async () => {
    const findings = await lint(`<style>
      button{background:#fff;border:1px solid #223344}
      .tight{width:30px;white-space:nowrap}
      .icon{width:24px;height:24px;padding:0;overflow:hidden}
      .ellipsis{display:inline-block;width:60px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
    </style><button class="tight">Delete</button>
    <button class="icon" aria-label="Close"><svg width="40" height="40"><rect width="40" height="40"></rect></svg></button>
    <button class="ellipsis">Nintendo Switch Lite</button>`);
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
