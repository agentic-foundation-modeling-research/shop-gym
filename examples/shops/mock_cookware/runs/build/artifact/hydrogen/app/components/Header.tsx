import {Suspense, useEffect, useRef, useState} from 'react';
import {Await, Link, NavLink, useAsyncValue, useLocation} from 'react-router';
import {
  type CartViewPayload,
  useAnalytics,
  useOptimisticCart,
} from '@shopify/hydrogen';
import type {HeaderQuery, CartApiQueryFragment} from 'storefrontapi.generated';
import {useAside} from '~/components/Aside';
import {AnnouncementBar} from '~/components/AnnouncementBar';
import {FlyoutPanel, MegaPanel} from '~/components/MegaMenu';
import {HeaderSearch} from '~/components/HeaderSearch';
import {PRIMARY_NAV, UTILITY_LINKS, type NavEntry} from './navigation';

interface HeaderProps {
  header: HeaderQuery;
  cart: Promise<CartApiQueryFragment | null>;
  isLoggedIn: Promise<boolean>;
  publicStoreDomain: string;
}

export function Header({header, isLoggedIn, cart}: HeaderProps) {
  const {shop} = header;
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const navRef = useRef<HTMLDivElement | null>(null);
  const location = useLocation();

  useEffect(() => {
    setOpenIndex(null);
  }, [location.pathname]);

  useEffect(() => {
    if (openIndex === null) return;
    function handleClick(e: MouseEvent) {
      if (navRef.current && !navRef.current.contains(e.target as Node)) {
        setOpenIndex(null);
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpenIndex(null);
    }
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [openIndex]);

  const close = () => setOpenIndex(null);

  return (
    <div className="site-header" ref={navRef}>
      <AnnouncementBar />
      <header className="header">
        <div className="header-row header-row-utility">
          <ul className="header-utility-links" aria-label="Editorial">
            {UTILITY_LINKS.map((link) => (
              <li key={link.label}>
                <NavLink to={link.url} prefetch="intent" className="utility-link">
                  {link.label}
                </NavLink>
              </li>
            ))}
          </ul>
          <Link to="/" prefetch="intent" className="header-logo" aria-label={shop.name}>
            <span className="header-wordmark">{shop.name}</span>
          </Link>
          <div className="header-ctas">
            <HeaderSearch />
            <SearchToggle />
            <AccountLink isLoggedIn={isLoggedIn} />
            <CartToggle cart={cart} />
            <MobileMenuToggle />
          </div>
        </div>
        <nav
          className="header-row header-row-primary"
          aria-label="Primary navigation"
        >
          <ul className="primary-nav">
            {PRIMARY_NAV.map((entry, i) => (
              <PrimaryNavItem
                key={entry.label}
                entry={entry}
                isOpen={openIndex === i}
                onClose={close}
                onToggle={() =>
                  setOpenIndex((cur) => (cur === i ? null : i))
                }
              />
            ))}
          </ul>
        </nav>
      </header>
    </div>
  );
}

function PrimaryNavItem({
  entry,
  isOpen,
  onClose,
  onToggle,
}: {
  entry: NavEntry;
  isOpen: boolean;
  onClose: () => void;
  onToggle: () => void;
}) {
  if (entry.kind === 'link') {
    return (
      <li className="primary-nav-item">
        <NavLink
          to={entry.url}
          prefetch="intent"
          className="primary-nav-link"
        >
          {entry.label}
        </NavLink>
      </li>
    );
  }

  return (
    <li
      className={`primary-nav-item primary-nav-item-trigger${isOpen ? ' is-open' : ''}`}
    >
      <button
        type="button"
        className="primary-nav-trigger"
        aria-expanded={isOpen}
        aria-haspopup="true"
        onClick={onToggle}
      >
        {entry.label}
        <span className="primary-nav-chevron" aria-hidden="true">
          ▾
        </span>
      </button>
      {isOpen && entry.kind === 'flyout' && (
        <FlyoutPanel entry={entry} onClose={onClose} />
      )}
      {isOpen && entry.kind === 'mega' && (
        <MegaPanel entry={entry} onClose={onClose} />
      )}
    </li>
  );
}

function MobileMenuToggle() {
  const {open} = useAside();
  return (
    <button
      type="button"
      className="header-icon-button mobile-menu-toggle"
      onClick={() => open('mobile')}
      aria-label="Open menu"
    >
      <svg
        viewBox="0 0 24 24"
        width="22"
        height="22"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        aria-hidden="true"
      >
        <path d="M4 7h16M4 12h16M4 17h16" />
      </svg>
    </button>
  );
}

function SearchToggle() {
  const {open} = useAside();
  return (
    <button
      type="button"
      className="header-icon-button"
      onClick={() => open('search')}
      aria-label="Search"
    >
      <svg
        viewBox="0 0 24 24"
        width="20"
        height="20"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <circle cx="11" cy="11" r="7" />
        <path d="M21 21l-4.3-4.3" />
      </svg>
    </button>
  );
}

function AccountLink({isLoggedIn}: {isLoggedIn: HeaderProps['isLoggedIn']}) {
  return (
    <NavLink
      prefetch="intent"
      to="/account"
      className="header-icon-button"
      aria-label="Account"
    >
      <Suspense fallback={<AccountIcon />}>
        <Await resolve={isLoggedIn} errorElement={<AccountIcon />}>
          {() => <AccountIcon />}
        </Await>
      </Suspense>
    </NavLink>
  );
}

function AccountIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" />
    </svg>
  );
}

function CartBadge({count}: {count: number}) {
  const {open} = useAside();
  const {publish, shop, cart, prevCart} = useAnalytics();

  return (
    <a
      href="/cart"
      className="header-icon-button header-cart-button"
      aria-label={`Cart, ${count} item${count === 1 ? '' : 's'}`}
      onClick={(e) => {
        e.preventDefault();
        open('cart');
        publish('cart_viewed', {
          cart,
          prevCart,
          shop,
          url: window.location.href || '',
        } as CartViewPayload);
      }}
    >
      <svg
        viewBox="0 0 24 24"
        width="20"
        height="20"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M6 7h13l-1.5 9a2 2 0 0 1-2 1.7H9.5A2 2 0 0 1 7.5 16L6 7z" />
        <path d="M9 7a3 3 0 0 1 6 0" />
      </svg>
      {count > 0 && <span className="header-cart-badge">{count}</span>}
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
