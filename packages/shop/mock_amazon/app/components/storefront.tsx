import { useEffect, useRef, useState } from 'react';
import { Form, Link, useLocation } from 'react-router';
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
  shop, menu, cart, customer, isCartOpen, onCartOpen,
}: {
  readonly shop: Shop;
  readonly menu: Menu | null;
  readonly cart: Cart | null;
  readonly customer: Customer | null;
  readonly isCartOpen: boolean;
  readonly onCartOpen: () => void;
}) {
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [locationOpen, setLocationOpen] = useState(false);
  const [localeOpen, setLocaleOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState(() => location.pathname === '/search' ? new URLSearchParams(location.search).get('q') ?? '' : '');
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const game = menu?.items[0];
  const gameLinks = game?.items ?? [];
  const inDepartment = (location.pathname === '/collections' || location.pathname.startsWith('/collections/video-games') || location.pathname.startsWith('/products/'));
  const accountPath = customer ? '/account' : '/account/login';
  useEffect(() => { setDrawerOpen(false); setSuggestionsOpen(false); }, [location.pathname, location.search]);
  const suggestions = [searchTerm, ...gameLinks.map(item => `${searchTerm} ${item.title.toLowerCase()}`)].slice(0,10);
  return (
    <header className="market-header site-header">
      <nav className="skip-navigation" aria-label="Keyboard shortcuts">
        <a href="#main-content">Skip to content</a><a href="#site-search">Search</a><Link to="/cart">Cart</Link><Link to="/">Home</Link><Link to="/account/orders">Orders</Link>
      </nav>
      <div className="masthead">
        <Link className="brand" to="/" aria-label={`${shop.name} home`}>{shop.name}<span className="brand-smile" aria-hidden="true" /></Link>
        <button type="button" className="header-location header-outline" onClick={() => setLocationOpen(true)}><span className="location-pin" aria-hidden="true">⌖</span><span><small>Deliver to</small><strong>United States</strong></span></button>
        <Form method="get" action="/search" className="header-search" role="search" id="site-search" onSubmit={() => setSuggestionsOpen(false)}>
          <label className="visually-hidden" htmlFor="search-scope">Search department</label>
          <select id="search-scope" name="department" defaultValue={inDepartment ? 'video-games' : ''} key={inDepartment ? 'games' : 'all'}><option value="">All</option>{menu?.items.map(item => <option key={item.id} value={item.url.split('/').pop()}>{item.title}</option>)}{gameLinks.map(item => <option key={item.id} value={item.url.split('/').pop()}>{item.title}</option>)}</select>
          <label className="visually-hidden" htmlFor="header-query">Search products</label>
          <input id="header-query" name="q" type="search" placeholder="Search products" autoComplete="off" value={searchTerm} onChange={event => {setSearchTerm(event.target.value);setSuggestionsOpen(event.target.value.trim().length > 0);}} onKeyDown={event => { if (event.key === 'Escape') setSuggestionsOpen(false); }} aria-expanded={suggestionsOpen} aria-controls="search-suggestions" />
          <button type="submit" aria-label="Search" className="search-submit"><span aria-hidden="true">⌕</span></button>
          {suggestionsOpen && <div id="search-suggestions" className="search-suggestions" role="listbox">{suggestions.map((suggestion,index) => <Link to={`/search?q=${encodeURIComponent(suggestion)}`} role="option" aria-selected={false} key={`${index}-${suggestion}`} onClick={() => setSuggestionsOpen(false)}><span aria-hidden="true">⌕</span><span>{searchTerm}<strong>{suggestion.slice(searchTerm.length)}</strong></span></Link>)}<span className="visually-hidden" role="status">{suggestions.length} suggestions for {searchTerm}</span></div>}
        </Form>
        <div className="locale-wrap"><button type="button" className="header-locale header-outline" aria-expanded={localeOpen} onClick={() => setLocaleOpen(!localeOpen)}><span aria-hidden="true">◎</span> EN <span className="mini-chevron">⌄</span></button>{localeOpen && <div className="locale-panel"><strong>Language & region</strong><Link to="/pages/help-center">English · United States · USD</Link></div>}</div>
        <div className="account-wrap header-outline"><Link className="account-link" aria-label={customer ? 'Account' : 'Log in'} to={accountPath}><small>{customer ? `Hello, ${customer.firstName || 'there'}` : 'Hello, sign in'}</small><strong><span className="account-desktop-label">Account & Lists</span><span className="account-mobile-label">{customer ? 'Account' : 'Sign in'}</span> <span className="mini-chevron">⌄</span></strong></Link><div className="account-flyout">{customer ? <Link className="button-link" to="/account">Your account</Link> : <><Link className="button-link" to="/account/login">Sign in</Link><p>New customer? <Link to="/account/register">Create your account</Link></p></>}<div className="flyout-columns"><div><strong>Your lists</strong><Link to="/account/login">Your lists</Link><Link to="/account/login">Your recommendations</Link></div><div><strong>Your account</strong><Link to={accountPath}>Your account</Link><Link to="/account/orders">Your orders</Link><Link to="/account/addresses">Your addresses</Link><Link to="/pages/help-center">Customer service</Link></div></div></div></div>
        <Link to="/account/orders" className="orders-link header-outline"><small>Returns</small><strong>& Orders</strong></Link>
        <button type="button" className="cart-toggle header-outline" aria-controls="cart-drawer" aria-expanded={isCartOpen} aria-haspopup="dialog" onClick={onCartOpen}><span className="cart-icon" aria-hidden="true">▰</span><span className="cart-count">{cart?.totalQuantity ?? 0}</span><strong>Cart</strong></button>
      </div>
      <nav className="market-nav" aria-label="Main navigation"><button type="button" className="all-menu-toggle" aria-expanded={drawerOpen} aria-controls="department-drawer" onClick={() => setDrawerOpen(true)}><span aria-hidden="true">☰</span> All</button><Link to="/collections">Today's Deals</Link>{menu?.items.map(item => <div className="nav-flyout-wrap" key={item.id}><Link to={item.url}>{item.title}</Link><div className="nav-flyout"><strong>Explore {item.title}</strong><div className="nav-flyout-links">{item.items.slice(0, 8).map(child => <Link to={child.url} key={child.id}>{child.title}</Link>)}</div><Link to={item.url}>Shop all {item.title} →</Link></div></div>)}<Link to="/collections">Best Sellers</Link><Link to="/collections">New Releases</Link><Link to="/collections">Gift Ideas</Link><Link to="/pages/help-center">Customer Service</Link><Link to="/account/login">Membership</Link></nav>
      {inDepartment && game && <nav className="department-nav" aria-label="Video Games department"><Link className="department-title" to={game.url}>{game.title}</Link>{gameLinks.filter((_, index) => [5, 7, 8, 9, 15, 18, 16, 14, 1].includes(index)).map(item => <Link to={item.url} key={item.id}>{item.title}</Link>)}</nav>}
      {drawerOpen && <div className="department-overlay"><button type="button" className="department-backdrop" aria-label="Close all categories" onClick={() => setDrawerOpen(false)} /><aside className="department-drawer" id="department-drawer" role="dialog" aria-modal="true" aria-label="All categories"><div className="drawer-login"><Link to={accountPath}>◉ &nbsp; Hello, {customer ? customer.firstName || 'there' : 'sign in'}</Link><button type="button" aria-label="Close menu" onClick={() => setDrawerOpen(false)}>×</button></div><div className="drawer-scroll"><h2>Trending</h2><Link to="/collections">Best Sellers</Link><Link to="/collections">New Releases</Link><h2>Digital content & devices</h2>{game && <Link to={game.url}>{game.title} <span>›</span></Link>}<h2>Shop by Department</h2>{gameLinks.map(item => <Link key={item.id} to={item.url}>{item.title}<span>›</span></Link>)}<h2>Programs & Features</h2><Link to="/collections">Today's Deals</Link><h2>Help & Settings</h2><Link to="/account">Your Account</Link><Link to="/pages/help-center">Customer Service</Link><Link to="/pages/help-center">English · United States</Link><Link to="/account/login">Sign in</Link></div></aside></div>}
      {locationOpen && <div className="location-overlay"><button type="button" className="department-backdrop" aria-label="Close location" onClick={() => setLocationOpen(false)} /><div className="location-dialog" role="dialog" aria-modal="true" aria-label="Choose your location"><div><strong>Choose your location</strong><button type="button" aria-label="Close location" onClick={() => setLocationOpen(false)}>×</button></div><p>Delivery options and availability depend on your location.</p><label>ZIP code<input inputMode="numeric" placeholder="Enter ZIP code" /></label><button type="button" onClick={() => setLocationOpen(false)}>Apply</button></div></div>}
    </header>
  );
}

export function Footer({ menu, headerMenu, policies, shop }: {
  readonly menu: Menu | null;
  readonly headerMenu: Menu | null;
  readonly policies: readonly Policy[];
  readonly shop?: Shop;
}) {
  const menuUrls = new Set(flattenMenuUrls(menu?.items ?? []));
  const policyLinks = policies.filter(policy => !menuUrls.has(policyPath(policy)));
  const footerItems = (menu?.items ?? []).filter((item, index, items) => items.findIndex(other => other.url === item.url) === index);
  const departmentItems = headerMenu?.items.flatMap(item => [item, ...item.items]) ?? [];
  return <footer className="market-footer site-footer">
    <button className="back-to-top" type="button" onClick={() => window.scrollTo({top: 0, behavior: 'smooth'})}>Back to top</button>
    <nav className="footer-main" aria-label="Footer navigation">
      <div className="footer-group"><h2>Get to Know Us</h2><Link to="/pages/about">About us</Link><Link to="/collections">Discover our store</Link><Link to="/pages/help-center">News & information</Link></div>
      <div className="footer-group"><h2>Make Money with Us</h2><Link to="/pages/help-center">Sell with us</Link><Link to="/pages/help-center">Partner programs</Link><Link to="/pages/help-center">Business services</Link></div>
      <div className="footer-group"><h2>Payment Products</h2><Link to="/pages/help-center">Payment options</Link><Link to="/pages/help-center">Gift cards & balance</Link><Link to="/pages/help-center">Shop with confidence</Link></div>
      <div className="footer-group"><h2>Let Us Help You</h2><Link to="/account">Your Account</Link><Link to="/account/orders">Your Orders</Link><Link to="/pages/shipping-policy">Shipping Rates & Policies</Link><Link to="/account/login">Returns & Replacements</Link><Link to="/pages/help-center">Help</Link></div>
    </nav>
    <div className="footer-locale"><Link className="footer-brand" to="/">{shop?.name ?? 'Home'}</Link><Link className="locale-pill" to="/pages/help-center">◎ &nbsp; English</Link><Link className="locale-pill" to="/pages/help-center">◉ &nbsp; United States · USD</Link></div>
    <nav className="footer-directory" aria-label="Explore departments and services"><div><h2>Shop departments</h2><Link to="/collections">All departments<span>Explore the catalog</span></Link>{footerItems.map(item => <StorefrontLink key={item.id} to={item.url}>{item.title}</StorefrontLink>)}</div><div><h2>Video games & more</h2>{departmentItems.map(item => <Link key={item.id} to={item.url}>{item.title}<span>Shop the collection</span></Link>)}{footerItems.flatMap(item => item.items).filter(item => !departmentItems.some(department => department.url === item.url)).map(item => <Link key={item.id} to={item.url}>{item.title}<span>Shop the collection</span></Link>)}</div><div><h2>Information & services</h2>{footerItems.map(item => <StorefrontLink key={item.id} to={item.url}>{item.title}</StorefrontLink>)}{policyLinks.map(policy => <Link key={policy.id} to={policyPath(policy)}>{policy.title}<span>Information</span></Link>)}</div></nav>
    <div className="footer-legal"><div><Link to="/policies/terms-of-service">Conditions of Use</Link><Link to="/policies/privacy-policy">Privacy Notice</Link><Link to="/pages/help-center">Consumer Privacy</Link><Link to="/pages/help-center">Your Privacy Choices</Link></div><small>© {new Date().getFullYear()} {shop?.name ?? 'Store'}. All rights reserved.</small></div>
  </footer>;
}

export function MenuList({ items }: { readonly items: Menu['items'] }) {
  if (items.length === 0) return null;
  return <ul className="menu-list">{items.map(item => <li key={item.id}><StorefrontLink to={item.url}>{item.title}</StorefrontLink><MenuList items={item.items} /></li>)}</ul>;
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

/** The variant title, or null for the "Default Title" of a product with one variant. */
export function variantTitle(title: string): string | null {
  return title === 'Default Title' ? null : title;
}

/**
 * The variant radios of the add form. A product whose only variant is the
 * "Default Title" one has nothing to choose: its variant id goes in a hidden
 * field and no picker shows.
 */
export function VariantChoices({
  variants,
}: {
  readonly variants: readonly ProductVariant[];
}) {
  if (variants.length === 0) return null;
  const [onlyVariant] = variants;
  if (variants.length === 1 && onlyVariant && variantTitle(onlyVariant.title) === null) {
    return <input type="hidden" name="merchandiseId" value={onlyVariant.id} />;
  }
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
            <div className="cart-popover-subtotal"><strong>Subtotal ({cart.totalQuantity} {cart.totalQuantity === 1 ? 'item' : 'items'}): <Price money={cart.cost.subtotalAmount} /></strong><span>✓ FREE delivery available</span></div>
            <Link className="button-link cart-popover-checkout" to="/checkout">Proceed to checkout</Link>
            <ul className="cart-lines">
              {cart.lines.nodes.map((line) => (
                <li key={line.id} className="cart-popover-line">
                  <Link className="cart-popover-media" to={`/products/${line.merchandise.product.handle}`}><ImageFrame image={line.merchandise.image} altFallback={line.merchandise.product.title} /></Link>
                  <div className="cart-popover-item">
                    <Link className="cart-popover-title" to={`/products/${line.merchandise.product.handle}`}>{line.merchandise.product.title}</Link>
                    {variantTitle(line.merchandise.title) && <span className="muted">{variantTitle(line.merchandise.title)}</span>}
                    <strong><Price money={line.cost.totalAmount} /></strong>
                    <div className="cart-popover-controls">
                      <Form method="post" action="/cart" reloadDocument>
                        <CartRedirectInput redirectTo={redirectTo} />
                        <input type="hidden" name="intent" value="update" />
                        <input type="hidden" name="lineId" value={line.id} />
                        <label>Quantity <input type="number" name="quantity" min="0" defaultValue={line.quantity} aria-label={`Quantity for ${line.merchandise.product.title}`} /></label>
                        <button type="submit">Update</button>
                      </Form>
                      <Form method="post" action="/cart" reloadDocument>
                        <CartRedirectInput redirectTo={redirectTo} />
                        <input type="hidden" name="intent" value="remove" />
                        <input type="hidden" name="lineId" value={line.id} />
                        <button className="secondary-button" type="submit">Remove</button>
                      </Form>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
            <Link className="cart-page-link" to="/cart">Go to Cart →</Link>
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
  const variant = variantTitle(line.merchandise.title);
  return (
    <li className="cart-line">
      <div className="cart-line-product">
        {line.merchandise.image && <Link className="cart-line-media" to={`/products/${line.merchandise.product.handle}`}><ImageFrame image={line.merchandise.image} altFallback={line.merchandise.product.title} /></Link>}
        <Link to={`/products/${line.merchandise.product.handle}`}>
          {line.merchandise.product.title}
        </Link>
        {variant ? <p className="muted">{variant}</p> : null}
        <p className="cart-stock">In stock · FREE delivery available</p>
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
      {cart.cost.totalTaxAmount ? (
        <div className="cart-total-row">
          <span>Estimated tax</span>
          <Price money={cart.cost.totalTaxAmount} />
        </div>
      ) : null}
      <div className="cart-total-row cart-total-row-grand">
        <span>Total</span>
        <Price money={cart.cost.totalAmount} />
      </div>
      <p className="cart-delivery">✓ FREE delivery available</p>
      <label className="cart-gift"><input type="checkbox" /> This order contains a gift</label>
      <Link className="button-link" to="/checkout">
        Proceed to checkout
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
