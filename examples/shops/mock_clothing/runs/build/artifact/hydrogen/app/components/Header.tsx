import {Suspense, useEffect, useState} from 'react';
import {Await, NavLink, useAsyncValue} from 'react-router';
import {
  type CartViewPayload,
  useAnalytics,
  useOptimisticCart,
} from '@shopify/hydrogen';
import type {HeaderQuery, CartApiQueryFragment} from 'storefrontapi.generated';
import {useAside} from '~/components/Aside';
import {AnnouncementBar} from '~/components/AnnouncementBar';
import {MegaMenu} from '~/components/MegaMenu';
import {MobileNav} from '~/components/MobileNav';
import {SubNavBar} from '~/components/SubNavBar';
import type {NavCategory} from '~/lib/navigation';

// Navigation is grounded in collections.json. Every link points to a real
// collection handle, and each handle appears at most once across the whole
// menu. Labels describe what is actually inside the linked collection — they
// are NOT derived from a wished-for taxonomy.
export const PRIMARY_NAV: NavCategory[] = [
  {
    label: 'Women',
    url: '/collections/womens-storefront',
    feature: {
      headline: "Women's Storefront",
      subline: 'Bras, leggings, hoodies, and run-ready layers in one place.',
      cta: "Shop Women's",
      ctaUrl: '/collections/womens-storefront',
      imageUrl: '/images/nav-women.png',
    },
    groups: [
      {
        heading: 'Shop',
        links: [
          {label: "Shop All Women's", url: '/collections/womens-browse-all'},
          {label: 'Sports Bras', url: '/collections/performance-bras'},
          {label: 'Coordinated Sets', url: '/collections/coordinated-sets'},
          {label: "All Women's Gear", url: '/collections/all-womens-gear'},
          {label: 'Spotted on Social', url: '/collections/spotted-on-feeds'},
        ],
      },
      {
        heading: 'Highlights',
        links: [
          {label: 'Best Gifts For Her', url: '/collections/best-gifts-for-her'},
          {label: 'Editor Selects', url: '/collections/editor-selects'},
        ],
      },
    ],
  },
  {
    label: 'Men',
    url: '/collections/mens-storefront',
    feature: {
      headline: "Men's Storefront",
      subline: 'Tees, long sleeves, hoodies, and everyday layers.',
      cta: "Shop Men's",
      ctaUrl: '/collections/mens-storefront',
      imageUrl: '/images/nav-men.png',
    },
    groups: [
      {
        heading: 'Shop',
        links: [
          {label: "Shop All Men's", url: '/collections/mens-browse-all'},
          {label: 'Hoodies & Tops', url: '/collections/guys-hooded-tops'},
          {label: "All Men's Gear", url: '/collections/all-mens-gear'},
        ],
      },
    ],
  },
  {
    label: 'Activewear',
    url: '/collections/training-zone',
    feature: {
      headline: 'Move Softly. Live Boldly.',
      subline: 'Studio-tested staples for every kind of movement.',
      cta: 'Shop Activewear',
      ctaUrl: '/collections/training-zone',
      imageUrl: '/images/nav-activewear.png',
    },
    groups: [
      {
        heading: 'By Activity',
        links: [
          {label: 'Train', url: '/collections/training-zone'},
          {label: 'Run', url: '/collections/womens-run-club'},
          {label: 'Pilates', url: '/collections/reformer-ready'},
          {label: 'Court Sports', url: '/collections/racquet-club'},
        ],
      },
      {
        heading: 'Featured',
        links: [
          {label: 'Studio Staples', url: '/collections/studio-staples'},
          {label: 'Currently Popular', url: '/collections/currently-popular'},
        ],
      },
    ],
  },
  {
    label: 'Loungewear',
    url: '/collections/lounge-collection',
    feature: {
      headline: 'At Home Comfort',
      subline: 'Plush layers built for slow mornings and slower evenings.',
      cta: 'Shop Loungewear',
      ctaUrl: '/collections/lounge-collection',
      imageUrl: '/images/nav-loungewear.png',
    },
    groups: [
      {
        heading: 'Cozy',
        links: [
          {label: 'All Loungewear', url: '/collections/lounge-collection'},
          {label: 'Cold Weather', url: '/collections/frost-season-collection'},
          {label: 'Matching Lounge Kits', url: '/collections/matching-lounge-kits'},
          {label: 'At Home Comfort', url: '/collections/at-home-comfort'},
        ],
      },
      {
        heading: 'Seasonal',
        links: [
          {label: 'Spring Edit', url: '/collections/vernal-season-edit'},
          {label: 'Festive Picks', url: '/collections/festive-season-picks'},
          {label: 'Ready to Ship', url: '/collections/ready-to-ship'},
        ],
      },
    ],
  },
  {
    label: 'New Arrivals',
    url: '/collections/fresh-drops',
    badge: 'new',
  },
  {
    label: 'Sale',
    url: '/collections/end-of-year-promo',
    accent: true,
  },
];

interface HeaderProps {
  header: HeaderQuery;
  cart: Promise<CartApiQueryFragment | null>;
  isLoggedIn: Promise<boolean>;
  publicStoreDomain: string;
}

