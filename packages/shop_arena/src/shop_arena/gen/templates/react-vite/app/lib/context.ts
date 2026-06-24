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
}

const CART_ID_KEY = 'cartId';

export function getAppContext(context: unknown): AppLoadContext {
  if (!isAppLoadContext(context)) {
    throw new Error('React Vite storefront load context is missing.');
  }
  return context;
}

export function getCartId(context: AppLoadContext): string | null {
  const value = context.session.get(CART_ID_KEY);
  return typeof value === 'string' && value.length > 0 ? value : null;
}

export async function commitCartId(
  context: AppLoadContext,
  cartId: string,
): Promise<Headers> {
  context.session.set(CART_ID_KEY, cartId);
  return commitSessionHeaders(context);
}

export async function clearCartId(context: AppLoadContext): Promise<Headers> {
  context.session.unset(CART_ID_KEY);
  return commitSessionHeaders(context);
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
    record.sessionStorage !== null
  );
}
