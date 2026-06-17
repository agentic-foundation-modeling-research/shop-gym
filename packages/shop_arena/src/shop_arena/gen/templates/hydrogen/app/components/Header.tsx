import {Suspense} from 'react';
import {Await, NavLink, useAsyncValue} from 'react-router';
import {
  type CartViewPayload,
  useAnalytics,
  useOptimisticCart,
} from '@shopify/hydrogen';
import type {HeaderQuery, CartApiQueryFragment} from 'storefrontapi.generated';
import {useAside} from '~/components/Aside';
import {HeaderShell} from '~/components/HeaderShell';
import {NavMenu} from '~/components/NavMenu';

interface HeaderProps {
  header: HeaderQuery;
  cart: Promise<CartApiQueryFragment | null>;
  isLoggedIn: Promise<boolean>;
  publicStoreDomain: string;
}

export function Header({
  header,
  isLoggedIn,
  cart,
  publicStoreDomain,
}: HeaderProps) {
  const {shop, menu} = header;
  const primaryDomainUrl = shop.primaryDomain?.url ?? '';

  return (
    <HeaderShell
      brand={
        <NavLink
          prefetch="intent"
          to="/"
          end
          className="header-brand"
          aria-label={shop.name}
        >
          <strong>{shop.name}</strong>
        </NavLink>
      }
      primary={
        <nav className="header-nav" aria-label="Main Menu">
          <NavMenu
            menu={menu}
            viewport="desktop"
            primaryDomainUrl={primaryDomainUrl}
            publicStoreDomain={publicStoreDomain}
            linkClassName="header-nav-link"
            triggerClassName="header-nav-link header-nav-trigger"
          />
        </nav>
      }
      ctas={
        <>
          <HeaderMenuMobileToggle />
          <AccountLink isLoggedIn={isLoggedIn} />
          <SearchToggle />
          <CartToggle cart={cart} />
        </>
      }
    />
  );
}

function HeaderMenuMobileToggle() {
  const {open} = useAside();
  return (
    <button
      type="button"
      className="header-menu-mobile-toggle reset"
      aria-label="Open menu"
      onClick={() => open('mobile')}
    >
      <span aria-hidden="true">☰</span>
    </button>
  );
}

function AccountLink({isLoggedIn}: Pick<HeaderProps, 'isLoggedIn'>) {
  return (
    <NavLink prefetch="intent" to="/account" className="header-cta">
      <Suspense fallback="Sign in">
        <Await resolve={isLoggedIn} errorElement="Sign in">
          {(loggedIn) => (loggedIn ? 'Account' : 'Sign in')}
        </Await>
      </Suspense>
    </NavLink>
  );
}

function SearchToggle() {
  const {open} = useAside();
  return (
    <button
      type="button"
      className="header-cta reset"
      onClick={() => open('search')}
    >
      Search
    </button>
  );
}

function CartBadge({count}: {count: number}) {
  const {open} = useAside();
  const {publish, shop, cart, prevCart} = useAnalytics();

  return (
    <a
      href="/cart"
      className="header-cta"
      onClick={(event) => {
        event.preventDefault();
        open('cart');
        publish('cart_viewed', {
          cart,
          prevCart,
          shop,
          url: window.location.href || '',
        } as CartViewPayload);
      }}
    >
      Cart <span aria-label={`(items: ${count})`}>{count}</span>
    </a>
  );
}

function CartToggle({cart}: Pick<HeaderProps, 'cart'>) {
  return (
    <Suspense fallback={<CartBadge count={0} />}>
      <Await resolve={cart}>
        <CartBanner />
      </Await>
    </Suspense>
  );
}

function CartBanner() {
  const originalCart = useAsyncValue() as CartApiQueryFragment | null;
  const cart = useOptimisticCart(originalCart);
  return <CartBadge count={cart?.totalQuantity ?? 0} />;
}
