import {Link} from 'react-router';
import {FOOTER_LINKS} from './navigation';

export function InfoPageFooter() {
  return (
    <section
      className="info-page-footer"
      role="group"
      aria-label="Help center links"
    >
      <ul className="info-page-footer-list">
        {FOOTER_LINKS.map((link) => (
          <li key={link.label} className="info-page-footer-item">
            <Link
              to={link.url}
              prefetch="intent"
              className="info-page-footer-link"
            >
              {link.label}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
