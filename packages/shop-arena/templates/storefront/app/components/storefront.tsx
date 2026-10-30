import { useEffect, useRef, useState } from 'react';
import { Form, Link } from 'react-router';
import type {
  AppliedDiscount,
  Cart,
  CartLine,
  CollectionSummary,
  Customer,
  Image,
  Menu,
  Money,
  Policy,
  ProductSummary,
  ProductVariant,
  Shop,
} from '~/lib/types';

/** Shown under the "Discount code" field when a code does not apply. */
const INVALID_DISCOUNT_CODE_MESSAGE = 'Enter a valid discount code';

export function Header({
  shop,
  menu,
  cart,
  customer,
  isCartOpen,
  onCartOpen,
}: {
  readonly shop: Shop;
  readonly menu: Menu | null;
  readonly cart: Cart | null;
  readonly customer: Customer | null;
  readonly isCartOpen: boolean;
  readonly onCartOpen: () => void;
}) {
  return (
    <header className="site-header">
      <Link className="brand" to="/">
        {shop.name}
      </Link>
      <nav aria-label="Main navigation">
        <MenuList items={menu?.items ?? []} />
      </nav>
      <Link className="account-link" to={customer ? '/account' : '/account/login'}>
        {customer ? 'Account' : 'Log in'}
      </Link>
      <button
        type="button"
        className="cart-toggle"
        aria-controls="cart-drawer"
        aria-expanded={isCartOpen}
        aria-haspopup="dialog"
        onClick={onCartOpen}
      >
        Cart ({cart?.totalQuantity ?? 0})
      </button>
    </header>
  );
}

export function Footer({
  menu,
  policies,
}: {
  readonly menu: Menu | null;
  readonly policies: readonly Policy[];
}) {
  const menuUrls = new Set(flattenMenuUrls(menu?.items ?? []));
  const policyLinks = policies.filter((policy) => !menuUrls.has(policyPath(policy)));
  return (
    <footer className="site-footer">
      <nav aria-label="Footer navigation">
        <MenuList items={menu?.items ?? []} />
        {policyLinks.length > 0 ? (
          <ul className="menu-list">
            {policyLinks.map((policy) => (
              <li key={policy.id}>
                <Link to={policyPath(policy)}>{policy.title}</Link>
              </li>
            ))}
          </ul>
        ) : null}
      </nav>
    </footer>
  );
}

export function MenuList({ items }: { readonly items: Menu['items'] }) {
  if (items.length === 0) return null;
  return (
    <ul className="menu-list">
      {items.map((item) => (
        <li key={item.id}>
          <StorefrontLink to={item.url}>{item.title}</StorefrontLink>
          <MenuList items={item.items} />
        </li>
      ))}
    </ul>
  );
}

export function Price({
  money,
  currencyDisplay = 'symbol',
}: {
  readonly money: Money;
  /** `narrowSymbol` drops the country from the symbol: "$19.99", not "CA$19.99". */
  readonly currencyDisplay?: 'symbol' | 'narrowSymbol';
}) {
  const amount = Number.parseFloat(money.amount);
  const displayAmount = Number.isFinite(amount) ? amount : money.amount;
  return (
    <span>
      {typeof displayAmount === 'number'
        ? new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: money.currencyCode,
            currencyDisplay,
          }).format(displayAmount)
        : `${displayAmount} ${money.currencyCode}`}
    </span>
  );
}

export function ProductGrid({
  products,
}: {
  readonly products: readonly ProductSummary[];
}) {
  if (products.length === 0) {
    return <p>No products found.</p>;
  }
  return (
    <ul className="product-grid">
      {products.map((product) => (
        <li key={product.id}>
          <ProductCard product={product} />
        </li>
      ))}
    </ul>
  );
}

