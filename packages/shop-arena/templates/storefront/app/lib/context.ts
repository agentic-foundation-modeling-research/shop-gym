export interface AppEnv {
  readonly PUBLIC_STORE_DOMAIN?: string;
  readonly SHOP_BACKEND_URL?: string;
  readonly SESSION_SECRET?: string;
  readonly PUBLIC_FOOTER_MENU_HANDLES?: string;
}

export interface CookieSession {
  get(name: string): unknown;
  set(name: string, value: string): void;
  unset(name: string): void;
}

export interface CookieSessionStorage {
  commitSession(session: CookieSession): Promise<string> | string;
}

export interface AppLoadContext {
  readonly env: AppEnv;
  readonly session: CookieSession;
  readonly sessionStorage: CookieSessionStorage;
  /** Value of the incoming `x-shopgym-episode` header, forwarded to the backend. */
  readonly episodeId: string | null;
}

const CART_ID_KEY = 'cartId';
const CUSTOMER_ACCESS_TOKEN_KEY = 'customerAccessToken';

export function getAppContext(context: unknown): AppLoadContext {
  if (!isAppLoadContext(context)) {
    throw new Error('React Vite storefront load context is missing.');
  }
  return context;
}

export function getCartId(context: AppLoadContext): string | null {
  return getSessionString(context, CART_ID_KEY);
}

export async function commitCartId(context: AppLoadContext, cartId: string): Promise<Headers> {
  context.session.set(CART_ID_KEY, cartId);
  return commitSessionHeaders(context);
}

export async function clearCartId(context: AppLoadContext): Promise<Headers> {
  context.session.unset(CART_ID_KEY);
  return commitSessionHeaders(context);
}

export function getCustomerAccessToken(context: AppLoadContext): string | null {
  return getSessionString(context, CUSTOMER_ACCESS_TOKEN_KEY);
}

export async function commitCustomerAccessToken(
  context: AppLoadContext,
  accessToken: string,
): Promise<Headers> {
  context.session.set(CUSTOMER_ACCESS_TOKEN_KEY, accessToken);
  return commitSessionHeaders(context);
}

export async function clearCustomerAccessToken(context: AppLoadContext): Promise<Headers> {
  context.session.unset(CUSTOMER_ACCESS_TOKEN_KEY);
  return commitSessionHeaders(context);
}

function getSessionString(context: AppLoadContext, key: string): string | null {
  const value = context.session.get(key);
  return typeof value === 'string' && value.length > 0 ? value : null;
}

async function commitSessionHeaders(context: AppLoadContext): Promise<Headers> {
  const cookie = await context.sessionStorage.commitSession(context.session);
  const headers = new Headers();
  headers.append('Set-Cookie', cookie);
  return headers;
}

function isAppLoadContext(value: unknown): value is AppLoadContext {
  if (typeof value !== 'object' || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.env === 'object' &&
    record.env !== null &&
    typeof record.session === 'object' &&
    record.session !== null &&
    typeof record.sessionStorage === 'object' &&
    record.sessionStorage !== null &&
    (typeof record.episodeId === 'string' || record.episodeId === null)
  );
}
