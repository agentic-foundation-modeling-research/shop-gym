import { useState } from 'react';
import {
  type ActionFunctionArgs,
  Form,
  Link,
  type LoaderFunctionArgs,
  redirect,
  useActionData,
  useLoaderData,
} from 'react-router';
import { FormErrors, orderPath } from '~/components/account';
import { ImageFrame, Price } from '~/components/storefront';
import { clearCartId, getAppContext, getCartId, getCustomerAccessToken } from '~/lib/context';
import { loadCustomer } from '~/lib/customer';
import {
  CART_BUYER_IDENTITY_UPDATE_MUTATION,
  CART_QUERY,
  CHECKOUT_COMPLETE_MUTATION,
  COMMERCE_SETTINGS_QUERY,
} from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type {
  Cart,
  CartLine,
  CheckoutUserError,
  CommerceSettings,
  Customer,
  MailingAddress,
  Money,
} from '~/lib/types';

interface CartQueryData {
  readonly cart: Cart | null;
}

interface CommerceSettingsData {
  readonly commerceSettings: CommerceSettings;
}

interface CheckoutCompleteData {
  readonly checkoutComplete: {
    readonly order: { readonly id: string; readonly orderNumber: number } | null;
    readonly userErrors: readonly CheckoutUserError[];
  };
}

interface CheckoutLoaderData {
  readonly cart: Cart | null;
  readonly settings: CommerceSettings;
  readonly customer: Customer | null;
}

interface CheckoutActionData {
  readonly errors: readonly CheckoutUserError[];
  readonly values: Record<string, string>;
}

const ADDRESS_FIELDS = [
  'firstName',
  'lastName',
  'company',
  'address1',
  'address2',
  'city',
  'province',
  'country',
  'zip',
  'phone',
] as const;

export function meta() {
  return [{ title: 'Checkout' }];
}

export async function loader({ context }: LoaderFunctionArgs): Promise<CheckoutLoaderData> {
  const appContext = getAppContext(context);
  const cartId = getCartId(appContext);
  const [cartData, settingsData, customer] = await Promise.all([
    cartId === null
      ? Promise.resolve({ cart: null })
      : storefrontQuery<CartQueryData>(appContext, CART_QUERY, { cartId }),
    storefrontQuery<CommerceSettingsData>(appContext, COMMERCE_SETTINGS_QUERY),
    loadCustomer(appContext),
  ]);
  return { cart: cartData.cart, settings: settingsData.commerceSettings, customer };
}

export async function action({ context, request }: ActionFunctionArgs) {
  const appContext = getAppContext(context);
  const cartId = getCartId(appContext);
  if (cartId === null) return redirect('/cart');

  const formData = await request.formData();
  const values = formValues(formData);
  const customerAccessToken = getCustomerAccessToken(appContext);
  if (customerAccessToken !== null) {
    await storefrontQuery(appContext, CART_BUYER_IDENTITY_UPDATE_MUTATION, {
      cartId,
      buyerIdentity: { customerAccessToken },
    });
  }

  const shippingAddress = Object.fromEntries(
    ADDRESS_FIELDS.map((field) => [field, values[field] ?? '']),
  );
  const data = await storefrontQuery<CheckoutCompleteData>(appContext, CHECKOUT_COMPLETE_MUTATION, {
    cartId,
    input: {
      email: values.email || null,
      shippingAddress,
      shippingMethodHandle: values.shippingMethodHandle || null,
      paymentMethodHandle: values.paymentMethodHandle || null,
    },
  });
  const { order, userErrors } = data.checkoutComplete;
  if (!order) {
    return { errors: userErrors, values } satisfies CheckoutActionData;
  }
  const destination =
    customerAccessToken === null ? `/checkout/confirmation/${order.orderNumber}` : orderPath(order);
  return redirect(destination, { headers: await clearCartId(appContext) });
}

