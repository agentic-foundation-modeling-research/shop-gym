import {Link, useLoaderData, type LoaderFunctionArgs} from 'react-router';
import {ImageFrame, Price} from '~/components/storefront';
import {getAppContext, getCartId} from '~/lib/context';
import {CART_QUERY} from '~/lib/queries';
import {storefrontQuery} from '~/lib/storefront';
import type {Cart, CartLine} from '~/lib/types';

interface CartQueryData {
  readonly cart: Cart | null;
}

export function meta() {
  return [{title: 'Checkout'}];
}

export async function loader({
  context,
}: LoaderFunctionArgs): Promise<CartQueryData> {
  const appContext = getAppContext(context);
  const cartId = getCartId(appContext);
  if (cartId === null) return {cart: null};
  return storefrontQuery<CartQueryData>(appContext, CART_QUERY, {cartId});
}

export default function CheckoutRoute() {
  const {cart} = useLoaderData<typeof loader>();
  if (!cart || cart.lines.nodes.length === 0) {
    return (
      <div className="page-width stack">
        <h1>Checkout</h1>
        <p>Your cart is empty.</p>
        <Link to="/collections">Browse collections</Link>
      </div>
    );
  }

  return (
    <div className="page-width checkout-page">
      <section className="stack" aria-labelledby="checkout-heading">
        <p className="eyebrow">Checkout confirmation</p>
        <h1 id="checkout-heading">Review your order</h1>
        <p className="muted">
          Confirm the items, promo codes, and total before completing checkout.
        </p>
        <div className="checkout-actions">
          <Link className="button-link" to="/cart">
            Return to cart
          </Link>
          <Link to="/collections">Continue shopping</Link>
        </div>
      </section>
      <aside className="checkout-summary" aria-label="Order summary">
        <ul className="checkout-lines">
          {cart.lines.nodes.map((line) => (
            <CheckoutLineItem key={line.id} line={line} />
          ))}
        </ul>
        {cart.discountCodes.length > 0 ? (
          <div className="checkout-discounts">
            <span>Promo codes</span>
            <span>
              {cart.discountCodes.map((discount) => discount.code).join(', ')}
            </span>
          </div>
        ) : null}
        <div className="cart-total-row">
          <span>Subtotal</span>
          <Price money={cart.cost.subtotalAmount} />
        </div>
        <div className="cart-total-row cart-total-row-grand">
          <span>Total</span>
          <Price money={cart.cost.totalAmount} />
        </div>
      </aside>
    </div>
  );
}

function CheckoutLineItem({line}: {readonly line: CartLine}) {
  return (
    <li className="checkout-line">
      <div className="checkout-line-image">
        <ImageFrame
          image={line.merchandise.image}
          altFallback={line.merchandise.product.title}
        />
      </div>
      <div>
        <p>{line.merchandise.product.title}</p>
        <p className="muted">
          {line.quantity} x {line.merchandise.title}
        </p>
      </div>
      <Price money={line.cost.totalAmount} />
    </li>
  );
}
