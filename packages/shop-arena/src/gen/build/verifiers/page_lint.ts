/**
 * `page_lint` verifier: deterministic checks (no model) on the canonical
 * pages of a task's buckets and on the open cart drawer, at the desktop and
 * mobile judge viewports. The final eval runs the same checks on the same
 * page list (`lintShopPages`), so a shop that passes them in the build loop
 * also passes them in the final eval.
 *
 * The rules:
 *
 * - `unstyled_control`: a visible `button`, `input` (text, number, email,
 *   password, search, checkbox, radio), `select` or `textarea` still has the
 *   browser default look of its element type. The baseline is the computed
 *   style of the same bare element in an empty page of the same browser. A
 *   box control (all but checkbox and radio) keeps the default look when its
 *   background (color and image) and its border (style, width and color)
 *   all equal the baseline: that is the grey bevelled button or the inset
 *   text box, whatever its radius, padding or font. A checkbox or radio
 *   keeps the default look when its `appearance` and `accent-color` both
 *   equal the baseline. A control is visible when it and its ancestors show
 *   it (not `display: none`, `visibility: hidden` or `opacity: 0`), its box
 *   is at least 2x2 px and it is not off-screen to the left, right or top.
 * - `placeholder_title`: the visible text has the placeholder variant title
 *   "Default Title".
 * - `drawer_closed`, `drawer_backdrop`, `drawer_image` (the open cart drawer
 *   only): the drawer is open; its backdrop (`.cart-backdrop`) covers the
 *   whole viewport and has square corners; no visible image in the drawer is
 *   wider than the drawer's content box. In the drawer, the first two rules
 *   check only what is inside the drawer.
 */

import { BrowserSession } from '@shop-gym/browser';
import type { Verifier, VerifierContext, VerifierResult } from '@shop-gym/harness';

import { JUDGE_VIEWPORTS, type ViewportName } from './page_judge.js';
import {
  CART_DRAWER_SELECTOR,
  type CanonicalPage,
  type SkippedPage,
  walkShopPages,
} from './shop_pages.js';
import { type StorefrontTarget, prepareTarget } from './storefront_target.js';
import {
  type DatasetHandles,
  type PageBucket,
  bucketsForTask,
  readDatasetHandles,
} from './task_routes.js';

export const PAGE_LINT_NAME = 'page_lint';
/** The placeholder title of a product's only variant. */
export const PLACEHOLDER_VARIANT_TITLE = 'Default Title';
/** The backdrop that the storefront renders behind its open cart drawer. */
export const CART_BACKDROP_SELECTOR = '.cart-backdrop';
/** The `input` types that the `unstyled_control` rule checks. */
export const CHECKED_INPUT_TYPES: readonly string[] = [
  'text',
  'number',
  'email',
  'password',
  'search',
  'checkbox',
  'radio',
];
const TOGGLE_INPUT_TYPES: readonly string[] = ['checkbox', 'radio'];
const BOX_PROPERTIES = [
  'background-color',
  'background-image',
  'border-style',
  'border-width',
  'border-color',
] as const;
const TOGGLE_PROPERTIES = ['appearance', 'accent-color'] as const;
const SAMPLED_PROPERTIES: readonly string[] = [...BOX_PROPERTIES, ...TOGGLE_PROPERTIES];
/** One bare element per baseline key, in a standards-mode page with no styles. */
const BARE_CONTROLS_HTML = `<!doctype html><html><head></head><body>
<button>Button</button>
${CHECKED_INPUT_TYPES.map((type) => `<input type="${type}">`).join('\n')}
<select><option>Option</option></select>
<select multiple><option>Option</option></select>
<textarea></textarea>
</body></html>`;
/** Pixels a box may miss the viewport edge by and still cover it. */
const COVER_TOLERANCE_PX = 0.5;
const NAVIGATION_TIMEOUT_MS = 30_000;
const SETTLE_MS = 300;

