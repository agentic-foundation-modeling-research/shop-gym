import {useState} from 'react';
import {NavLink} from 'react-router';
import type {FooterQuery, HeaderQuery} from 'storefrontapi.generated';
import {FOOTER_COLUMNS, LEGAL_LINKS} from '~/lib/navigation';

interface FooterProps {
  footer: Promise<FooterQuery | null>;
  header: HeaderQuery;
  publicStoreDomain: string;
}

export function Footer({header}: FooterProps) {
  const shopName = header.shop?.name ?? 'Mock Clothing';
  return (
    <footer className="site-footer">
      <div className="site-footer-grid">
        <NewsletterColumn />
        {FOOTER_COLUMNS.map((column) => (
          <FooterColumnBlock key={column.heading} column={column} />
        ))}
      </div>

      <div className="site-footer-secondary">
        <div className="site-footer-secondary-left">
          <SocialIcons />
          <AppBadges />
        </div>
        <RegionPicker />
      </div>

      <div className="site-footer-legal">
        <p className="site-footer-copy">
          © 2026 {shopName}. All rights reserved.
        </p>
        <ul className="site-footer-legal-links">
          {LEGAL_LINKS.map((link) => (
            <li key={link.label}>
              <NavLink to={link.url} className="site-footer-legal-link">
                {link.label}
              </NavLink>
            </li>
          ))}
        </ul>
        <p className="site-footer-disclaimer">
          Comfort apparel for everyday wear. Not intended as medical or
          therapeutic equipment.
        </p>
      </div>
    </footer>
  );
}

function NewsletterColumn() {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [smsOptIn, setSmsOptIn] = useState(false);

  return (
    <div className="footer-column footer-newsletter">
      <h4 className="footer-column-heading">Stay In The Loop</h4>
      <p className="footer-newsletter-sub">
        Sign up for 10% off your first order, plus early access to new
        collections.
      </p>
      {submitted ? (
        <p className="footer-newsletter-thanks">
          Thanks — check your inbox for your code.
        </p>
      ) : (
        <form
          className="footer-newsletter-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (email.trim()) {
              setSubmitted(true);
            }
          }}
        >
          <label className="sr-only" htmlFor="footer-newsletter-email">
            Email address
          </label>
          <div className="footer-newsletter-row">
            <input
              id="footer-newsletter-email"
              className="footer-newsletter-input"
              type="email"
              name="email"
              required
              placeholder="Your email address"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <button type="submit" className="footer-newsletter-submit">
              Subscribe
            </button>
          </div>
          <label className="footer-newsletter-sms">
            <input
              type="checkbox"
              checked={smsOptIn}
              onChange={(e) => setSmsOptIn(e.target.checked)}
            />
            <span>Also send me SMS updates</span>
          </label>
        </form>
      )}
    </div>
  );
}

interface FooterColumn {
  heading: string;
  links: {label: string; url: string}[];
}