export default function CheckoutRoute() {
  const { cart, settings, customer } = useLoaderData<typeof loader>();
  const actionData = useActionData<typeof action>();
  const [shippingHandle, setShippingHandle] = useState(
    actionData?.values.shippingMethodHandle ?? settings.shippingMethods[0]?.handle ?? '',
  );

  if (!cart || cart.lines.nodes.length === 0) {
    return (
      <div className="page-width stack">
        <h1>Checkout</h1>
        <p>Your cart is empty.</p>
        <Link to="/collections">Browse collections</Link>
      </div>
    );
  }

  const defaults = defaultValues(customer, actionData?.values);
  const fieldErrors = errorsByField(actionData?.errors ?? []);
  const totals = computeTotals(cart, settings, shippingHandle);

  return (
    <div className="page-width checkout-page">
      <Form method="post" className="stack" aria-labelledby="checkout-heading">
        <h1 id="checkout-heading">Checkout</h1>
        {customer ? (
          <p className="muted">Checking out as {customer.displayName}.</p>
        ) : (
          <p className="muted">
            Checking out as a guest. <Link to="/account/login?redirectTo=%2Fcheckout">Log in</Link>{' '}
            to use a saved address.
          </p>
        )}
        <FormErrors errors={actionData?.errors} />
        <fieldset className="form-grid">
          <legend>Contact</legend>
          <Field
            label="Email"
            name="email"
            type="email"
            autoComplete="email"
            required
            defaultValue={defaults.email}
            error={fieldErrors.email}
          />
        </fieldset>
        <fieldset className="form-grid">
          <legend>Shipping address</legend>
          <Field
            label="First name"
            name="firstName"
            autoComplete="given-name"
            required
            defaultValue={defaults.firstName}
            error={fieldErrors.firstName}
          />
          <Field
            label="Last name"
            name="lastName"
            autoComplete="family-name"
            required
            defaultValue={defaults.lastName}
            error={fieldErrors.lastName}
          />
          <Field
            label="Company (optional)"
            name="company"
            autoComplete="organization"
            defaultValue={defaults.company}
            error={fieldErrors.company}
          />
          <Field
            label="Address"
            name="address1"
            autoComplete="address-line1"
            required
            defaultValue={defaults.address1}
            error={fieldErrors.address1}
          />
          <Field
            label="Apartment, suite, etc. (optional)"
            name="address2"
            autoComplete="address-line2"
            defaultValue={defaults.address2}
            error={fieldErrors.address2}
          />
          <Field
            label="City"
            name="city"
            autoComplete="address-level2"
            required
            defaultValue={defaults.city}
            error={fieldErrors.city}
          />
          <Field
            label="Province / State"
            name="province"
            autoComplete="address-level1"
            defaultValue={defaults.province}
            error={fieldErrors.province}
          />
          <Field
            label="Country"
            name="country"
            autoComplete="country-name"
            required
            defaultValue={defaults.country}
            error={fieldErrors.country}
          />
          <Field
            label="Postal code"
            name="zip"
            autoComplete="postal-code"
            required
            defaultValue={defaults.zip}
            error={fieldErrors.zip}
          />
          <Field
            label="Phone (optional)"
            name="phone"
            type="tel"
            autoComplete="tel"
            defaultValue={defaults.phone}
            error={fieldErrors.phone}
          />
        </fieldset>
        <fieldset className="choice-list">
          <legend>Shipping method</legend>
          {settings.shippingMethods.map((method) => (
            <label className="choice" key={method.handle}>
              <input
                type="radio"
                name="shippingMethodHandle"
                value={method.handle}
                checked={method.handle === shippingHandle}
                onChange={() => setShippingHandle(method.handle)}
              />
              <span>{method.title}</span>
              <span className="variant-price">
                <Price money={method.price} />
              </span>
            </label>
          ))}
          <FieldError message={fieldErrors.shippingMethodHandle} />
        </fieldset>
        <fieldset className="choice-list">
          <legend>Payment method</legend>
          {settings.paymentMethods.map((method, index) => (
            <label className="choice" key={method.handle}>
              <input
                type="radio"
                name="paymentMethodHandle"
                value={method.handle}
                defaultChecked={
                  (defaults.paymentMethodHandle ?? settings.paymentMethods[0]?.handle) ===
                    method.handle ||
                  (!defaults.paymentMethodHandle && index === 0)
                }
              />
              <span>{method.title}</span>
            </label>
          ))}
          <FieldError message={fieldErrors.paymentMethodHandle} />
        </fieldset>
        <div className="checkout-actions">
          <button type="submit">Place order</button>
          <Link to="/cart">Return to cart</Link>
        </div>
      </Form>
      <aside className="checkout-summary" aria-label="Order summary">
        <ul className="checkout-lines">
          {cart.lines.nodes.map((line) => (
            <CheckoutLineItem key={line.id} line={line} />
          ))}
        </ul>
        <div className="cart-total-row">
          <span>Subtotal</span>
          <Price money={totals.subtotal} />
        </div>
        <div className="cart-total-row">
          <span>Shipping</span>
          <Price money={totals.shipping} />
        </div>
        <div className="cart-total-row">
          <span>Tax</span>
          <Price money={totals.tax} />
        </div>
        <div className="cart-total-row cart-total-row-grand">
          <span>Total</span>
          <Price money={totals.total} />
        </div>
      </aside>
    </div>
  );
}

