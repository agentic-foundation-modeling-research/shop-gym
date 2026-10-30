import type { LoaderFunctionArgs } from 'react-router';
import { variantTitle } from '~/components/checkout';
import { getAppContext, getCartId } from '~/lib/context';
import { CART_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { Cart } from '~/lib/types';

interface CartQueryData {
  readonly cart: Cart | null;
}

interface AjaxCartItem {
  readonly id: number;
  readonly variant_id: number;
  readonly product_title: string;
  readonly variant_title: string | null;
  readonly quantity: number;
  readonly price: number;
  readonly line_price: number;
}

interface AjaxCart {
  readonly item_count: number;
  readonly items: readonly AjaxCartItem[];
  readonly total_price: number;
  readonly total_discount: number;
  readonly discount_codes: readonly { readonly code: string; readonly applicable: boolean }[];
}

const EMPTY_CART: AjaxCart = {
  item_count: 0,
  items: [],
  total_price: 0,
  total_discount: 0,
  discount_codes: [],
};

/**
 * `GET /cart.js`: the session's cart in the request's episode, as the JSON
 * of Shopify's AJAX Cart API (`GET /{locale}/cart.js`). Task generation
 * reads the cart this way on SandboxShops and on Live storefronts, so keep
 * the path and the fields. The route is read only: it has no action and
 * sets no cookie. It needs no login. With no cart, or a cart id that the
 * episode does not know, it returns the empty cart, not an error.
 *
 * The fields have Shopify's names and meanings. Every amount is an integer
 * in the currency's subunit (cents):
 *
 * - `items[].id` and `items[].variant_id`: the numeric variant id.
 * - `items[].product_title`; `items[].variant_title`, null for the
 *   "Default Title" variant of a product with one variant.
 * - `items[].quantity`; `items[].price`, the unit price; `items[].line_price`,
 *   the price times the quantity. Lines have no discounts of their own.
 * - `item_count`: the sum of the quantities.
 * - `total_discount`: what the cart's Discount code takes off the
 *   merchandise; 0 for a free-shipping code, as a cart has no shipping.
 * - `total_price`: the merchandise subtotal less `total_discount`. Tax and
 *   shipping come at checkout.
 * - `discount_codes[]`: `code` and `applicable` for each code on the cart.
 *   A code stays on the cart with `applicable: false` when the cart drops
 *   below the code's minimum.
 *
 * Shopify's AJAX Cart API reference documents each of these fields except
 * `discount_codes`. Shopify's `/cart.js` returns that field too, with the
 * `code` and `applicable` of the Storefront API's `CartDiscountCode`. The
 * other Shopify fields are left out.
 */
export async function loader({ context }: LoaderFunctionArgs): Promise<Response> {
  const appContext = getAppContext(context);
  const cartId = getCartId(appContext);
  if (cartId === null) return Response.json(EMPTY_CART);
  const { cart } = await storefrontQuery<CartQueryData>(appContext, CART_QUERY, { cartId });
  return Response.json(cart === null ? EMPTY_CART : ajaxCart(cart));
}

function ajaxCart(cart: Cart): AjaxCart {
  const totalDiscount = cart.discountAllocations
    .filter((allocation) => allocation.targetType === 'LINE_ITEM')
    .reduce((sum, allocation) => sum + toCents(allocation.discountedAmount.amount), 0);
  return {
    item_count: cart.totalQuantity,
    items: cart.lines.nodes.map((line) => {
      const variantId = numericId(line.merchandise.id);
      return {
        id: variantId,
        variant_id: variantId,
        product_title: line.merchandise.product.title,
        variant_title: variantTitle(line.merchandise.title),
        quantity: line.quantity,
        price: toCents(line.merchandise.price.amount),
        line_price: toCents(line.cost.totalAmount.amount),
      };
    }),
    total_price: toCents(cart.cost.subtotalAmount.amount) - totalDiscount,
    total_discount: totalDiscount,
    discount_codes: cart.discountCodes.map(({ code, applicable }) => ({ code, applicable })),
  };
}

/** The number at the end of a gid, e.g. 123 for `gid://shopify/ProductVariant/123`. */
function numericId(gid: string): number {
  return Number(gid.slice(gid.lastIndexOf('/') + 1));
}

function toCents(amount: string): number {
  return Math.round(Number.parseFloat(amount) * 100);
}
