import {Link} from 'react-router';
import type {FooterQuery, HeaderQuery} from 'storefrontapi.generated';
import {FOOTER_LINKS} from './navigation';

interface FooterProps {
  footer: Promise<FooterQuery | null>;
  header: HeaderQuery;
  publicStoreDomain: string;
}

export function Footer(_: FooterProps) {
  return (
    <footer className="site-footer" role="contentinfo">
      <div className="site-footer-inner">
        <ul className="site-footer-links">
          {FOOTER_LINKS.map((link) => (
            <li key={link.label}>
              <Link to={link.url} prefetch="intent" className="site-footer-link">
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </footer>
  );
}