function Field({
  label,
  name,
  error,
  ...inputProps
}: {
  readonly label: string;
  readonly name: string;
  readonly error?: string | undefined;
  readonly type?: string;
  readonly autoComplete?: string;
  readonly required?: boolean;
  readonly defaultValue?: string | undefined;
}) {
  return (
    <label>
      {label}
      <input name={name} aria-invalid={error ? true : undefined} {...inputProps} />
      <FieldError message={error} />
    </label>
  );
}

function FieldError({ message }: { readonly message: string | undefined }) {
  if (!message) return null;
  return <span className="field-error">{message}</span>;
}

function CheckoutLineItem({ line }: { readonly line: CartLine }) {
  return (
    <li className="checkout-line">
      <div className="checkout-line-image">
        <ImageFrame image={line.merchandise.image} altFallback={line.merchandise.product.title} />
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

function formValues(formData: FormData): Record<string, string> {
  const values: Record<string, string> = {};
  for (const [key, value] of formData.entries()) {
    if (typeof value === 'string') values[key] = value.trim();
  }
  return values;
}

/** Form defaults: the last submission, else the customer's profile and default address. */
function defaultValues(
  customer: Customer | null,
  submitted: Record<string, string> | undefined,
): Record<string, string | undefined> {
  if (submitted) return submitted;
  const address: Partial<MailingAddress> = customer?.defaultAddress ?? {};
  return {
    email: customer?.email ?? undefined,
    firstName: address.firstName ?? customer?.firstName ?? undefined,
    lastName: address.lastName ?? customer?.lastName ?? undefined,
    company: address.company ?? undefined,
    address1: address.address1 ?? undefined,
    address2: address.address2 ?? undefined,
    city: address.city ?? undefined,
    province: address.province ?? undefined,
    country: address.country ?? undefined,
    zip: address.zip ?? undefined,
    phone: address.phone ?? customer?.phone ?? undefined,
  };
}

/** Last path segment of each `CheckoutUserError.field`, e.g. `address1`. */
function errorsByField(errors: readonly CheckoutUserError[]): Record<string, string | undefined> {
  const byField: Record<string, string> = {};
  for (const error of errors) {
    const field = error.field?.at(-1);
    if (field && !(field in byField)) byField[field] = error.message;
  }
  return byField;
}

/**
 * Mirrors the backend's pricing: flat `taxRate` on the merchandise subtotal,
 * the chosen method's flat shipping price, waived at `freeShippingThreshold`.
 */
function computeTotals(
  cart: Cart,
  settings: CommerceSettings,
  shippingHandle: string,
): {
  readonly subtotal: Money;
  readonly shipping: Money;
  readonly tax: Money;
  readonly total: Money;
} {
  const currencyCode = cart.cost.subtotalAmount.currencyCode;
  const subtotal = toCents(cart.cost.subtotalAmount.amount);
  const method =
    settings.shippingMethods.find((entry) => entry.handle === shippingHandle) ??
    settings.shippingMethods[0];
  const threshold = settings.freeShippingThreshold;
  const shipping =
    method === undefined || (threshold !== null && subtotal >= toCents(threshold.amount))
      ? 0
      : toCents(method.price.amount);
  const tax = Math.round(subtotal * settings.taxRate);
  const money = (cents: number): Money => ({
    amount: (cents / 100).toFixed(2),
    currencyCode,
  });
  return {
    subtotal: money(subtotal),
    shipping: money(shipping),
    tax: money(tax),
    total: money(subtotal + shipping + tax),
  };
}

function toCents(amount: string): number {
  return Math.round(Number.parseFloat(amount) * 100);
}
