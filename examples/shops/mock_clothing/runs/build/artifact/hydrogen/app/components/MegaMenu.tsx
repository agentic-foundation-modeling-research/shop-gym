import {NavLink} from 'react-router';
import type {NavCategory} from '~/lib/navigation';

interface MegaMenuProps {
  category: NavCategory;
  onNavigate?: () => void;
}

export function MegaMenu({category, onNavigate}: MegaMenuProps) {
  const groups = category.groups ?? [];
  const feature = category.feature;
  return (
    <div className="mega-menu" role="menu">
      <div className="mega-menu-inner">
        <div className="mega-menu-columns">
          {groups.map((group) => (
            <div className="mega-menu-column" key={group.heading}>
              <h4 className="mega-menu-heading">{group.heading}</h4>
              <ul className="mega-menu-list">
                {group.links.map((link) => (
                  <li key={`${group.heading}-${link.label}`}>
                    <NavLink
                      to={link.url}
                      className="mega-menu-link"
                      onClick={onNavigate}
                      prefetch="intent"
                    >
                      <span>{link.label}</span>
                      {link.badge === 'new' && (
                        <span className="mega-menu-badge">New</span>
                      )}
                      {link.badge === 'restock' && (
                        <span className="mega-menu-badge mega-menu-badge-restock">
                          Back In Stock
                        </span>
                      )}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        {feature && (
          <div className="mega-menu-feature">
            <div className="mega-menu-feature-image">
              {feature.imageUrl ? (
                <img
                  src={feature.imageUrl}
                  alt={feature.headline}
                  loading="lazy"
                  decoding="async"
                />
              ) : null}
            </div>
            <div className="mega-menu-feature-content">
              <h3 className="mega-menu-feature-headline">
                {feature.headline}
              </h3>
              <p className="mega-menu-feature-subline">{feature.subline}</p>
              <NavLink
                to={feature.ctaUrl}
                className="mega-menu-feature-cta"
                onClick={onNavigate}
                prefetch="intent"
              >
                {feature.cta}
                <span aria-hidden="true"> →</span>
              </NavLink>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