function FooterColumnBlock({column}: {column: FooterColumn}) {
  const [open, setOpen] = useState(false);

  return (
    <div className={`footer-column${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="footer-column-toggle"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <span>{column.heading}</span>
        <span className="footer-column-caret" aria-hidden="true">
          {open ? '−' : '+'}
        </span>
      </button>
      <h4 className="footer-column-heading">{column.heading}</h4>
      <ul className="footer-column-list">
        {column.links.map((link) => (
          <li key={link.label}>
            <NavLink to={link.url} className="footer-column-link">
              {link.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RegionPicker() {
  return (
    <button
      type="button"
      className="footer-region"
      aria-label="Change region or currency"
    >
      <span aria-hidden="true">🇺🇸</span>
      <span>USD $</span>
      <span aria-hidden="true">▾</span>
    </button>
  );
}

function SocialIcons() {
  const items: {label: string; path: string}[] = [
    {
      label: 'Photo Feed',
      path:
        'M5 3h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zm5 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6zm5-1a1 1 0 1 0 0 2 1 1 0 0 0 0-2z',
    },
    {
      label: 'Short Video',
      path:
        'M13 3v9a3 3 0 1 1-3-3v3a1.5 1.5 0 1 0 1.5 1.5V3H13c0 1.7 1.3 3 3 3v2c-1.1 0-2.2-.4-3-1z',
    },
    {
      label: 'Visual Boards',
      path:
        'M10 2a8 8 0 0 0-3 15.4c-.1-.7-.1-1.7 0-2.4l1-3.9s-.2-.5-.2-1.3c0-1.2.7-2.1 1.6-2.1.7 0 1.1.5 1.1 1.2 0 .8-.5 1.9-.7 3 0 .9.6 1.6 1.5 1.6 1.8 0 3.1-2 3.1-4.7 0-2-1.4-3.4-3.4-3.4-2.3 0-3.6 1.7-3.6 3.5 0 .7.3 1.4.6 1.8 0 .1.1.2 0 .3l-.2.9c0 .1-.1.2-.2.1-1-.5-1.7-2-1.7-3.2 0-2.6 1.9-5 5.5-5 2.9 0 5.1 2.1 5.1 4.8 0 2.9-1.8 5.2-4.4 5.2-.8 0-1.6-.4-1.9-.9l-.5 2c-.2.7-.7 1.7-1 2.2A8 8 0 1 0 10 2z',
    },
    {
      label: 'Video Channel',
      path:
        'M17.5 6.5c-.2-.8-.8-1.4-1.6-1.6-1.4-.4-7-.4-7-.4s-5.6 0-7 .4c-.8.2-1.4.8-1.6 1.6-.4 1.4-.4 4-.4 4s0 2.6.4 4c.2.8.8 1.4 1.6 1.6 1.4.4 7 .4 7 .4s5.6 0 7-.4c.8-.2 1.4-.8 1.6-1.6.4-1.4.4-4 .4-4s0-2.6-.4-4zM8 13V7l5 3-5 3z',
    },
  ];
  return (
    <div className="footer-social">
      {items.map((item) => (
        <a
          key={item.label}
          href="/pages/about"
          className="footer-social-link"
          aria-label={item.label}
        >
          <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true">
            <path d={item.path} fill="currentColor" />
          </svg>
        </a>
      ))}
    </div>
  );
}

function AppBadges() {
  return (
    <div className="footer-app-badges" aria-label="Mobile apps">
      <button type="button" className="footer-app-badge">
        <svg width="18" height="20" viewBox="0 0 18 20" fill="currentColor" aria-hidden="true">
          <path d="M14 10.5c0-2.4 2-3.6 2.1-3.6-1.1-1.7-2.9-1.9-3.5-1.9-1.5-.2-2.9.9-3.7.9-.7 0-2-.9-3.2-.8-1.7 0-3.2 1-4.1 2.5C-.2 10.6 1.1 15 2.8 17.4c.8 1.2 1.8 2.5 3.1 2.4 1.2 0 1.7-.8 3.2-.8s1.9.8 3.2.8c1.3 0 2.2-1.2 3-2.4.7-1.1 1.1-2.1 1.4-3.3-1.4-.6-2.7-2.2-2.7-3.6zM11.5 3.4c.7-.8 1.1-1.9 1-3-1 0-2.1.7-2.7 1.5-.6.7-1.1 1.8-1 2.9 1.1.1 2.1-.6 2.7-1.4z" />
        </svg>
        <span className="footer-app-badge-text">
          <small>Download on the</small>
          <strong>Mobile Store</strong>
        </span>
      </button>
      <button type="button" className="footer-app-badge">
        <svg width="18" height="20" viewBox="0 0 18 20" fill="currentColor" aria-hidden="true">
          <path d="M2 1l11 9-11 9V1zm12 8l3 1.5-3 1.5V9z" />
        </svg>
        <span className="footer-app-badge-text">
          <small>Get it on</small>
          <strong>App Market</strong>
        </span>
      </button>
    </div>
  );
}
