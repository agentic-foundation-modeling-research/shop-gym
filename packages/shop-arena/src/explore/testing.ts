/**
 * Test doubles for Storefront exploration: an offline fixture site served
 * by node:http that records every request, and the pages of an invented
 * generic (non-Shopify) marketplace. No real merchant data.
 *
 * A site is a map from URL pathname to page. To add a route for a new
 * test, spread `genericSitePages(origin)` and add or replace an entry.
 */

import * as http from 'node:http';
import type { AddressInfo } from 'node:net';

/** One response of a fixture site. */
export interface FixturePage {
  /** Defaults to 200. */
  readonly status?: number;
  readonly contentType: string;
  readonly body: string;
}

/** Pages keyed by URL pathname. The query string does not select a page. */
export type FixturePages = Readonly<Record<string, FixturePage>>;

/** One request that a fixture site received. */
export interface FixtureRequest {
  /** Pathname plus query string, as sent. */
  readonly path: string;
  readonly userAgent: string;
}

/** A running fixture site. */
export interface FixtureSite {
  /** `http://127.0.0.1:<port>`, with no trailing slash. */
  readonly url: string;
  /** Every request the site received, oldest first. */
  readonly requests: readonly FixtureRequest[];
  close(): Promise<void>;
}

/**
 * Serves `pages(origin)` on a free local port. An unknown pathname gets a
 * 404 HTML page.
 */