type Page = BrowserSession['page'];
type BrowserContext = ReturnType<Page['context']>;
type StyleSample = Readonly<Record<string, string>>;

/** `page` checks the whole page; `cartDrawer` checks the open cart drawer over it. */
export type LintScope = 'page' | 'cartDrawer';

export type LintRule =
  | 'unstyled_control'
  | 'placeholder_title'
  | 'drawer_closed'
  | 'drawer_backdrop'
  | 'drawer_image';

export interface LintFinding {
  readonly rule: LintRule;
  /** A short CSS path to the element; empty when there is no element. */
  readonly selector: string;
  /** The element's text, label or alt text, cut to 80 characters. */
  readonly text: string;
  readonly detail: string;
}

/** Check the page as it is now loaded in `page`. */
export async function lintLoadedPage(page: Page, scope: LintScope): Promise<LintFinding[]> {
  const baseline = await bareControlStyles(page.context());
  const sample = await page.evaluate(samplePage, {
    drawerSelector: scope === 'cartDrawer' ? CART_DRAWER_SELECTOR : null,
    backdropSelector: CART_BACKDROP_SELECTOR,
    inputTypes: CHECKED_INPUT_TYPES,
    properties: SAMPLED_PROPERTIES,
    placeholder: PLACEHOLDER_VARIANT_TITLE,
  });
  if (sample.drawer === null) {
    return [
      {
        rule: 'drawer_closed',
        selector: CART_DRAWER_SELECTOR,
        text: '',
        detail: `the cart drawer \`${CART_DRAWER_SELECTOR}\` is not open on this route`,
      },
    ];
  }
  return [
    ...sample.controls.flatMap((control) => unstyledFinding(control, baseline)),
    ...sample.placeholders.map(
      (element): LintFinding => ({
        rule: 'placeholder_title',
        ...element,
        detail: `shows the placeholder variant title "${PLACEHOLDER_VARIANT_TITLE}"; hide the variant title when it is "${PLACEHOLDER_VARIANT_TITLE}"`,
      }),
    ),
    ...(sample.drawer === undefined ? [] : drawerFindings(sample.drawer)),
  ];
}

export interface PageLintIssue extends LintFinding {
  /** The viewports that showed the problem. */
  readonly viewports: readonly ViewportName[];
}

export interface LintedPage extends CanonicalPage {
  readonly status: 'pass' | 'fail';
  readonly issues: readonly PageLintIssue[];
}

export type PageLintResult = LintedPage | SkippedPage;

export interface LintShopPagesOptions {
  readonly session: BrowserSession;
  readonly baseUrl: string;
  readonly dataDir: string;
  readonly handles: DatasetHandles;
  /** Check only the pages of these buckets; every canonical page when omitted. */
  readonly buckets?: readonly PageBucket[];
  readonly signal?: AbortSignal;
  readonly log?: (line: string) => void;
}

/** Walk the canonical pages and check each one at every judge viewport. */
export async function lintShopPages(options: LintShopPagesOptions): Promise<PageLintResult[]> {
  const results: PageLintResult[] = [];
  const skipped = await walkShopPages({
    session: options.session,
    baseUrl: options.baseUrl,
    dataDir: options.dataDir,
    handles: options.handles,
    ...(options.buckets === undefined ? {} : { buckets: options.buckets }),
    orderEmail: 'page.lint@example.com',
    visit: async (page) => {
      options.signal?.throwIfAborted();
      const result = await lintPage(options.session.page, options.baseUrl, page);
      options.log?.(`page_lint: ${page.name} ${result.status}`);
      results.push(result);
    },
  });
  return [...results, ...skipped];
}

export interface PageLintOptions {
  readonly target: StorefrontTarget;
  readonly dataDir: string;
}

