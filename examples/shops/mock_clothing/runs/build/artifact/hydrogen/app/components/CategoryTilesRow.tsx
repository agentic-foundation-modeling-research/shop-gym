import {Link} from 'react-router';

interface CategoryTile {
  label: string;
  url: string;
  hue: string;
  badge?: 'new';
}

// Tiles point only to handles that exist in collections.json AND have
// meaningful product counts. Labels are honest about the collection's contents.
const TILES: CategoryTile[] = [
  {label: 'New In', url: '/collections/fresh-drops', hue: '#dcc6a8', badge: 'new'},
  {label: 'Sports Bras', url: '/collections/performance-bras', hue: '#e6cdb1'},
  {label: 'Studio Staples', url: '/collections/studio-staples', hue: '#d8c4a8'},
  {label: 'Coordinated Sets', url: '/collections/coordinated-sets', hue: '#bea185'},
  {label: 'Train', url: '/collections/training-zone', hue: '#b89a78'},
  {label: 'Run', url: '/collections/womens-run-club', hue: '#9a8367'},
  {label: 'Pilates', url: '/collections/reformer-ready', hue: '#d4b78b'},
  {label: 'Court Sports', url: '/collections/racquet-club', hue: '#cbb89a'},
  {label: 'Loungewear', url: '/collections/lounge-collection', hue: '#efd8be'},
  {label: 'Frost Season', url: '/collections/frost-season-collection', hue: '#a48560'},
  {label: 'Spring Edit', url: '/collections/vernal-season-edit', hue: '#e2c79a'},
  {label: "Men's", url: '/collections/mens-storefront', hue: '#e9d5c2'},
  {label: 'Final Sale', url: '/collections/end-of-year-promo', hue: '#b8454a'},
];

export function CategoryTilesRow() {
  return (
    <section className="category-tiles-row" aria-label="Shop by category">
      <div className="category-tiles-track">
        {TILES.map((tile) => (
          <Link
            key={tile.label}
            to={tile.url}
            prefetch="intent"
            className="category-tile"
          >
            <span
              className="category-tile-circle"
              style={{background: tile.hue}}
              aria-hidden="true"
            >
              <span className="category-tile-monogram">
                {tile.label.charAt(0)}
              </span>
              {tile.badge === 'new' && (
                <span className="category-tile-badge" aria-hidden="true">
                  New
                </span>
              )}
            </span>
            <span className="category-tile-label">{tile.label}</span>
          </Link>
        ))}
      </div>
      <div className="category-tiles-fade" aria-hidden="true" />
    </section>
  );
}