export function Header({header, isLoggedIn, cart}: HeaderProps) {
  const {shop} = header;
  const [hoveredCategory, setHoveredCategory] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 80);
    onScroll();
    window.addEventListener('scroll', onScroll, {passive: true});
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const closeMobile = () => setMobileOpen(false);

  return (
    <>
      <AnnouncementBar />
      <header
        className={`site-header${scrolled ? ' is-scrolled' : ''}`}
        onMouseLeave={() => setHoveredCategory(null)}
      >
        <div className="site-header-row">
          <div className="site-header-left">
            <NavLink to="/" prefetch="intent" className="site-header-logo">
              <span className="site-header-logo-mark">{shop.name}</span>
            </NavLink>
          </div>

          <nav className="site-header-nav" aria-label="Primary">
            {PRIMARY_NAV.map((category) => {
              const hasMega = Boolean(
                category.groups && category.groups.length > 0,
              );
              const isActive = hoveredCategory === category.label;
              return (
                <div
                  key={category.label}
                  className={`site-header-nav-item${
                    category.accent ? ' is-accent' : ''
                  }${isActive ? ' is-active' : ''}`}
                  onMouseEnter={() =>
                    setHoveredCategory(hasMega ? category.label : null)
                  }
                  onFocus={() =>
                    setHoveredCategory(hasMega ? category.label : null)
                  }
                >
                  <NavLink
                    to={category.url}
                    prefetch="intent"
                    className="site-header-nav-link"
                  >
                    {category.label}
                    {category.badge === 'new' && (
                      <span className="site-header-nav-badge" aria-hidden="true">
                        New
                      </span>
                    )}
                  </NavLink>
                  {hasMega && isActive && (
                    <MegaMenu
                      category={category}
                      onNavigate={() => setHoveredCategory(null)}
                    />
                  )}
                </div>
              );
            })}
          </nav>

          <HeaderUtilities
            cart={cart}
            isLoggedIn={isLoggedIn}
            onOpenMobile={() => setMobileOpen(true)}
          />
        </div>

        <SubNavBar />
      </header>

      <MobileNav open={mobileOpen} onClose={closeMobile} />
    </>
  );
}

function HeaderUtilities({
  cart,
  isLoggedIn,
  onOpenMobile,
}: Pick<HeaderProps, 'cart' | 'isLoggedIn'> & {
  onOpenMobile: () => void;
}) {
  const {open} = useAside();
  return (
    <div className="site-header-utilities">
      <button
        type="button"
        className="header-icon-button"
        onClick={() => open('search')}
        aria-label="Open search"
      >
        <SearchIcon />
      </button>

      <NavLink to="/account" className="site-header-account">
        <AccountIcon />
        <span className="site-header-account-text">
          <Suspense fallback="Sign In · Earn Rewards">
            <Await resolve={isLoggedIn} errorElement="Sign In · Earn Rewards">
              {(loggedIn) => (loggedIn ? 'My Account' : 'Sign In · Earn Rewards')}
            </Await>
          </Suspense>
        </span>
      </NavLink>

      <button
        type="button"
        className="header-icon-button site-header-wishlist"
        aria-label="View wishlist"
      >
        <HeartIcon />
      </button>

      <CartToggle cart={cart} />

      <button
        type="button"
        className="header-icon-button site-header-hamburger"
        onClick={onOpenMobile}
        aria-label="Open menu"
      >
        <HamburgerIcon />
      </button>
    </div>
  );
}

function CartToggle({cart}: Pick<HeaderProps, 'cart'>) {
  return (
    <Suspense fallback={<CartBadgeButton count={0} />}>
      <Await resolve={cart}>
        <CartBadgeFromAwait />
      </Await>
    </Suspense>
  );
}

function CartBadgeFromAwait() {
  const originalCart = useAsyncValue() as CartApiQueryFragment | null;
  const cart = useOptimisticCart(originalCart);
  return <CartBadgeButton count={cart?.totalQuantity ?? 0} />;
}

function CartBadgeButton({count}: {count: number}) {
  const {open} = useAside();
  const {publish, shop, cart: analyticsCart, prevCart} = useAnalytics();

  return (
    <button
      type="button"
      className="header-icon-button site-header-cart"
      onClick={() => {
        open('cart');
        publish('cart_viewed', {
          cart: analyticsCart,
          prevCart,
          shop,
          url: typeof window !== 'undefined' ? window.location.href : '',
        } as CartViewPayload);
      }}
      aria-label={`Cart, ${count} item${count === 1 ? '' : 's'}`}
    >
      <BagIcon />
      {count > 0 && (
        <span className="site-header-cart-badge" aria-hidden="true">
          {count}
        </span>
      )}
    </button>
  );
}

function HamburgerIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
    >
      <path d="M3 6h14M3 10h14M3 14h14" strokeLinecap="round" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
    >
      <circle cx="9" cy="9" r="6" />
      <path d="M14 14l4 4" strokeLinecap="round" />
    </svg>
  );
}

function AccountIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
    >
      <circle cx="10" cy="7" r="3" />
      <path d="M3.5 17c1.5-3.5 4.5-5 6.5-5s5 1.5 6.5 5" strokeLinecap="round" />
    </svg>
  );
}

function HeartIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
    >
      <path
        d="M10 16.5C5 13 2 10.5 2 7.5A4 4 0 0 1 10 5a4 4 0 0 1 8 2.5c0 3-3 5.5-8 9z"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function BagIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
    >
      <path d="M4 6h12l-1 11H5L4 6z" strokeLinejoin="round" />
      <path d="M7 6V4.5a3 3 0 0 1 6 0V6" strokeLinecap="round" />
    </svg>
  );
}
