/**
 * `page_lint` verifier: deterministic checks (no model) on the canonical
 * pages of a task's buckets and on the open cart drawer, at the desktop and
 * mobile judge viewports. The final eval runs the same checks on the same
 * page list (`lintShopPages`), so a shop that passes them in the build loop
 * also passes them in the final eval.
 *
 * The rules:
 *
 * - `unstyled_control`: a visible `button`, `input` (every type in
 *   `CHECKED_INPUT_TYPES`), `select` or `textarea` still has the browser
 *   default look of its element type. The baseline is the computed style of
 *   the same bare element in an empty page of the same browser. A box
 *   control keeps the default look when its background (color and image)
 *   and its border (style, width and color) all equal the baseline: that is
 *   the grey bevelled button or the inset text box, whatever its radius,
 *   padding or font. For a file input the box is its
 *   `::file-selector-button`. A checkbox, radio or range input is a native
 *   widget that the browser draws whatever its background, border or
 *   `accent-color` (which only tints it): it keeps the default look while
 *   its computed `appearance` is not `none`.
 * - `unstyled_summary`: a visible `summary` still shows the browser
 *   disclosure marker: its `display`, `list-style-type`,
 *   `list-style-image` and `::marker` content all equal those of a bare
 *   `summary` in the same open or closed state. `list-style: none`, a
 *   non-list-item `display` or a `::marker` content of the shop's own
 *   removes it; `::-webkit-details-marker` does not exist in Chromium.
 * - `unstyled_link`: a visible `a[href]` with text keeps the color of a
 *   bare link (the default blue). A link without text, such as an image
 *   link, shows no link color and does not count.
 * - `clipped_label`: a visible button (a `button`, a `submit`, `reset` or
 *   `button` input, an element with `role="button"`, or a link with a class
 *   name that has "button" or "btn") hides part of its label: its content
 *   (scroll size) is more than 1 px wider or taller than its padding box
 *   (client size) and its `overflow` on that axis is not `visible`. A
 *   button without text (an icon button) does not count, and a label that
 *   the shop cuts on purpose with `text-overflow: ellipsis` passes on the
 *   horizontal axis. A label that spills visibly out of its box is not cut.
 * - `placeholder_title`: the visible text has the placeholder variant title
 *   "Default Title".
 * - `drawer_closed`, `drawer_backdrop`, `drawer_image` (the open cart drawer
 *   only): the drawer is open; its backdrop (`.cart-backdrop`) covers the
 *   whole viewport and has square corners; no visible image in the drawer is
 *   wider than the drawer's content box. In the drawer, the first two rules
 *   check only what is inside the drawer.
 *
 * An element is visible when it and its ancestors show it (not
 * `display: none`, `visibility: hidden` or `opacity: 0`), its box is at
 * least 2x2 px and it is not off-screen to the left, right or top. So a
 * visually hidden native input behind a shop-drawn box does not count.
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
/** The `input` types that the `unstyled_control` rule checks: all but `hidden` and `image`. */
export const CHECKED_INPUT_TYPES: readonly string[] = [
  'text',
  'search',
  'email',
  'password',
  'number',
  'tel',
  'url',
  'date',
  'time',
  'datetime-local',
  'month',
  'week',
  'color',
  'file',
  'submit',
  'reset',
  'button',
  'checkbox',
  'radio',
  'range',
];
/** The `input` types that the browser draws as a native widget until `appearance: none`. */
const NATIVE_INPUT_TYPES: readonly string[] = ['checkbox', 'radio', 'range'];
/** The `input` types that show as a button, which the `clipped_label` rule checks. */
const BUTTON_INPUT_TYPES: readonly string[] = ['submit', 'reset', 'button'];
const BOX_PROPERTIES: readonly string[] = [
  'background-color',
  'background-image',
  'border-style',
  'border-width',
  'border-color',
];
/** `samplePage` reads `::marker content` from the `::marker` pseudo element. */
const SUMMARY_PROPERTIES: readonly string[] = [
  'display',
  'list-style-type',
  'list-style-image',
  '::marker content',
];
const LINK_PROPERTIES: readonly string[] = ['color'];
const SAMPLED_PROPERTIES: readonly string[] = [
  ...BOX_PROPERTIES,
  'appearance',
  ...LINK_PROPERTIES,
  ...SUMMARY_PROPERTIES.filter((property) => !property.startsWith('::')),
];
/** One bare element per baseline key, in a standards-mode page with no styles. */
const BARE_CONTROLS_HTML = `<!doctype html><html><head></head><body>
<button>Button</button>
${CHECKED_INPUT_TYPES.map((type) => `<input type="${type}">`).join('\n')}
<select><option>Option</option></select>
<select multiple><option>Option</option></select>
<textarea></textarea>
<details><summary>Summary</summary></details>
<details open><summary>Summary</summary></details>
<a href="#">Link</a>
</body></html>`;
/** Pixels a box may miss the viewport edge by and still cover it. */
const COVER_TOLERANCE_PX = 0.5;
/** Pixels a label may overflow its button by before the rule counts it as cut. */
const CLIP_TOLERANCE_PX = 1;
/** The `samplePage` arguments that do not depend on the scope. */
const SAMPLE_ARGS: Omit<SampleArgs, 'drawerSelector'> = {
  backdropSelector: CART_BACKDROP_SELECTOR,
  inputTypes: CHECKED_INPUT_TYPES,
  buttonInputTypes: BUTTON_INPUT_TYPES,
  properties: SAMPLED_PROPERTIES,
  placeholder: PLACEHOLDER_VARIANT_TITLE,
};
const NAVIGATION_TIMEOUT_MS = 30_000;
const SETTLE_MS = 300;