export async function startFixtureSite(
  pages: (origin: string) => FixturePages,
): Promise<FixtureSite> {
  const requests: FixtureRequest[] = [];
  let routes: FixturePages = {};
  const server = http.createServer((req, res) => {
    const path = req.url ?? '/';
    requests.push({ path, userAgent: req.headers['user-agent'] ?? '' });
    const page = routes[new URL(path, 'http://fixture.invalid').pathname];
    if (page === undefined) {
      res.writeHead(404, { 'content-type': 'text/html' }).end(NOT_FOUND);
      return;
    }
    res.writeHead(page.status ?? 200, { 'content-type': page.contentType }).end(page.body);
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  routes = pages(url);
  return {
    url,
    requests,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

const HTML = 'text/html; charset=utf-8';
const NOT_FOUND = '<!doctype html><html><head><title>Page not found</title></head></html>';

/** The homepage title of the generic site: a brand segment, then a tagline. */
const GENERIC_SITE_TITLE = 'Fixture Mart. Spend less. Shop more.';

interface FixtureProduct {
  readonly path: string;
  readonly name: string;
  readonly price: string;
  /** Variant axis name to option labels; empty for a product with one variant. */
  readonly axes: Readonly<Record<string, readonly string[]>>;
  readonly rating: string;
  readonly ratingCount: number;
}

/** The products of the generic site, in sitemap order. */
const GENERIC_SITE_PRODUCTS: readonly FixtureProduct[] = [
  {
    path: '/p/fm-1001',
    name: 'Star Drifter - space adventure game',
    price: '59.99',
    axes: { Edition: ['Standard', 'Deluxe'], Platform: ['Console A', 'Console B'] },
    rating: '4.4',
    ratingCount: 120,
  },
  {
    path: '/p/fm-1002',
    name: 'Orbit wireless controller',
    price: '44.50',
    axes: { Color: ['Black', 'White', 'Red'] },
    rating: '4.1',
    ratingCount: 87,
  },
  {
    path: '/p/fm-1003',
    name: 'Nimbus over-ear gaming headset',
    price: '79.00',
    axes: {},
    rating: '3.8',
    ratingCount: 42,
  },
];

interface Department {
  readonly path: string;
  readonly name: string;
  readonly subDepartments: readonly string[];
}

/** The department that has its own page; it lists every product. */
const VIDEO_GAMES: Department = {
  path: '/d/video-games',
  name: 'Video Games',
  subDepartments: ['Consoles', 'Controllers', 'Games', 'Headsets'],
};

/** The departments, as the header menu shows them. */
const DEPARTMENTS: readonly Department[] = [
  VIDEO_GAMES,
  { path: '/d/home-kitchen', name: 'Home & Kitchen', subDepartments: ['Cookware', 'Storage'] },
  { path: '/d/books', name: 'Books', subDepartments: ['Fiction', 'Comics'] },
];

/** The `<li>` links to the sub-departments of `department`. */
function subDepartmentLinks(department: Department): string {
  return department.subDepartments
    .map((sub) => `<li><a href="${department.path}/${sub.toLowerCase()}">${sub}</a></li>`)
    .join('');
}

/** A page of the site; `canonical` is the path of its `<link rel="canonical">`, when it has one. */
function layout(title: string, main: string, canonical?: string): string {
  const departments = DEPARTMENTS.map(
    (department) =>
      `<li><a href="${department.path}">${department.name}</a><ul>${subDepartmentLinks(department)}</ul></li>`,
  ).join('');
  return `<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>${title}</title>${
    canonical === undefined ? '' : `<link rel="canonical" href="${canonical}">`
  }</head>
<body>
<header>
  <a href="/">Fixture Mart</a>
  <form action="/search" method="get" role="search">
    <input type="search" name="q" aria-label="Search">
    <button type="submit">Go</button>
  </form>
  <a href="/account/sign-in">Sign in</a>
  <a href="/cart">Cart (0)</a>
  <nav aria-label="Departments"><ul>${departments}</ul></nav>
</header>
<main>
${main}
</main>
<footer>
  <a href="/help">Help</a>
  <a href="/about">About us</a>
  <a href="/terms">Terms of use</a>
  <a href="https://partner.example.org/">Sell with a partner</a>
</footer>
</body>
</html>
`;
}

function productCard(product: FixtureProduct): string {
  return `<li><a href="${product.path}">${product.name}</a> <span>$${product.price}</span> <span>${product.rating} out of 5 stars (${product.ratingCount})</span></li>`;
}

function homePage(): string {
  return layout(
    GENERIC_SITE_TITLE,
    `<section aria-label="Hero"><h1>Deals on games and gear</h1><a href="/d/video-games">Shop video games</a></section>
<section aria-label="Popular products"><h2>Popular in Video Games</h2><ul>${GENERIC_SITE_PRODUCTS.map(
      productCard,
    ).join('')}</ul></section>`,
  );
}

function departmentPage(department: Department): string {
  return layout(
    department.name,
    `<h1>${department.name}</h1>
<ul>${subDepartmentLinks(department)}</ul>
<ul>${GENERIC_SITE_PRODUCTS.map(productCard).join('')}</ul>`,
  );
}

function searchPage(): string {
  const facet = (name: string, options: readonly string[]) =>
    `<fieldset><legend>${name}</legend>${options
      .map((option) => `<label><input type="checkbox"> ${option}</label>`)
      .join('')}</fieldset>`;
  return layout(
    'Search results',
    `<h1>Results</h1>
<aside aria-label="Filters">
${facet('Department', ['Video Games', 'Electronics'])}
${facet('Brand', ['Brand A', 'Brand B'])}
${facet('Price', ['Under $25', '$25 to $50', '$50 and up'])}
${facet('Customer rating', ['4 stars and up', '3 stars and up'])}
</aside>
<label>Sort by <select name="sort"><option>Featured</option><option>Price: low to high</option><option>Price: high to low</option><option>Customer rating</option><option>Newest arrivals</option></select></label>
<ol>${GENERIC_SITE_PRODUCTS.map(productCard).join('')}</ol>
<nav aria-label="Pagination"><span>1</span> <a href="/search?q=game&amp;page=2">2</a> <a href="/search?q=game&amp;page=3">3</a> <a href="/search?q=game&amp;page=2">Next</a></nav>`,
  );
}

function productPage(product: FixtureProduct): string {
  const selectors = Object.entries(product.axes)
    .map(
      ([axis, options]) =>
        `<fieldset><legend>${axis}</legend>${options
          .map((option) => `<button type="button">${option}</button>`)
          .join('')}</fieldset>`,
    )
    .join('');
  const histogram = [5, 4, 3, 2, 1]
    .map(
      (stars, index) =>
        `<li>${stars} star <meter value="${[62, 20, 9, 4, 5][index]}" max="100"></meter></li>`,
    )
    .join('');
  const related = GENERIC_SITE_PRODUCTS.filter((other) => other.path !== product.path)
    .map(productCard)
    .join('');
  return layout(
    product.name,
    `<h1>${product.name}</h1>
<p>Price: <span>$${product.price}</span></p>
${selectors}
<label>Quantity <select name="quantity"><option>1</option><option>2</option><option>3</option></select></label>
<form action="/cart/add" method="post"><button type="submit">Add to cart</button></form>
<section aria-label="Customer reviews">
  <h2>Customer reviews</h2>
  <p>${product.rating} out of 5 (${product.ratingCount} ratings)</p>
  <ul aria-label="Rating histogram">${histogram}</ul>
  <label>Filter by <select name="review-filter"><option>All stars</option><option>5 star only</option><option>Critical reviews</option><option>Verified purchase only</option></select></label>
  <article><h3>Works as described</h3><p>Rated 5 of 5. Verified purchase.</p></article>
</section>
<section aria-label="Frequently bought together"><h2>Frequently bought together</h2><ul>${related}</ul></section>
<section aria-label="Customers also viewed"><h2>Customers also viewed</h2><ul>${related}</ul></section>`,
    product.path,
  );
}

function sitemap(origin: string): string {
  const paths = [
    '/',
    ...DEPARTMENTS.map((department) => department.path),
    ...GENERIC_SITE_PRODUCTS.map((p) => p.path),
  ];
  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${paths.map((path) => `  <url><loc>${origin}${path}</loc></url>`).join('\n')}
</urlset>
`;
}

/**
 * The pages of the generic fixture site: a marketplace with no Shopify
 * marker and no JSON endpoints. It has robots.txt, a homepage with a
 * tagline title, sitemap.xml, a department page, a search results page
 * (`/search`, any query), and one page per product. A product page has
 * a canonical link to its own path.
 */
export function genericSitePages(origin: string): FixturePages {
  const html = (body: string): FixturePage => ({ contentType: HTML, body });
  return {
    '/robots.txt': {
      contentType: 'text/plain',
      body: `User-agent: *\nDisallow: /account/\nDisallow: /cart\nAllow: /\n\nSitemap: ${origin}/sitemap.xml\n`,
    },
    '/': html(homePage()),
    '/sitemap.xml': { contentType: 'application/xml', body: sitemap(origin) },
    [VIDEO_GAMES.path]: html(departmentPage(VIDEO_GAMES)),
    '/search': html(searchPage()),
    ...Object.fromEntries(
      GENERIC_SITE_PRODUCTS.map((product) => [product.path, html(productPage(product))]),
    ),
  };
}
