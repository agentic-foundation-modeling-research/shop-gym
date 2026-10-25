/**
 * Minimal HTTP client for driving the storefront over plain `fetch`: a
 * cookie jar so the signed session (cart id, login) survives across calls,
 * manual redirect handling so verifiers can assert on `Location`, and an
 * optional `x-shopgym-episode` header so backend state stays isolated per
 * check.
 */

export interface HttpResult {
  readonly status: number;
  /** `Location` header, or `''` when absent. */
  readonly location: string;
  readonly body: string;
}

const DEFAULT_TIMEOUT_MS = 30_000;

export interface StorefrontClientOptions {
  readonly baseUrl: string;
  /** Sent as `x-shopgym-episode` on every request. */
  readonly episodeId?: string;
  readonly timeoutMs?: number;
}

export class StorefrontClient {
  readonly cookies = new Map<string, string>();
  private readonly baseUrl: string;
  private readonly episodeId: string | undefined;
  private readonly timeoutMs: number;

  constructor(options: StorefrontClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, '');
    this.episodeId = options.episodeId;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  get(route: string): Promise<HttpResult> {
    return this.request(route, { method: 'GET' });
  }

  /** POST a `application/x-www-form-urlencoded` body, like a browser form. */
  post(route: string, form: Readonly<Record<string, string>>): Promise<HttpResult> {
    return this.request(route, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(form).toString(),
    });
  }

  private async request(route: string, init: RequestInit): Promise<HttpResult> {
    const headers = new Headers(init.headers);
    if (this.cookies.size > 0) {
      headers.set('cookie', [...this.cookies].map(([k, v]) => `${k}=${v}`).join('; '));
    }
    if (this.episodeId !== undefined) {
      headers.set('x-shopgym-episode', this.episodeId);
    }
    const response = await fetch(`${this.baseUrl}${route}`, {
      ...init,
      headers,
      redirect: 'manual',
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    for (const cookie of response.headers.getSetCookie()) {
      const [pair] = cookie.split(';');
      const eq = pair?.indexOf('=') ?? -1;
      if (pair !== undefined && eq > 0) {
        this.cookies.set(pair.slice(0, eq), pair.slice(eq + 1));
      }
    }
    return {
      status: response.status,
      location: response.headers.get('location') ?? '',
      body: await response.text(),
    };
  }
}

const EXCERPT_CHARS = 300;

/** A short, tag-stripped excerpt of a response body for failure feedback. */
export function bodyExcerpt(body: string): string {
  const text = body
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return text.length <= EXCERPT_CHARS ? text : `${text.slice(0, EXCERPT_CHARS)}...`;
}

/** `value` of the first enabled `merchandiseId` radio on a product page. */
export function firstAvailableMerchandiseId(html: string): string | undefined {
  for (const [input] of html.matchAll(/<input[^>]*name="merchandiseId"[^>]*>/g)) {
    if (input.includes('disabled')) {
      continue;
    }
    const value = /value="([^"]+)"/.exec(input)?.[1];
    if (value !== undefined) {
      return value;
    }
  }
  return undefined;
}
