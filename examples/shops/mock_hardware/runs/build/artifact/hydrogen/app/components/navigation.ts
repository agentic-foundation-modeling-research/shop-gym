export type NavLinkItem = {label: string; url: string};

export type BundleCard = {
  title: string;
  subcopy: string;
  url: string;
};

export type MegaEntry = {
  kind: 'mega';
  label: string;
  url: string;
  cards: BundleCard[];
  featured?: NavLinkItem[];
};

export type DirectEntry = {
  kind: 'link';
  label: string;
  url: string;
};

export type NavEntry = MegaEntry | DirectEntry;

export const PRIMARY_NAV: NavEntry[] = [
  {
    kind: 'mega',
    label: 'Bundles',
    url: '/collections/aislearena-counter-bundles',
    cards: [
      {
        title: 'Essential Counter',
        subcopy:
          'Starter hardware bundle with everything you need to ring up your first sale.',
        url: '/collections/aislearena-counter-bundles',
      },
      {
        title: 'Complete Counter',
        subcopy:
          'Full-store kit pairing terminals, scanners, printers, and till trays.',
        url: '/collections/aislearena-counter-kits',
      },
    ],
    featured: [
      {label: 'Till trays', url: '/collections/kit-maker-till-trays'},
      {label: 'AisleArena labels', url: '/collections/aislearena-labels'},
      {label: 'Service plans', url: '/collections/service-agreements'},
    ],
  },
  {
    kind: 'link',
    label: 'Card readers',
    url: '/collections/code-readers',
  },
  {
    kind: 'link',
    label: 'POS Hub',
    url: '/collections/retail-hub-companions',
  },
  {
    kind: 'link',
    label: 'Accessories',
    url: '/collections/essential-add-ons',
  },
  {
    kind: 'link',
    label: 'Gift cards',
    url: '/pages/gift-cards',
  },
];

export type Locale = {
  country: string;
  code: string;
  currency: string;
  symbol: string;
};

export const LOCALES: Locale[] = [
  {country: 'Australia', code: 'AU', currency: 'AUD', symbol: '$'},
  {country: 'Belgium', code: 'BE', currency: 'EUR', symbol: '€'},
  {country: 'Canada', code: 'CA', currency: 'CAD', symbol: '$'},
  {country: 'Czechia', code: 'CZ', currency: 'CZK', symbol: 'Kč'},
  {country: 'Denmark', code: 'DK', currency: 'DKK', symbol: 'kr.'},
  {country: 'Finland', code: 'FI', currency: 'EUR', symbol: '€'},
  {country: 'France', code: 'FR', currency: 'EUR', symbol: '€'},
  {country: 'Germany', code: 'DE', currency: 'EUR', symbol: '€'},
  {country: 'Ireland', code: 'IE', currency: 'EUR', symbol: '€'},
  {country: 'Italy', code: 'IT', currency: 'EUR', symbol: '€'},
  {country: 'Luxembourg', code: 'LU', currency: 'EUR', symbol: '€'},
  {country: 'Netherlands', code: 'NL', currency: 'EUR', symbol: '€'},
  {country: 'New Zealand', code: 'NZ', currency: 'NZD', symbol: '$'},
  {country: 'Singapore', code: 'SG', currency: 'SGD', symbol: '$'},
  {country: 'Spain', code: 'ES', currency: 'EUR', symbol: '€'},
  {country: 'Switzerland', code: 'CH', currency: 'CHF', symbol: ''},
  {country: 'United Kingdom', code: 'GB', currency: 'GBP', symbol: '£'},
  {country: 'United States', code: 'US', currency: 'USD', symbol: '$'},
];

export const DEFAULT_LOCALE_CODE = 'US';

export type Language = {label: string; code: string};

export const LANGUAGES: Language[] = [
  {label: 'English', code: 'EN'},
  {label: 'Español', code: 'ES'},
];

export const FOOTER_LINKS: NavLinkItem[] = [
  {label: 'Terms of Service', url: '/policies/terms-of-service'},
  {label: 'Rental Program', url: '/pages/hardware-rental-program'},
  {label: 'Hardware Compatibility', url: '/pages/pos-compatibility'},
  {label: 'FAQ', url: '/pages/faq'},
  {label: 'Returns', url: '/policies/refund-policy'},
  {label: 'Warranty', url: '/pages/shopify-products-warranty'},
  {label: 'Support', url: '/pages/contact'},
  {label: 'Your Privacy Choices', url: '/policies/privacy-policy'},
];
