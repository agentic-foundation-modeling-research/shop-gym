/**
 * Bot-check pages: pages that a site shows in place of the page that was
 * asked for, to find out whether the visitor is a person. Storefront
 * exploration finds them by markers in their HTML and never tries to pass
 * one.
 */

/** HTML substrings of a Cloudflare challenge page. */
const CLOUDFLARE_MARKERS: readonly string[] = [
  'cf-browser-verification',
  '__cf_chl_',
  'Just a moment...',
  'Checking your browser before accessing',
  'Attention Required! | Cloudflare',
  'cf-challenge-running',
];

/**
 * HTML substrings of a captcha page: the two prompts and the form path of
 * the captcha page of a large marketplace.
 */
const CAPTCHA_MARKERS: readonly string[] = [
  'Enter the characters you see below',
  'Type the characters you see in this image',
  '/errors/validateCaptcha',
];

/**
 * HTML substrings of an interstitial page: a page with one button that
 * the visitor must click to go on to the shop. The heading of the
 * interstitial page of a large marketplace.
 */
const INTERSTITIAL_MARKERS: readonly string[] = ['Click the button below to continue shopping'];

/**
 * HTML substrings of a rate-limit page: the title of the page that a
 * large marketplace sends with HTTP 503 when it refuses a browser that
 * opens its search and product URLs directly. A normal error page can
 * have the same words, so they count only on a page served with
 * `RATE_LIMIT_STATUS`.
 */
const RATE_LIMIT_MARKERS: readonly string[] = ['Sorry! Something went wrong!'];

/** The HTTP status of a rate-limit page. */
const RATE_LIMIT_STATUS = 503;

/** The first Cloudflare challenge marker in `html`, or `undefined`. */
export function cloudflareMarker(html: string): string | undefined {
  return firstMarker(CLOUDFLARE_MARKERS, html);
}

/**
 * The first marker of a bot check that the site serves itself, not a
 * Cloudflare challenge in front of it: a captcha page, an interstitial
 * page or a rate-limit page. `status` is the HTTP status of the page, or
 * `null` when it is not known; a rate-limit marker counts only with
 * HTTP 503. `undefined` when the page has none.
 */
export function siteBotCheckMarker(html: string, status: number | null): string | undefined {
  return (
    firstMarker(CAPTCHA_MARKERS, html) ??
    firstMarker(INTERSTITIAL_MARKERS, html) ??
    (status === RATE_LIMIT_STATUS ? firstMarker(RATE_LIMIT_MARKERS, html) : undefined)
  );
}

/**
 * The first bot-check marker of a page, or `undefined` when the page is
 * not a bot check. `status` is as for `siteBotCheckMarker`.
 */
export function botCheckMarker(html: string, status: number | null): string | undefined {
  return cloudflareMarker(html) ?? siteBotCheckMarker(html, status);
}

function firstMarker(markers: readonly string[], html: string): string | undefined {
  return markers.find((marker) => html.includes(marker));
}
