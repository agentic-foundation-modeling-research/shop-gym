/**
 * Bot-check pages: pages that a site shows in place of the page that was
 * asked for, to find out whether the visitor is a person. Storefront
 * exploration finds them by markers in their HTML and never tries to pass
 * one.
 */

/** HTML substrings of a Cloudflare challenge page. */
export const CLOUDFLARE_MARKERS: readonly string[] = [
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
export const CAPTCHA_MARKERS: readonly string[] = [
  'Enter the characters you see below',
  'Type the characters you see in this image',
  '/errors/validateCaptcha',
];

/** The first Cloudflare or captcha marker in `html`, or `undefined` when the page is not a bot check. */
export function botCheckMarker(html: string): string | undefined {
  return [...CLOUDFLARE_MARKERS, ...CAPTCHA_MARKERS].find((marker) => html.includes(marker));
}