type Page = BrowserSession['page'];
type BrowserContext = ReturnType<Page['context']>;
type StyleSample = Readonly<Record<string, string>>;

/** `page` checks the whole page; `cartDrawer` checks the open cart drawer over it. */
export type LintScope = 'page' | 'cartDrawer';

export type LintRule =
  | 'unstyled_control'
  | 'unstyled_summary'
  | 'unstyled_link'
  | 'clipped_label'
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
    ...SAMPLE_ARGS,
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
    ...sample.labels.flatMap(clippedFinding),
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
    'Give every visible control shop styles: a background and a border from the theme tokens. Draw checkboxes, radios and range inputs with `appearance: none` and shop styles (a border, a background and a check mark or dot when checked); `accent-color` alone keeps the native widget. Style the `::file-selector-button` of a file input.',
  unstyled_summary:
    'Hide the browser disclosure marker of a `summary` with `list-style: none` and draw a shop marker (for example a chevron in `summary::after`); `::-webkit-details-marker` does not hide it in Chromium.',
  unstyled_link:
    'Give links a color from the theme tokens (for example `a { color: inherit }` or the accent token), not the browser default blue.',
  clipped_label:
    'Let the button fit its whole label: remove the fixed width or height that cuts it, or make the button wider; do not hide the overflow of a label.',
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
    const sample = await page.evaluate(samplePage, { drawerSelector: null, ...SAMPLE_ARGS });
    return new Map(sample.controls.map((control) => [control.key, control.style]));
  } finally {
    await page.close();
  }
}

/**
 * The `unstyled_*` finding of one sampled element, if it keeps the browser
 * default look: a native widget by its `appearance`, any other element by
 * the properties of its kind that all equal its bare baseline.
 */
function unstyledFinding(
  control: ControlSample,
  baseline: ReadonlyMap<string, StyleSample>,
): LintFinding[] {
  const at = { selector: control.selector, text: control.text };
  const element = controlElement(control.key);
  const [tag, type = ''] = control.key.split(':');
  if (tag === 'input' && NATIVE_INPUT_TYPES.includes(type)) {
    const appearance = control.style.appearance;
    if (appearance === 'none') return [];
    return [
      {
        rule: 'unstyled_control',
        ...at,
        detail: `keeps the native browser widget of \`${element}\` (appearance ${appearance}); \`accent-color\` only tints it`,
      },
    ];
  }
  const bare = baseline.get(control.key);
  const rule: LintRule =
    tag === 'a' ? 'unstyled_link' : tag === 'summary' ? 'unstyled_summary' : 'unstyled_control';
  const properties =
    rule === 'unstyled_link'
      ? LINK_PROPERTIES
      : rule === 'unstyled_summary'
        ? SUMMARY_PROPERTIES
        : BOX_PROPERTIES;
  if (
    bare === undefined ||
    properties.some((property) => control.style[property] !== bare[property])
  ) {
    return [];
  }
  const look = properties.map((property) => `${property} ${control.style[property]}`).join('; ');
  const detail =
    rule === 'unstyled_link'
      ? `keeps the browser default link color (${look})`
      : rule === 'unstyled_summary'
        ? `shows the browser disclosure marker of a bare \`summary\` (${look})`
        : `keeps the browser default look of a bare \`${element}\` (${look})`;
  return [{ rule, ...at, detail }];
}

/**
 * `input:checkbox` -> `input[type="checkbox"]`, `select:select-one` -> `select`,
 * `input:file` -> `input[type="file"]::file-selector-button` (the part the rule checks).
 */
function controlElement(key: string): string {
  const [tag = key, type] = key.split(':');
  if (tag === 'input' && type === 'file') return 'input[type="file"]::file-selector-button';
  if (tag === 'input' && type !== undefined) return `input[type="${type}"]`;
  if (type === 'select-multiple') return 'select[multiple]';
  return tag;
}

