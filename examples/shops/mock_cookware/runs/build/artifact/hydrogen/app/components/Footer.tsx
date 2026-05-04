import {Link} from 'react-router';
import type {FooterQuery, HeaderQuery} from 'storefrontapi.generated';

interface FooterProps {
  footer: Promise<FooterQuery | null>;
  header: HeaderQuery;
  publicStoreDomain: string;
}

type FooterLink = {label: string; to: string};

type FooterColumn = {
  heading: string;
  links: FooterLink[];
};

const FOOTER_COLUMNS: FooterColumn[] = [
  {
    heading: 'Shop',
    links: [
      {label: 'Cookware', to: '/collections/cookware'},
      {label: 'Knives', to: '/collections/knives'},
      {label: 'Bakeware', to: '/collections/bakeware'},
      {label: 'Kitchen Tools', to: '/collections/kitchen-tools-utensils'},
      {label: 'Cookware Sets', to: '/collections/cookware-sets'},
      {label: 'Sale', to: '/collections/sale'},
      {label: 'Brand Story', to: '/pages/about'},
    ],
  },
  {
    heading: 'Help',
    links: [
      {label: 'Care Guide', to: '/pages/faq'},
      {label: 'FAQ', to: '/pages/faq'},
      {label: 'Warranty', to: '/pages/returns'},
      {label: 'Contact', to: '/pages/contact'},
      {label: 'Careers', to: '/pages/about'},
      {label: 'Privacy Policy', to: '/policies/privacy-policy'},
    ],
  },
  {
    heading: 'Media & About',
    links: [
      {label: 'Press', to: '/pages/about'},
      {label: 'Recipes', to: '/blogs/journal'},
      {label: 'Brand Education', to: '/pages/faq'},
      {label: 'Partners', to: '/pages/contact'},
    ],
  },
];

const SOCIAL_LINKS: {label: string; href: string; icon: 'instagram' | 'facebook' | 'youtube' | 'pinterest'}[] = [
  {label: 'Instagram', href: '#', icon: 'instagram'},
  {label: 'Facebook', href: '#', icon: 'facebook'},
  {label: 'YouTube', href: '#', icon: 'youtube'},
  {label: 'Pinterest', href: '#', icon: 'pinterest'},
];

const LEGAL_LINKS: FooterLink[] = [
  {label: 'Terms of Service', to: '/policies/terms-of-service'},
  {label: 'Terms of Sale', to: '/policies/refund-policy'},
  {label: 'Accessibility', to: '/pages/about'},
  {label: 'Privacy Policy', to: '/policies/privacy-policy'},
  {label: 'Sitemap', to: '/sitemap.xml'},
  {label: 'Privacy Opt-Out', to: '/policies/privacy-policy'},
];

export function Footer({header}: FooterProps) {
  const shopName = header?.shop?.name ?? 'Mock Cookware';
  const year = new Date().getFullYear();

  return (
    <footer className="site-footer" role="contentinfo">
      <div className="site-footer-inner">
        <div className="footer-top">
          {FOOTER_COLUMNS.map((col) => (
            <div className="footer-column" key={col.heading}>
              <h3>{col.heading}</h3>
              <ul>
                {col.links.map((link) => (
                  <li key={`${col.heading}-${link.label}`}>
                    <Link to={link.to} prefetch="intent">
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <div className="footer-column">
            <h3>Find Us</h3>
            <ul className="footer-social-list">
              {SOCIAL_LINKS.map((s) => (
                <li key={s.label}>
                  <a
                    href={s.href}
                    className="footer-social-link"
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={s.label}
                  >
                    <SocialIcon icon={s.icon} />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="footer-bottom">
          <span className="footer-copyright">
            © {year} {shopName}. All rights reserved.
          </span>
          <nav className="footer-bottom-legal" aria-label="Legal">
            {LEGAL_LINKS.map((link) => (
              <Link key={link.label} to={link.to} prefetch="intent">
                {link.label}
              </Link>
            ))}
          </nav>
          <span className="footer-wordmark" aria-hidden="true">
            {shopName}
          </span>
        </div>
      </div>
    </footer>
  );
}

function SocialIcon({icon}: {icon: 'instagram' | 'facebook' | 'youtube' | 'pinterest'}) {
  const props = {
    width: 18,
    height: 18,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };
  if (icon === 'instagram') {
    return (
      <svg {...props}>
        <rect x="3" y="3" width="18" height="18" rx="5" />
        <circle cx="12" cy="12" r="4" />
        <circle cx="17.5" cy="6.5" r="0.5" fill="currentColor" />
      </svg>
    );
  }
  if (icon === 'facebook') {
    return (
      <svg {...props}>
        <path d="M14 8h2V5h-2a3 3 0 0 0-3 3v2H9v3h2v6h3v-6h2.5l.5-3H14V8z" />
      </svg>
    );
  }
  if (icon === 'youtube') {
    return (
      <svg {...props}>
        <rect x="3" y="6" width="18" height="12" rx="3" />
        <path d="M11 9.5l4 2.5-4 2.5z" fill="currentColor" stroke="none" />
      </svg>
    );
  }
  return (
    <svg {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M11 8l-2 9M11 8c0-1.5 1-2.5 2.5-2.5S16 6.5 16 8.5 14.5 12 13 12s-2-1-2-1" />
    </svg>
  );
}