export function ProductCard({ product }: { readonly product: ProductSummary }) {
  return (
    <article className="product-card">
      <Link className="product-card-link" to={`/products/${product.handle}`}>
        <ImageFrame image={product.featuredImage} altFallback={product.title} />
        <h3>{product.title}</h3>
      </Link>
      <p className="muted">{product.vendor}</p>
      <p>
        <Price money={product.priceRange.minVariantPrice} />
      </p>
    </article>
  );
}

export function CollectionGrid({
  collections,
}: {
  readonly collections: readonly CollectionSummary[];
}) {
  if (collections.length === 0) {
    return <p>No collections found.</p>;
  }
  return (
    <ul className="collection-grid">
      {collections.map((collection) => (
        <li key={collection.id}>
          <article className="collection-card">
            <Link to={`/collections/${collection.handle}`}>
              <ImageFrame image={collection.image} altFallback={collection.title} />
              <h3>{collection.title}</h3>
            </Link>
            <p>{collection.description}</p>
          </article>
        </li>
      ))}
    </ul>
  );
}

export function ImageFrame({
  image,
  altFallback,
}: {
  readonly image: Image | null;
  readonly altFallback: string;
}) {
  if (!image) {
    return (
      <div
        className="image-placeholder"
        role="img"
        aria-label={`Image unavailable for ${altFallback}`}
      >
        <span>{altFallback}</span>
      </div>
    );
  }
  return (
    <img
      className="image-frame-media"
      src={image.url}
      alt={image.altText ?? altFallback}
      width={image.width ?? undefined}
      height={image.height ?? undefined}
      loading="lazy"
    />
  );
}