/** The `clipped_label` finding of one sampled button, if its overflow hides part of its label. */
function clippedFinding(label: LabelSample): LintFinding[] {
  const cutX =
    label.overflowX !== 'visible' &&
    label.textOverflow !== 'ellipsis' &&
    label.scrollWidth > label.clientWidth + CLIP_TOLERANCE_PX;
  const cutY =
    label.overflowY !== 'visible' && label.scrollHeight > label.clientHeight + CLIP_TOLERANCE_PX;
  if (!cutX && !cutY) return [];
  const overflow =
    label.overflowX === label.overflowY ? label.overflowX : `${label.overflowX} ${label.overflowY}`;
  return [
    {
      rule: 'clipped_label',
      selector: label.selector,
      text: label.text,
      detail: `the label is cut: it needs ${label.scrollWidth}x${label.scrollHeight} px but the box shows ${label.clientWidth}x${label.clientHeight} px (overflow ${overflow})`,
    },
  ];
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

/** What `samplePage` reads about one visible control, `summary` or link. */
interface ControlSample {
  /**
   * `button`, `textarea`, `a`, `input:<type>`, `select:<type>`, or
   * `summary:open` and `summary:closed` by the state of its `details`.
   */
  readonly key: string;
  readonly selector: string;
  readonly text: string;
  readonly style: StyleSample;
}

interface ElementSample {
  readonly selector: string;
  readonly text: string;
}

/** What `samplePage` reads about one visible button with text. */
interface LabelSample extends ElementSample {
  readonly scrollWidth: number;
  readonly scrollHeight: number;
  readonly clientWidth: number;
  readonly clientHeight: number;
  readonly overflowX: string;
  readonly overflowY: string;
  readonly textOverflow: string;
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
  readonly labels: readonly LabelSample[];
  readonly placeholders: readonly ElementSample[];
  /** Read for the drawer scope only; `null` when the drawer is not open. */
  readonly drawer?: DrawerSample | null;
}

interface SampleArgs {
  /** The open drawer to check inside; `null` checks the whole page. */
  readonly drawerSelector: string | null;
  readonly backdropSelector: string;
  readonly inputTypes: readonly string[];
  readonly buttonInputTypes: readonly string[];
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
  readonly scrollWidth: number;
  readonly scrollHeight: number;
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
  getComputedStyle(
    element: DomElement,
    pseudoElement?: string | null,
  ): { getPropertyValue(name: string): string };
}

/**
 * Runs in the browser: read the visible controls, summaries and links, the
 * visible buttons with text, the visible placeholder titles and, for the
 * drawer scope, the drawer's backdrop and images. It is serialized into the
 * page, so it uses nothing outside its own body.
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
  const isButtonInput = (element: DomElement): boolean =>
    element.tagName === 'INPUT' && args.buttonInputTypes.includes(element.type ?? '');
  /** The text that the element shows: a button input shows its value. */
  const shownText = (element: DomElement): string =>
    clean(isButtonInput(element) ? (element.getAttribute('value') ?? '') : element.innerText);
  const textOf = (element: DomElement): string => {
    if (['A', 'BUTTON', 'SUMMARY'].includes(element.tagName)) {
      return clean(element.innerText || (element.getAttribute('aria-label') ?? ''));
    }
    const label = element.labels?.[0];
    return clean(
      element.getAttribute('aria-label') ??
        (label === undefined ? null : label.innerText) ??
        (isButtonInput(element) ? element.getAttribute('value') : null) ??
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
      return { controls: [], labels: [], placeholders: [], drawer: null };
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
  const checked = 'button, input, select, textarea, summary, a[href]';
  for (const element of root.querySelectorAll(checked)) {
    const tag = element.tagName.toLowerCase();
    const type = element.type ?? '';
    if (tag === 'input' && !args.inputTypes.includes(type)) continue;
    if (tag === 'a' && shownText(element) === '') continue;
    if (!visible(element)) continue;
    const pseudo = tag === 'input' && type === 'file' ? '::file-selector-button' : null;
    const style = win.getComputedStyle(element, pseudo);
    const sampled: Record<string, string> = Object.fromEntries(
      args.properties.map((property) => [property, style.getPropertyValue(property)]),
    );
    let key = tag === 'input' || tag === 'select' ? `${tag}:${type}` : tag;
    if (tag === 'summary') {
      key = element.parentElement?.getAttribute('open') == null ? 'summary:closed' : 'summary:open';
      sampled['::marker content'] = win
        .getComputedStyle(element, '::marker')
        .getPropertyValue('content');
    }
    controls.push({ key, selector: cssPath(element), text: textOf(element), style: sampled });
  }

  const labels: LabelSample[] = [];
  for (const element of root.querySelectorAll('button, input, [role="button"], a[href]')) {
    const buttonLike =
      element.tagName === 'BUTTON' ||
      isButtonInput(element) ||
      element.getAttribute('role') === 'button' ||
      (element.tagName === 'A' && [...element.classList].some((name) => /button|btn/i.test(name)));
    if (!buttonLike || shownText(element) === '' || !visible(element)) continue;
    const style = win.getComputedStyle(element);
    labels.push({
      selector: cssPath(element),
      text: textOf(element),
      scrollWidth: element.scrollWidth,
      scrollHeight: element.scrollHeight,
      clientWidth: element.clientWidth,
      clientHeight: element.clientHeight,
      overflowX: style.getPropertyValue('overflow-x'),
      overflowY: style.getPropertyValue('overflow-y'),
      textOverflow: style.getPropertyValue('text-overflow'),
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
  return drawer === undefined
    ? { controls, labels, placeholders }
    : { controls, labels, placeholders, drawer };
}
