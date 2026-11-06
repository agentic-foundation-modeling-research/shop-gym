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

/** The first Cloudflare challenge marker in `html`, or `undefined`. */
export function cloudflareMarker(html: string): string | undefined {
  return CLOUDFLARE_MARKERS.find((marker) => html.includes(marker));
}

/** The first captcha marker in `html`, or `undefined`. */
export function captchaMarker(html: string): string | undefined {
  return CAPTCHA_MARKERS.find((marker) => html.includes(marker));
}

/** The first Cloudflare or captcha marker in `html`, or `undefined` when the page is not a bot check. */
export function botCheckMarker(html: string): string | undefined {
  return cloudflareMarker(html) ?? captchaMarker(html);
}