export function pageLintVerifier(options: PageLintOptions): Verifier {
  return {
    name: PAGE_LINT_NAME,
    appliesTo: (taskId) => bucketsForTask(taskId).length > 0,
    async run(ctx: VerifierContext): Promise<VerifierResult> {
      const blocked = await prepareTarget(options.target);
      if (blocked !== undefined) {
        return blocked;
      }
      const buckets = bucketsForTask(ctx.selectedTaskId);
      const handles = await readDatasetHandles(options.dataDir);
      const session = await BrowserSession.launch({ episodeId: `page-lint-${ctx.iterId}` });
      let pages: PageLintResult[];
      try {
        pages = await lintShopPages({
          session,
          baseUrl: options.target.url,
          dataDir: options.dataDir,
          handles,
          buckets,
        });
      } finally {
        await session.close();
      }
      const details = { buckets, pages };
      const failed = pages.filter((page): page is LintedPage => page.status === 'fail');
      if (failed.length === 0) {
        return { verdict: 'pass', details };
      }
      return {
        verdict: 'fail',
        feedback: renderLintFeedback(ctx.selectedTaskId, pages),
        details,
      };
    },
  };
}

/** Feedback for the executor: each problem with its page, viewports, element and fix. */
export function renderLintFeedback(taskId: string, pages: readonly PageLintResult[]): string {
  const failed = pages.filter((page): page is LintedPage => page.status === 'fail');
  const problems = failed.reduce((sum, page) => sum + page.issues.length, 0);
  const rules = new Set(failed.flatMap((page) => page.issues.map((issue) => issue.rule)));
  const lines = [
    `\`${PAGE_LINT_NAME}\`: ${problems} problem(s) on ${failed.length} of ${pages.length} page(s) for \`${taskId}\`.`,
  ];
  for (const page of failed) {
    lines.push('', `### \`${page.name}\` (\`${page.route}\`)`, '');
    for (const issue of page.issues) {
      const element = issue.selector === '' ? '' : ` \`${issue.selector}\``;
      const text = issue.text === '' ? '' : ` "${issue.text}"`;
      lines.push(
        `- ${issue.rule} at ${issue.viewports.join(', ')}:${element}${text}: ${issue.detail}`,
      );
    }
  }
  lines.push('', 'To fix:', ...[...rules].map((rule) => `- ${RULE_HINTS[rule]}`));
  return lines.join('\n');
}

const RULE_HINTS: Readonly<Record<LintRule, string>> = {
  unstyled_control:
    'Give every visible control shop styles: a background and a border from the theme tokens (for a checkbox or radio, `accent-color` or a drawn box).',
  placeholder_title: `Hide a variant title of "${PLACEHOLDER_VARIANT_TITLE}" in the product, cart and drawer lines.`,
  drawer_closed: `Keep the cart drawer: \`?cart=open\` opens \`${CART_DRAWER_SELECTOR}\`.`,
  drawer_backdrop: `Keep \`${CART_BACKDROP_SELECTOR}\` a full-viewport layer with square corners. Element selectors such as \`button\` must not change it; scope look changes with classes.`,
  drawer_image: 'Size drawer images to the drawer line, not to the drawer width.',
};

