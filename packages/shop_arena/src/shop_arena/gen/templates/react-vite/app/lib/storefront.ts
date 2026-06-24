import type {AppLoadContext} from '~/lib/context';

export class StorefrontHttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'StorefrontHttpError';
  }
}

export class StorefrontJsonError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'StorefrontJsonError';
  }
}

export class StorefrontGraphQLError extends Error {
  constructor(readonly errors: readonly unknown[]) {
    super(`shop_backend GraphQL error: ${JSON.stringify(errors)}`);
    this.name = 'StorefrontGraphQLError';
  }
}

export async function storefrontQuery<TData>(
  context: AppLoadContext,
  query: string,
  variables: Record<string, unknown> = {},
): Promise<TData> {
  const response = await fetch(`${resolveBackendUrl(context)}/graphql`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({query, variables}),
  });

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new StorefrontJsonError(`Invalid JSON from shop_backend: ${message}`);
  }

  if (!response.ok) {
    throw new StorefrontHttpError(
      `shop_backend HTTP ${response.status}: ${JSON.stringify(payload)}`,
      response.status,
    );
  }

  if (!isRecord(payload)) {
    throw new StorefrontJsonError('shop_backend response was not a JSON object.');
  }
  const errors = payload.errors;
  if (Array.isArray(errors) && errors.length > 0) {
    throw new StorefrontGraphQLError(errors);
  }
  const data = payload.data;
  if (!isRecord(data)) {
    throw new StorefrontJsonError('shop_backend response did not contain data.');
  }
  return data as TData;
}

export function resolveBackendUrl(context: AppLoadContext): string {
  const raw =
    context.env.PUBLIC_STORE_DOMAIN?.trim() || context.env.SHOP_BACKEND_URL?.trim();
  if (!raw) {
    throw new Error('Set PUBLIC_STORE_DOMAIN or SHOP_BACKEND_URL for shop_backend.');
  }
  return raw.replace(/\/+$/, '');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
