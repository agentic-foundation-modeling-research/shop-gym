import type { AppLoadContext } from '~/lib/context';
import { CART_DISCOUNT_CODES_UPDATE_MUTATION, CART_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { Cart } from '~/lib/types';

interface CartQueryData {
  readonly cart: Cart | null;
}

interface CartDiscountCodesUpdateData {
  readonly cartDiscountCodesUpdate: {
    readonly cart: Cart | null;
  };
}

/**
 * Makes `code` the cart's one Discount code. A code that does not apply
 * (unknown, or its minimum subtotal not met) is not kept: the cart gets back
 * the code it held before. Returns whether `code` applies.
 */
export async function applyDiscountCode(
  context: AppLoadContext,
  cartId: string,
  code: string,
): Promise<boolean> {
  if (code.trim().length === 0) return false;
  const before = await storefrontQuery<CartQueryData>(context, CART_QUERY, { cartId });
  const earlierCodes = before.cart?.discountCodes.map((entry) => entry.code) ?? [];
  const after = await updateDiscountCodes(context, cartId, [code]);
  if (after.discountCodes.some((entry) => entry.applicable)) return true;
  await updateDiscountCodes(context, cartId, earlierCodes);
  return false;
}

export async function removeDiscountCode(context: AppLoadContext, cartId: string): Promise<void> {
  await updateDiscountCodes(context, cartId, []);
}

async function updateDiscountCodes(
  context: AppLoadContext,
  cartId: string,
  discountCodes: readonly string[],
): Promise<Cart> {
  const data = await storefrontQuery<CartDiscountCodesUpdateData>(
    context,
    CART_DISCOUNT_CODES_UPDATE_MUTATION,
    { cartId, discountCodes },
  );
  const cart = data.cartDiscountCodesUpdate.cart;
  if (!cart) {
    throw new Response('Discount update did not return a cart.', { status: 502 });
  }
  return cart;
}