/** Load `page.route` at every judge viewport and merge the findings by viewport. */
async function lintPage(
  page: Page,
  baseUrl: string,
  shopPage: CanonicalPage,
): Promise<PageLintResult> {
  const scope: LintScope = shopPage.name === 'cartDrawer' ? 'cartDrawer' : 'page';
  const issues = new Map<string, { finding: LintFinding; viewports: ViewportName[] }>();
  for (const viewport of JUDGE_VIEWPORTS) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    try {
      await page.goto(`${baseUrl}${shopPage.route}`, {
        waitUntil: 'load',
        timeout: NAVIGATION_TIMEOUT_MS,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { ...shopPage, status: 'skipped', reason: `the page did not load: ${message}` };
    }
    await page.waitForTimeout(SETTLE_MS);
    for (const finding of await lintLoadedPage(page, scope)) {
      const key = JSON.stringify([finding.rule, finding.selector, finding.text]);
      const entry = issues.get(key);
      if (entry === undefined) {
        issues.set(key, { finding, viewports: [viewport.name] });
      } else {
        entry.viewports.push(viewport.name);
      }
    }
  }
  const merged = [...issues.values()].map(({ finding, viewports }) => ({ ...finding, viewports }));
  return { ...shopPage, status: merged.length === 0 ? 'pass' : 'fail', issues: merged };
}

const baselines = new WeakMap<BrowserContext, Promise<ReadonlyMap<string, StyleSample>>>();

/** Computed styles of the bare controls, by control key; read once per browser context. */
function bareControlStyles(context: BrowserContext): Promise<ReadonlyMap<string, StyleSample>> {
  let baseline = baselines.get(context);
  if (baseline === undefined) {
    baseline = readBareControlStyles(context);
    baselines.set(context, baseline);
  }
  return baseline;
}

async function readBareControlStyles(
  context: BrowserContext,
): Promise<ReadonlyMap<string, StyleSample>> {
  const page = await context.newPage();
  try {
    await page.setContent(BARE_CONTROLS_HTML);
    const sample = await page.evaluate(samplePage, {
      drawerSelector: null,
      backdropSelector: CART_BACKDROP_SELECTOR,
      inputTypes: CHECKED_INPUT_TYPES,
      properties: SAMPLED_PROPERTIES,
      placeholder: PLACEHOLDER_VARIANT_TITLE,
    });
    return new Map(sample.controls.map((control) => [control.key, control.style]));
  } finally {
    await page.close();
  }
}

function unstyledFinding(
  control: ControlSample,
  baseline: ReadonlyMap<string, StyleSample>,
): LintFinding[] {
  const bare = baseline.get(control.key);
  if (bare === undefined) {
    return [];
  }
  const toggle = TOGGLE_INPUT_TYPES.includes(control.key.replace(/^input:/, ''));
  const properties: readonly string[] = toggle ? TOGGLE_PROPERTIES : BOX_PROPERTIES;
  if (properties.some((property) => control.style[property] !== bare[property])) {
    return [];
  }
  const element = controlElement(control.key);
  const look = properties.map((property) => `${property} ${control.style[property]}`).join('; ');
  return [
    {
      rule: 'unstyled_control',
      selector: control.selector,
      text: control.text,
      detail: `keeps the browser default look of a bare \`${element}\` (${look})`,
    },
  ];
}

/** `input:checkbox` -> `input[type="checkbox"]`, `select:select-one` -> `select`. */
function controlElement(key: string): string {
  const [tag = key, type] = key.split(':');
  if (tag === 'input' && type !== undefined) return `input[type="${type}"]`;
  if (type === 'select-multiple') return 'select[multiple]';
  return tag;
}

function drawerFindings(drawer: DrawerSample): LintFinding[] {
  const findings: LintFinding[] = [];
  const { backdrop, viewport } = drawer;
  if (backdrop === null) {
    findings.push({
      rule: 'drawer_backdrop',
      selector: '',
      text: '',
      detail: `no \`${CART_BACKDROP_SELECTOR}\` behind the open cart drawer`,
    });
  } else {
    const covers =
      backdrop.left <= COVER_TOLERANCE_PX &&
      backdrop.top <= COVER_TOLERANCE_PX &&
      backdrop.right >= viewport.width - COVER_TOLERANCE_PX &&
      backdrop.bottom >= viewport.height - COVER_TOLERANCE_PX;
    if (!covers) {
      const box = `${round(backdrop.left)},${round(backdrop.top)} to ${round(backdrop.right)},${round(backdrop.bottom)}`;
      findings.push({
        rule: 'drawer_backdrop',
        selector: backdrop.selector,
        text: backdrop.text,
        detail: `the backdrop spans ${box} and does not cover the whole viewport (${viewport.width}x${viewport.height})`,
      });
    }
    if (backdrop.radii.some((radius) => Number.parseFloat(radius) !== 0)) {
      findings.push({
        rule: 'drawer_backdrop',
        selector: backdrop.selector,
        text: backdrop.text,
        detail: `the backdrop has rounded corners (${backdrop.radii.join(' ')}); it must have square corners`,
      });
    }
  }
  for (const image of drawer.images) {
    if (image.width > drawer.contentWidth + COVER_TOLERANCE_PX) {
      findings.push({
        rule: 'drawer_image',
        selector: image.selector,
        text: image.text,
        detail: `the image is ${round(image.width)}px wide, wider than the ${round(drawer.contentWidth)}px content box of the drawer`,
      });
    }
  }
  return findings;
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}

/** What `samplePage` reads about one visible control. */
interface ControlSample {
  /** `button`, `textarea`, `input:<type>` or `select:<type>`. */
  readonly key: string;
  readonly selector: string;
  readonly text: string;
  readonly style: StyleSample;
}

interface ElementSample {
  readonly selector: string;
  readonly text: string;
}

interface DrawerSample {
  /** The viewport without scrollbars. */
  readonly viewport: { readonly width: number; readonly height: number };
  /** The drawer's width without its padding. */
  readonly contentWidth: number;
  /** `null` when the page has no visible backdrop element. */
  readonly backdrop:
    | (ElementSample & {
        readonly left: number;
        readonly top: number;
        readonly right: number;
        readonly bottom: number;
        readonly radii: readonly string[];
      })
    | null;
  readonly images: readonly (ElementSample & { readonly width: number })[];
}

interface PageSample {
  readonly controls: readonly ControlSample[];
  readonly placeholders: readonly ElementSample[];
  /** Read for the drawer scope only; `null` when the drawer is not open. */
  readonly drawer?: DrawerSample | null;
}

interface SampleArgs {
  /** The open drawer to check inside; `null` checks the whole page. */
  readonly drawerSelector: string | null;
  readonly backdropSelector: string;
  readonly inputTypes: readonly string[];
  readonly properties: readonly string[];
  readonly placeholder: string;
}

/** The few DOM members `samplePage` uses (the package compiles without the DOM lib). */
interface DomRect {
  readonly left: number;
  readonly top: number;
  readonly right: number;
  readonly bottom: number;
  readonly width: number;
  readonly height: number;
}

interface DomElement {
  readonly tagName: string;
  readonly id: string;
  readonly type?: string;
  readonly classList: Iterable<string>;
  readonly parentElement: DomElement | null;
  readonly innerText: string;
  readonly clientWidth: number;
  readonly clientHeight: number;
  readonly labels?: ArrayLike<DomElement> | null;
  getAttribute(name: string): string | null;
  getBoundingClientRect(): DomRect;
  checkVisibility(options: { opacityProperty: boolean; visibilityProperty: boolean }): boolean;
  querySelectorAll(selector: string): Iterable<DomElement>;
}

interface DomWindow {
  readonly document: {
    readonly body: DomElement;
    readonly documentElement: DomElement;
    querySelector(selector: string): DomElement | null;
    createTreeWalker(
      root: DomElement,
      whatToShow: number,
    ): { nextNode(): { readonly data: string; readonly parentElement: DomElement | null } | null };
  };
  readonly innerWidth: number;
  readonly scrollY: number;
  readonly CSS: { escape(value: string): string };
  getComputedStyle(element: DomElement): { getPropertyValue(name: string): string };
}

/**
 * Runs in the browser: read the visible controls, the visible placeholder
 * titles and, for the drawer scope, the drawer's backdrop and images. It is
 * serialized into the page, so it uses nothing outside its own body.
 */
function samplePage(args: SampleArgs): PageSample {
  const win = globalThis as unknown as DomWindow;
  const doc = win.document;
  const clean = (text: string): string => text.replace(/\s+/g, ' ').trim().slice(0, 80);
  const visible = (element: DomElement): boolean => {
    if (!element.checkVisibility({ opacityProperty: true, visibilityProperty: true })) {
      return false;
    }
    const rect = element.getBoundingClientRect();
    return (
      rect.width >= 2 &&
      rect.height >= 2 &&
      rect.right > 0 &&
      rect.left < win.innerWidth &&
      rect.bottom + win.scrollY > 0
    );
  };
  const cssPath = (element: DomElement): string => {
    const parts: string[] = [];
    let node: DomElement | null = element;
    while (node !== null && parts.length < 3 && node.tagName !== 'BODY') {
      if (node.id !== '') {
        parts.unshift(`#${win.CSS.escape(node.id)}`);
        break;
      }
      const classes = [...node.classList]
        .slice(0, 2)
        .map((name) => `.${win.CSS.escape(name)}`)
        .join('');
      parts.unshift(`${node.tagName.toLowerCase()}${classes}`);
      node = node.parentElement;
    }
    return parts.join(' > ');
  };
  const textOf = (element: DomElement): string => {
    if (element.tagName === 'BUTTON') {
      return clean(element.innerText || (element.getAttribute('aria-label') ?? ''));
    }
    const label = element.labels?.[0];
    return clean(
      element.getAttribute('aria-label') ??
        (label === undefined ? null : label.innerText) ??
        element.getAttribute('placeholder') ??
        element.getAttribute('name') ??
        '',
    );
  };

  let root = doc.body;
  let drawer: DrawerSample | null | undefined;
  if (args.drawerSelector !== null) {
    const open = doc.querySelector(args.drawerSelector);
    if (open === null || !visible(open)) {
      return { controls: [], placeholders: [], drawer: null };
    }
    root = open;
    const backdrop = doc.querySelector(args.backdropSelector);
    const rect = backdrop?.getBoundingClientRect();
    const drawerStyle = win.getComputedStyle(open);
    drawer = {
      viewport: {
        width: doc.documentElement.clientWidth,
        height: doc.documentElement.clientHeight,
      },
      contentWidth:
        open.clientWidth -
        Number.parseFloat(drawerStyle.getPropertyValue('padding-left')) -
        Number.parseFloat(drawerStyle.getPropertyValue('padding-right')),
      backdrop:
        backdrop === null || rect === undefined
          ? null
          : {
              selector: cssPath(backdrop),
              text: textOf(backdrop),
              left: rect.left,
              top: rect.top,
              right: rect.right,
              bottom: rect.bottom,
              radii: ['top-left', 'top-right', 'bottom-right', 'bottom-left'].map((corner) =>
                win.getComputedStyle(backdrop).getPropertyValue(`border-${corner}-radius`),
              ),
            },
      images: [...open.querySelectorAll('img')].filter(visible).map((image) => ({
        selector: cssPath(image),
        text: clean(image.getAttribute('alt') ?? ''),
        width: image.getBoundingClientRect().width,
      })),
    };
  }

  const controls: ControlSample[] = [];
  for (const element of root.querySelectorAll('button, input, select, textarea')) {
    const tag = element.tagName.toLowerCase();
    const type = element.type ?? '';
    if (tag === 'input' && !args.inputTypes.includes(type)) continue;
    if (!visible(element)) continue;
    const style = win.getComputedStyle(element);
    controls.push({
      key: tag === 'input' || tag === 'select' ? `${tag}:${type}` : tag,
      selector: cssPath(element),
      text: textOf(element),
      style: Object.fromEntries(
        args.properties.map((property) => [property, style.getPropertyValue(property)]),
      ),
    });
  }

  const placeholders: ElementSample[] = [];
  const SHOW_TEXT = 4;
  const walker = doc.createTreeWalker(root, SHOW_TEXT);
  for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
    const parent = node.parentElement;
    if (node.data.includes(args.placeholder) && parent !== null && visible(parent)) {
      placeholders.push({ selector: cssPath(parent), text: clean(parent.innerText) });
    }
  }
  return drawer === undefined ? { controls, placeholders } : { controls, placeholders, drawer };
}
