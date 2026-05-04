import {Suspense, useEffect, useRef, useState} from 'react';
import {Await, Link, NavLink, useAsyncValue, useLocation} from 'react-router';
import {useOptimisticCart} from '@shopify/hydrogen';
import type {HeaderQuery, CartApiQueryFragment} from 'storefrontapi.generated';
import {useAside} from '~/components/Aside';
import {MegaPanel} from '~/components/MegaMenu';
import {
  DEFAULT_LOCALE_CODE,
  LocaleButton,
  LocalePanel,
} from '~/components/LocalePanel';
import {LOCALES, PRIMARY_NAV, type NavEntry} from './navigation';

interface HeaderProps {
  header: HeaderQuery;
  cart: Promise<CartApiQueryFragment | null>;
  isLoggedIn: Promise<boolean>;
  publicStoreDomain: string;
  onOpenSearch?: () => void;
}

type OpenMenu = {kind: 'mega'; index: number} | {kind: 'locale'} | null;

export function Header({header, cart, onOpenSearch}: HeaderProps) {
  const {shop} = header;
  const [openMenu, setOpenMenu] = useState<OpenMenu>(null);
  const [localeCode, setLocaleCode] = useState(DEFAULT_LOCALE_CODE);
  const headerRef = useRef<HTMLElement | null>(null);
  const location = useLocation();

  useEffect(() => {
    setOpenMenu(null);
  }, [location.pathname]);

  useEffect(() => {
    if (!openMenu) return;
    function handleClick(e: MouseEvent) {
      if (headerRef.current && !headerRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpenMenu(null);
    }
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [openMenu]);

  const close = () => setOpenMenu(null);
  const activeLocale =
    LOCALES.find((l) => l.code === localeCode) ?? LOCALES[LOCALES.length - 1];

  return (
    <header className="site-header" ref={headerRef}>
      <div className="site-header-inner">
        <div className="site-header-left">
          <MobileMenuToggle />
          <Link
            to="/"
            prefetch="intent"
            className="site-header-logo"
            aria-label={shop.name}
          >
            <LogoMark />
            <span className="site-header-wordmark">{shop.name}</span>
          </Link>
          <nav
            className="primary-nav"
            aria-label="Primary navigation"
          >
            <ul className="primary-nav-list">
              {PRIMARY_NAV.map((entry, i) => (
                <PrimaryNavItem
                  key={entry.label}
                  entry={entry}
                  isOpen={
                    openMenu?.kind === 'mega' && openMenu.index === i
                  }
                  onToggle={() =>
                    setOpenMenu((cur) =>
                      cur?.kind === 'mega' && cur.index === i
                        ? null
                        : {kind: 'mega', index: i},
                    )
                  }
                  onClose={close}
                />
              ))}
            </ul>
          </nav>
        </div>
        <div className="site-header-right">
          <div className="site-header-locale">
            <LocaleButton
              locale={activeLocale}
              isOpen={openMenu?.kind === 'locale'}
              onToggle={() =>
                setOpenMenu((cur) =>
                  cur?.kind === 'locale' ? null : {kind: 'locale'},
                )
              }
            />
            {openMenu?.kind === 'locale' && (
              <LocalePanel
                selectedCode={localeCode}
                onSelect={setLocaleCode}
                onClose={close}
              />
            )}
          </div>
          <SearchToggle onOpen={onOpenSearch} />
          <CartToggle cart={cart} />
        </div>
      </div>
    </header>
  );
}

function PrimaryNavItem({
  entry,
  isOpen,
  onToggle,
  onClose,
}: {
  entry: NavEntry;
  isOpen: boolean;
  onToggle: () => void;
  onClose: () => void;
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
      className={`primary-nav-item primary-nav-item-mega${
        isOpen ? ' is-open' : ''
      }`}
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
      {isOpen && <MegaPanel entry={entry} onClose={onClose} />}
    </li>
  );
}

function LogoMark() {
  return (
    <svg
      width="28"
      height="28"
      viewBox="0 0 28 28"
      fill="none"
      aria-hidden="true"
      className="site-header-mark"
    >
      <rect width="28" height="28" rx="6" fill="#1a1a1a" />
      <rect x="7" y="9" width="14" height="10" rx="2" fill="#ffffff" />
      <rect x="9" y="11" width="10" height="2" fill="#1a1a1a" opacity="0.3" />
      <circle cx="17" cy="16" r="1.5" fill="#008060" />
    </svg>
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

function SearchToggle({onOpen}: {onOpen?: () => void}) {
  return (
    <button
      type="button"
      className="header-icon-button site-header-search"
      onClick={() => onOpen?.()}
      aria-label="Open search"
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

function CartBadge({count}: {count: number}) {
  return (
    <Link
      to="/cart"
      prefetch="intent"
      className="header-icon-button site-header-cart"
      aria-label={`Cart, ${count} item${count === 1 ? '' : 's'}`}
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
      {count > 0 && <span className="site-header-cart-badge">{count}</span>}
    </Link>
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
