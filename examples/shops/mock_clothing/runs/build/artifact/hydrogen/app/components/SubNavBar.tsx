import {NavLink} from 'react-router';
import {SUB_NAV_CHIPS} from '~/lib/navigation';

export function SubNavBar() {
  return (
    <nav className="sub-nav-bar" aria-label="Trending categories">
      <div className="sub-nav-track">
        {SUB_NAV_CHIPS.map((chip) => (
          <NavLink
            key={chip.label}
            to={chip.url}
            className={({isActive}) =>
              `sub-nav-chip${isActive ? ' is-active' : ''}`
            }
            prefetch="intent"
          >
            {chip.label}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
