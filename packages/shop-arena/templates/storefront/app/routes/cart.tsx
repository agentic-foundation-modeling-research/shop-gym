import {
  type ActionFunctionArgs,
  type LoaderFunctionArgs,
  redirect,
  useActionData,
  useLoaderData,
} from 'react-router';
import { CartLineItem, CartSummary } from '~/components/storefront';
import { commitCartId, getAppContext, getCartId } from '~/lib/context';
import { applyDiscountCode, removeDiscountCode } from '~/lib/discount';
import {
  CART_CREATE_MUTATION,
  CART_LINES_ADD_MUTATION,
  CART_LINES_REMOVE_MUTATION,
  CART_LINES_UPDATE_MUTATION,
  CART_QUERY,
} from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { Cart } from '~/lib/types';

interface CartQueryData {
  readonly cart: Cart | null;
}

interface CartMutationPayload {
  readonly cart: Cart | null;
  readonly userErrors: readonly { readonly message: string }[];
}

interface CartCreateData {
  readonly cartCreate: CartMutationPayload;
}

interface CartLinesAddData {
  readonly cartLinesAdd: CartMutationPayload;
}

interface CartLinesUpdateData {
  readonly cartLinesUpdate: CartMutationPayload;
}

interface CartLinesRemoveData {
  readonly cartLinesRemove: CartMutationPayload;
}

export function meta() {
  return [{ title: 'Cart' }];
}

export async function loader({ context }: LoaderFunctionArgs): Promise<CartQueryData> {
  const appContext = getAppContext(context);
  const cartId = getCartId(appContext);
  if (cartId === null) return { cart: null };
  return storefrontQuery<CartQueryData>(appContext, CART_QUERY, { cartId });
}

export async function action({ context, request }: ActionFunctionArgs) {
  const appContext = getAppContext(context);
  const formData = await request.formData();
  const intent = stringField(formData, 'intent');
  const cartId = getCartId(appContext);
  const redirectTo = safeRedirect(optionalStringField(formData, 'redirectTo') ?? '/cart');

  if (intent === 'add') {
    const merchandiseId = stringField(formData, 'merchandiseId');
    const quantity = quantityField(formData, 'quantity', 1);
    const line = { merchandiseId, quantity };
    const cart =
      cartId === null
        ? (
            await storefrontQuery<CartCreateData>(appContext, CART_CREATE_MUTATION, {
              input: { lines: [line] },
            })
          ).cartCreate.cart
        : (
            await storefrontQuery<CartLinesAddData>(appContext, CART_LINES_ADD_MUTATION, {
              cartId,
              lines: [line],
            })
          ).cartLinesAdd.cart;
    if (!cart) {
      throw new Response('Cart mutation did not return a cart.', { status: 502 });
    }
    return redirect(redirectTo, {
      headers: await commitCartId(appContext, cart.id),
    });
  }

  if (cartId === null) {
    return redirect(redirectTo);
  }

  if (intent === 'discount') {
    const applied = await applyDiscountCode(
      appContext,
      cartId,
      optionalStringField(formData, 'discountCode') ?? '',
    );
    // A turned-down code renders the cart page with the error, also for the drawer.
    if (!applied) return { discountRejected: true };
    return redirect(redirectTo);
  }

  if (intent === 'discount-remove') {
    await removeDiscountCode(appContext, cartId);
    return redirect(redirectTo);
  }

  if (intent === 'update') {
    const lineId = stringField(formData, 'lineId');
    const quantity = quantityField(formData, 'quantity', 0);
    const data = await storefrontQuery<CartLinesUpdateData>(
      appContext,
      CART_LINES_UPDATE_MUTATION,
      { cartId, lines: [{ id: lineId, quantity }] },
    );
    const cart = data.cartLinesUpdate.cart;
    if (!cart) {
      throw new Response('Cart update did not return a cart.', { status: 502 });
    }
    return redirect(redirectTo, {
      headers: await commitCartId(appContext, cart.id),
    });
  }

  if (intent === 'remove') {
    const lineId = stringField(formData, 'lineId');
    const data = await storefrontQuery<CartLinesRemoveData>(
      appContext,
      CART_LINES_REMOVE_MUTATION,
      { cartId, lineIds: [lineId] },
    );
    const cart = data.cartLinesRemove.cart;
    if (!cart) {
      throw new Response('Cart remove did not return a cart.', { status: 502 });
    }
    return redirect(redirectTo, {
      headers: await commitCartId(appContext, cart.id),
    });
  }

  throw new Response(`Unknown cart intent: ${intent}`, { status: 400 });
}

export default function CartRoute() {
  const { cart } = useLoaderData<typeof loader>();
  const actionData = useActionData<typeof action>();
  return (
    <div className="page-width stack">
      <h1>Cart</h1>
      {!cart || cart.lines.nodes.length === 0 ? (
        <p>Your cart is empty.</p>
      ) : (
        <>
          <ul className="cart-lines">
            {cart.lines.nodes.map((line) => (
              <CartLineItem key={line.id} line={line} />
            ))}
          </ul>
          <CartSummary
            cart={cart}
            layout="page"
            discountRejected={actionData?.discountRejected === true}
          />
        </>
      )}
    </div>
  );
}

function stringField(formData: FormData, name: string): string {
  const value = formData.get(name);
  if (typeof value !== 'string' || value.length === 0) {
    throw new Response(`Missing form field: ${name}`, { status: 400 });
  }
  return value;
}

function optionalStringField(formData: FormData, name: string): string | null {
  const value = formData.get(name);
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function safeRedirect(raw: string): string {
  if (!raw.startsWith('/') || raw.startsWith('//')) return '/cart';
  return raw;
}

function quantityField(formData: FormData, name: string, fallback: number): number {
  const value = formData.get(name);
  if (typeof value !== 'string' || value.length === 0) return fallback;
  const quantity = Number.parseInt(value, 10);
  if (!Number.isInteger(quantity) || quantity < 0) {
    throw new Response(`Invalid quantity: ${value}`, { status: 400 });
  }
  return quantity;
}
