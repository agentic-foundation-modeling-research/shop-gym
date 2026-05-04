export interface NavLink {
  label: string;
  url: string;
  badge?: 'new' | 'restock';
}

export interface NavGroup {
  heading: string;
  links: NavLink[];
}

export interface NavFeaturePanel {
  headline: string;
  subline: string;
  cta: string;
  ctaUrl: string;
  imageUrl?: string;
}

export interface NavCategory {
  label: string;
  url: string;
  groups?: NavGroup[];
  feature?: NavFeaturePanel;
  accent?: boolean;
  badge?: 'new' | 'sale';
}


export const SUB_NAV_CHIPS: NavLink[] = [
  {label: 'New In', url: '/collections/fresh-drops'},
  {label: 'Sports Bras', url: '/collections/performance-bras'},
  {label: 'Studio Staples', url: '/collections/studio-staples'},
  {label: 'Coordinated Sets', url: '/collections/coordinated-sets'},
  {label: 'Train', url: '/collections/training-zone'},
  {label: 'Run', url: '/collections/womens-run-club'},
  {label: 'Spotted On Feeds', url: '/collections/spotted-on-feeds'},
];

export interface FooterColumn {
  heading: string;
  links: NavLink[];
}

export const FOOTER_COLUMNS: FooterColumn[] = [
  {
    heading: 'Customer Support',
    links: [
      {label: 'Help Center', url: '/pages/faq'},
      {label: 'Track Your Order', url: '/account/orders'},
      {label: 'Returns & Exchanges', url: '/policies/refund-policy'},
      {label: 'Shipping Policy', url: '/policies/shipping-policy'},
      {label: 'Size Guide', url: '/pages/faq'},
      {label: 'Gift Card Balance', url: '/account'},
      {label: 'FAQs', url: '/pages/faq'},
      {label: 'Contact Us', url: '/pages/contact'},
    ],
  },
  {
    heading: 'Account & Loyalty',
    links: [
      {label: 'Sign In / Register', url: '/account'},
      {label: 'Order History', url: '/account/orders'},
      {label: 'Wishlist', url: '/account'},
      {label: 'Rewards Program', url: '/account'},
    ],
  },
  {
    heading: 'About',
    links: [
      {label: 'Our Story', url: '/pages/about'},
      {label: 'Sustainability', url: '/pages/about'},
      {label: 'Ambassador Program', url: '/pages/about'},
      {label: 'Community Events', url: '/pages/about'},
      {label: 'Retail Locations', url: '/pages/about'},
      {label: 'Journal', url: '/blogs'},
      {label: 'Contact Us', url: '/pages/contact'},
    ],
  },
];

export const LEGAL_LINKS: NavLink[] = [
  {label: 'Terms of Service', url: '/policies/terms-of-service'},
  {label: 'Privacy Policy', url: '/policies/privacy-policy'},
  {label: 'Cookie Policy', url: '/policies/privacy-policy'},
  {label: 'Cookie Preferences', url: '/policies/privacy-policy'},
];