export function ProductImageGallery({
  images,
  fallbackImage,
  title,
}: {
  readonly images: readonly (Image | null)[];
  readonly fallbackImage: Image | null;
  readonly title: string;
}) {
  const galleryImages = images.filter((image): image is Image => image !== null);
  const usableImages =
    galleryImages.length > 0 ? galleryImages : fallbackImage === null ? [] : [fallbackImage];
  const [selectedIndex, setSelectedIndex] = useState(0);
  const selectedImage = usableImages[selectedIndex] ?? usableImages[0] ?? null;

  return (
    <section className="product-gallery" aria-label={`${title} images`}>
      <ImageFrame image={selectedImage} altFallback={title} />
      {usableImages.length > 1 ? (
        <div className="product-gallery-thumbnails" aria-label="Choose image">
          {usableImages.map((image, index) => (
            <button
              type="button"
              className="product-gallery-thumbnail"
              aria-pressed={index === selectedIndex}
              aria-label={`Show image ${index + 1} for ${title}`}
              key={image.id ?? image.url}
              onClick={() => setSelectedIndex(index)}
            >
              <ImageFrame image={image} altFallback={`${title} ${index + 1}`} />
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function VariantChoices({
  variants,
}: {
  readonly variants: readonly ProductVariant[];
}) {
  if (variants.length === 0) return null;
  const selectedVariant = variants.find((variant) => variant.availableForSale) ?? variants[0];
  return (
    <fieldset className="variant-choices">
      <legend>Variant</legend>
      <div className="variant-choice-list">
        {variants.map((variant) => (
          <label className="variant-choice" key={variant.id}>
            <input
              type="radio"
              name="merchandiseId"
              value={variant.id}
              required
              disabled={!variant.availableForSale}
              defaultChecked={variant.id === selectedVariant?.id}
            />
            <span>{variant.title}</span>
            <span className="variant-price">{formatMoney(variant.price)}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function CartDrawer({
  cart,
  isOpen,
  onClose,
  redirectTo,
}: {
  readonly cart: Cart | null;
  readonly isOpen: boolean;
  readonly onClose: () => void;
  readonly redirectTo: string;
}) {
  const hasLines = (cart?.lines.nodes.length ?? 0) > 0;
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const activeElement = document.activeElement;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose();
      }
    }

    closeButtonRef.current?.focus({ preventScroll: true });
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      if (activeElement instanceof HTMLElement) {
        activeElement.focus({ preventScroll: true });
      }
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="cart-popup">
      <button
        type="button"
        className="cart-backdrop"
        aria-label="Close cart drawer"
        onClick={onClose}
      />
      <aside
        id="cart-drawer"
        className="cart-drawer"
        // biome-ignore lint/a11y/useSemanticElements: drawer rendered during SSR; <dialog> needs showModal()
        role="dialog"
        aria-modal="true"
        aria-labelledby="cart-drawer-title"
      >
        <div className="cart-drawer-header">
          <h2 id="cart-drawer-title">Cart</h2>
          <button type="button" className="secondary-button" ref={closeButtonRef} onClick={onClose}>
            Close
          </button>
        </div>
        {hasLines && cart ? (
          <div className="cart-drawer-body">
            <ul className="cart-lines">
              {cart.lines.nodes.map((line) => (
                <CartLineItem key={line.id} line={line} redirectTo={redirectTo} />
              ))}
            </ul>
            <CartSummary cart={cart} layout="drawer" redirectTo={redirectTo} />
            <Link className="cart-page-link" to="/cart">
              View cart page
            </Link>
          </div>
        ) : (
          <div className="stack">
            <p>Your cart is empty.</p>
            <Link to="/collections">Browse collections</Link>
          </div>
        )}
      </aside>
    </div>
  );
}

export function CartLineItem({
  line,
  redirectTo,
}: {
  readonly line: CartLine;
  readonly redirectTo?: string | undefined;
}) {
  return (
    <li className="cart-line">
      <div className="cart-line-product">
        <Link to={`/products/${line.merchandise.product.handle}`}>
          {line.merchandise.product.title}
        </Link>
        <p className="muted">{line.merchandise.title}</p>
      </div>
      <div className="cart-line-actions">
        <Form method="post" action="/cart" className="cart-line-update" reloadDocument>
          <CartRedirectInput redirectTo={redirectTo} />
          <input type="hidden" name="intent" value="update" />
          <input type="hidden" name="lineId" value={line.id} />
          <label>
            Quantity
            <input
              type="number"
              name="quantity"
              min="0"
              defaultValue={line.quantity}
              aria-label={`Quantity for ${line.merchandise.product.title}`}
            />
          </label>
          <button type="submit">Update</button>
        </Form>
        <Form method="post" action="/cart" reloadDocument>
          <CartRedirectInput redirectTo={redirectTo} />
          <input type="hidden" name="intent" value="remove" />
          <input type="hidden" name="lineId" value={line.id} />
          <button className="secondary-button" type="submit">
            Remove
          </button>
        </Form>
      </div>
      <p className="cart-line-price">
        <Price money={line.cost.totalAmount} />
      </p>
    </li>
  );
}

export function CartSummary({
  cart,
  layout,
  redirectTo,
  discountRejected = false,
}: {
  readonly cart: Cart;
  readonly layout: 'page' | 'drawer';
  readonly redirectTo?: string | undefined;
  /** True right after the cart action turned down a code. */
  readonly discountRejected?: boolean;
}) {
  const discount = appliedCartDiscount(cart);
  return (
    <section className={`cart-summary cart-summary-${layout}`} aria-label="Cart summary">
      <div className="cart-total-row">
        <span>Subtotal</span>
        <Price money={cart.cost.subtotalAmount} />
      </div>
      {discount ? <DiscountRow discount={discount} /> : null}
      <div className="cart-total-row cart-total-row-grand">
        <span>Total</span>
        <Price money={cart.cost.totalAmount} />
      </div>
      <DiscountCodeForm
        action="/cart"
        cart={cart}
        rejected={discountRejected}
        reloadDocument
        redirectTo={redirectTo}
      />
      <Link className="button-link" to="/checkout">
        Continue to checkout
      </Link>
    </section>
  );
}

export function appliedCartDiscount(cart: Cart): AppliedDiscount | null {
  const allocation = cart.discountAllocations[0];
  if (allocation === undefined) return null;
  return {
    code: allocation.code,
    targetType: allocation.targetType,
    amount: allocation.discountedAmount,
  };
}

/** The "Discount" totals row: the code, then the amount as a negative or "Free shipping". */
export function DiscountRow({ discount }: { readonly discount: AppliedDiscount }) {
  return (
    <div className="cart-total-row">
      <span>Discount</span>
      <DiscountAmount discount={discount} />
    </div>
  );
}

/** The code, then the amount as a negative, or "Free shipping" for a free-shipping code. */
export function DiscountAmount({
  discount,
  currencyDisplay = 'symbol',
}: {
  readonly discount: AppliedDiscount;
  readonly currencyDisplay?: 'symbol' | 'narrowSymbol';
}) {
  return (
    <span>
      <span className="discount-row-code">{discount.code}</span>{' '}
      {discount.targetType === 'SHIPPING_LINE' ? (
        'Free shipping'
      ) : (
        <>
          -<Price money={discount.amount} currencyDisplay={currencyDisplay} />
        </>
      )}
    </span>
  );
}

/**
 * The "Discount code" field with "Apply", then the error, then a tag for the
 * code the cart holds. The tag stays when the code stops applying, and the
 * error then shows too.
 */
export function DiscountCodeForm({
  action,
  cart,
  rejected,
  reloadDocument = false,
  redirectTo,
}: {
  readonly action: '/cart' | '/checkout';
  readonly cart: Cart;
  /** True right after the action turned down a code. */
  readonly rejected: boolean;
  readonly reloadDocument?: boolean;
  readonly redirectTo?: string | undefined;
}) {
  const heldCode = cart.discountCodes[0];
  const showError = rejected || (heldCode !== undefined && !heldCode.applicable);
  return (
    <div className="discount-code">
      <Form
        method="post"
        action={action}
        className="discount-code-form"
        reloadDocument={reloadDocument}
      >
        <CartRedirectInput redirectTo={redirectTo} />
        <input type="hidden" name="intent" value="discount" />
        <label>
          Discount code
          <input
            // A new held code clears the field; a rejected code stays for the customer to fix.
            key={heldCode?.code ?? ''}
            name="discountCode"
            autoComplete="off"
            required
            aria-invalid={showError ? true : undefined}
          />
        </label>
        <button type="submit">Apply</button>
      </Form>
      {showError ? (
        <p className="field-error" role="alert">
          {INVALID_DISCOUNT_CODE_MESSAGE}
        </p>
      ) : null}
      {heldCode ? (
        <Form
          method="post"
          action={action}
          className="discount-tag"
          reloadDocument={reloadDocument}
        >
          <CartRedirectInput redirectTo={redirectTo} />
          <input type="hidden" name="intent" value="discount-remove" />
          <span>{heldCode.code}</span>
          <button
            type="submit"
            className="text-button"
            aria-label={`Remove discount code ${heldCode.code}`}
          >
            ×
          </button>
        </Form>
      ) : null}
    </div>
  );
}

function CartRedirectInput({
  redirectTo,
}: {
  readonly redirectTo?: string | undefined;
}) {
  if (!redirectTo) return null;
  return <input type="hidden" name="redirectTo" value={redirectTo} />;
}

function StorefrontLink({
  to,
  children,
}: {
  readonly to: string;
  readonly children: string;
}) {
  if (to.startsWith('/')) return <Link to={to}>{children}</Link>;
  return <a href={to}>{children}</a>;
}

function flattenMenuUrls(items: readonly Menu['items'][number][]): string[] {
  return items.flatMap((item) => [item.url, ...flattenMenuUrls(item.items)]);
}

function policyPath(policy: Policy): string {
  return `/policies/${policy.handle}`;
}

function formatMoney(money: Money): string {
  const amount = Number.parseFloat(money.amount);
  if (!Number.isFinite(amount)) return `${money.amount} ${money.currencyCode}`;
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: money.currencyCode,
  }).format(amount);
}
