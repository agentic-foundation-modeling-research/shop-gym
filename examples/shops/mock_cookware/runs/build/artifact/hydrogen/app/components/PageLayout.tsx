import {Await, useLocation, useNavigate} from 'react-router';
import {Suspense, useEffect} from 'react';
import type {
  CartApiQueryFragment,
  FooterQuery,
  HeaderQuery,
} from 'storefrontapi.generated';
import {Aside, useAside} from '~/components/Aside';
import {Footer} from '~/components/Footer';
import {Header} from '~/components/Header';
import {MobileNav} from '~/components/MobileNav';
import {CartMain} from '~/components/CartMain';
import {SearchFormPredictive} from '~/components/SearchFormPredictive';
import {CookieConsentBanner} from '~/components/CookieConsentBanner';
import {PromoPopup} from '~/components/PromoPopup';

interface PageLayoutProps {
  cart: Promise<CartApiQueryFragment | null>;
  footer: Promise<FooterQuery | null>;
  header: HeaderQuery;
  isLoggedIn: Promise<boolean>;
  publicStoreDomain: string;
  children?: React.ReactNode;
}

export function PageLayout({
  cart,
  children = null,
  footer,
  header,
  isLoggedIn,
  publicStoreDomain,
}: PageLayoutProps) {
  return (
    <Aside.Provider>
      <CartUrlOpener />
      <CartAside cart={cart} />
      <SearchAside />
      <MobileMenuAside header={header} publicStoreDomain={publicStoreDomain} />
      {header && (
        <Header
          header={header}
          cart={cart}
          isLoggedIn={isLoggedIn}
          publicStoreDomain={publicStoreDomain}
        />
      )}
      <main>{children}</main>
      <Footer
        footer={footer}
        header={header}
        publicStoreDomain={publicStoreDomain}
      />
      <CookieConsentBanner />
      <PromoPopup />
    </Aside.Provider>
  );
}

function CartUrlOpener() {
  const {open} = useAside();
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('cart') === 'open') {
      open('cart');
      params.delete('cart');
      const search = params.toString();
      void navigate(
        {pathname: location.pathname, search: search ? `?${search}` : ''},
        {replace: true},
      );
    }
  }, [location.search, location.pathname, open, navigate]);
  return null;
}

function CartAside({cart}: {cart: PageLayoutProps['cart']}) {
  return (
    <Aside type="cart" heading="Your Cart">
      <Suspense fallback={<p className="cart-loading">Loading cart…</p>}>
        <Await resolve={cart}>
          {(resolvedCart) => (
            <CartMain cart={resolvedCart} layout="aside" />
          )}
        </Await>
      </Suspense>
    </Aside>
  );
}

function SearchAside() {
  return (
    <Aside type="search" heading="Search">
      <div className="mobile-search">
        <SearchFormPredictive className="mobile-search-form">
          {({inputRef, goToSearch}) => (
            <>
              <input
                ref={inputRef}
                name="q"
                type="search"
                placeholder="Search products"
                aria-label="Search products"
                className="mobile-search-input"
                autoComplete="off"
              />
              <button
                type="submit"
                className="mobile-search-submit"
                onClick={() => goToSearch()}
                aria-label="Submit search"
              >
                Search
              </button>
            </>
          )}
        </SearchFormPredictive>
        <p className="mobile-search-hint">
          Press Enter to see all matching products.
        </p>
      </div>
    </Aside>
  );
}

function MobileMenuAside({
  header,
}: {
  header: PageLayoutProps['header'];
  publicStoreDomain: PageLayoutProps['publicStoreDomain'];
}) {
  return (
    <Aside type="mobile" heading={header?.shop?.name ?? 'Menu'}>
      <MobileNav />
    </Aside>
  );
}
