import {Link} from 'react-router';
import {PRIMARY_NAV} from '~/components/Header';

const NAV_PRIORITY = collectNavCollectionHandles(PRIMARY_NAV);

export function PdpBreadcrumbs({
  productTitle,
  collections,
}: {
  productTitle: string;
  collections: Array<{handle: string; title: string}>;
}) {
  const category = pickCategory(collections);
  const crumb = category
    ? {label: category.title, href: `/collections/${category.handle}`}
    : {label: 'Shop', href: '/collections/explore-everything'};

  return (
    <nav className="pdp-breadcrumbs" aria-label="Breadcrumb">
      <ol>
        <li>
          <Link to="/" prefetch="intent">
            Home
          </Link>
          <span aria-hidden="true" className="pdp-breadcrumb-sep">
            /
          </span>
        </li>
        <li>
          <Link to={crumb.href} prefetch="intent">
            {crumb.label}
          </Link>
          <span aria-hidden="true" className="pdp-breadcrumb-sep">
            /
          </span>
        </li>
        <li className="pdp-breadcrumb-current" aria-current="page">
          {productTitle}
        </li>
      </ol>
    </nav>
  );
}

function pickCategory(
  collections: Array<{handle: string; title: string}>,
): {handle: string; title: string} | null {
  if (collections.length === 0) return null;
  const byHandle = new Map(collections.map((c) => [c.handle, c]));
  for (const handle of NAV_PRIORITY) {
    const hit = byHandle.get(handle);
    if (hit) return hit;
  }
  return collections[0];
}

function collectNavCollectionHandles(
  nav: Array<{
    url: string;
    groups?: Array<{links: Array<{url: string}>}>;
  }>,
): string[] {
  const seen = new Set<string>();
  const ordered: string[] = [];
  const push = (url: string) => {
    const m = url.match(/^\/collections\/([^/?#]+)/);
    if (!m) return;
    const handle = m[1];
    if (seen.has(handle)) return;
    seen.add(handle);
    ordered.push(handle);
  };
  // Sub-links first (more specific), then category top-level URLs.
  for (const cat of nav) {
    for (const group of cat.groups ?? []) {
      for (const link of group.links) push(link.url);
    }
  }
  for (const cat of nav) push(cat.url);
  return ordered;
}
