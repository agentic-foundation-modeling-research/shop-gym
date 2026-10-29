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
import { FormErrors } from '~/components/account';
import {
  CheckoutSummary,
  ShippingPrice,
  type SummaryTotals,
  variantTitle,
} from '~/components/checkout';
import { DiscountCodeForm, appliedCartDiscount } from '~/components/storefront';
import { ADDRESS_FIELDS } from '~/lib/addresses';
import { clearCartId, getAppContext, getCartId, getCustomerAccessToken } from '~/lib/context';
import { loadCustomer } from '~/lib/customer';
import { applyDiscountCode, removeDiscountCode } from '~/lib/discount';
import {
  CART_BUYER_IDENTITY_UPDATE_MUTATION,
  CART_QUERY,
  CHECKOUT_COMPLETE_MUTATION,
  COMMERCE_SETTINGS_QUERY,
} from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type {
  Cart,
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

/** A "Pay now" that did not place the order: the errors and the submitted values. */
interface PaymentRejectedData {
  readonly intent: 'pay';
  readonly errors: readonly CheckoutUserError[];
  readonly values: Record<string, string>;
}

/** A "Discount code" submission: whether the code was turned down. */
interface DiscountActionData {
  readonly intent: 'discount';
  readonly discountRejected: boolean;
}

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
  const intent = formData.get('intent');
  if (intent === 'discount') {
    const code = formData.get('discountCode');
    const applied = await applyDiscountCode(
      appContext,
      cartId,
      typeof code === 'string' ? code : '',
    );
    return { intent: 'discount', discountRejected: !applied } satisfies DiscountActionData;
  }
  if (intent === 'discount-remove') {
    await removeDiscountCode(appContext, cartId);
    return { intent: 'discount', discountRejected: false } satisfies DiscountActionData;
  }

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
    return { intent: 'pay', errors: userErrors, values } satisfies PaymentRejectedData;
  }
  return redirect(`/checkout/confirmation/${order.orderNumber}`, {
    headers: await clearCartId(appContext),
  });
}

export default function CheckoutRoute() {
  const { cart, settings, customer } = useLoaderData<typeof loader>();
  const actionData = useActionData<typeof action>();
  const payment = actionData?.intent === 'pay' ? actionData : undefined;
  const discountRejected = actionData?.intent === 'discount' && actionData.discountRejected;
  const [shippingHandle, setShippingHandle] = useState(
    payment?.values.shippingMethodHandle ?? settings.shippingMethods[0]?.handle ?? '',
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

  const defaults = defaultValues(customer, payment?.values);
  const fieldErrors = errorsByField(payment?.errors ?? []);
  const totals = computeTotals(cart, settings, shippingHandle);
  const shippingWaived = isShippingWaived(cart, settings);

  return (
    <div className="page-width checkout-page">
      <CheckoutSummary
        lines={cart.lines.nodes.map((line) => ({
          key: line.id,
          image: line.merchandise.image,
          quantity: line.quantity,
          title: line.merchandise.product.title,
          variantTitle: variantTitle(line.merchandise.title),
          price: line.cost.totalAmount,
        }))}
        totals={totals}
      >
        <DiscountCodeForm action="/checkout" cart={cart} rejected={discountRejected} />
      </CheckoutSummary>
      <Form method="post" className="stack checkout-form" aria-labelledby="checkout-heading">
        <h1 id="checkout-heading">Checkout</h1>
        <FormErrors errors={payment?.errors} />
        <fieldset className="form-grid">
          <legend>Contact</legend>
          {customer ? null : (
            <Link className="checkout-login" to="/account/login?redirectTo=%2Fcheckout">
              Log in
            </Link>
          )}
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
          <legend>Delivery</legend>
          <Field
            label="Country"
            name="country"
            autoComplete="country-name"
            required
            defaultValue={defaults.country}
            error={fieldErrors.country}
          />
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
                {shippingWaived ? 'Free' : <ShippingPrice money={method.price} />}
              </span>
            </label>
          ))}
          <FieldError message={fieldErrors.shippingMethodHandle} />
        </fieldset>
        <fieldset className="choice-list">
          <legend>Payment</legend>
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
          <button type="submit">Pay now</button>
        </div>
      </Form>
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
 * Checkout totals. The cart cost already has the Discount code and the tax;
 * shipping mirrors the backend: the chosen method's flat price, waived at
 * `freeShippingThreshold` (on the subtotal before the discount) or by a
 * free-shipping code.
 */
function computeTotals(
  cart: Cart,
  settings: CommerceSettings,
  shippingHandle: string,
): SummaryTotals {
  const currencyCode = cart.cost.subtotalAmount.currencyCode;
  const method =
    settings.shippingMethods.find((entry) => entry.handle === shippingHandle) ??
    settings.shippingMethods[0];
  const shipping =
    method === undefined || isShippingWaived(cart, settings) ? 0 : toCents(method.price.amount);
  const money = (cents: number): Money => ({
    amount: (cents / 100).toFixed(2),
    currencyCode,
  });
  return {
    subtotal: cart.cost.subtotalAmount,
    discount: appliedCartDiscount(cart),
    shipping: money(shipping),
    taxes: cart.cost.totalTaxAmount ?? money(0),
    total: money(toCents(cart.cost.totalAmount.amount) + shipping),
  };
}

/**
 * Whether every shipping method is free: the subtotal reaches the threshold,
 * or a free-shipping code applies.
 */
function isShippingWaived(cart: Cart, settings: CommerceSettings): boolean {
  const threshold = settings.freeShippingThreshold;
  return (
    (threshold !== null && toCents(cart.cost.subtotalAmount.amount) >= toCents(threshold.amount)) ||
    appliedCartDiscount(cart)?.targetType === 'SHIPPING_LINE'
  );
}

function toCents(amount: string): number {
  return Math.round(Number.parseFloat(amount) * 100);
}
