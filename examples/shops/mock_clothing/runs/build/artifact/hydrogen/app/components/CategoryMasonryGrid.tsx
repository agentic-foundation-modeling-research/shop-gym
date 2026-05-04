import {Link} from 'react-router';

interface MasonryTile {
  label: string;
  url: string;
  span: 'lg' | 'md' | 'sm';
  imageUrl: string;
}

// Tiles use real collection handles whose contents match the displayed label.
// `imageUrl` paths must match files in data/images/.
const TILES: MasonryTile[] = [
  {
    label: 'Hooded Layers',
    url: '/collections/hooded-layers',
    span: 'lg',
    imageUrl: '/images/collection-hooded-layers.png',
  },
  {
    label: 'Loungewear',
    url: '/collections/lounge-collection',
    span: 'md',
    imageUrl: '/images/collection-lounge-collection.png',
  },
  {
    label: 'At Home Comfort',
    url: '/collections/at-home-comfort',
    span: 'sm',
    imageUrl: '/images/collection-at-home-comfort.png',
  },
  {
    label: 'Casual Shorts',
    url: '/collections/casual-shorts',
    span: 'sm',
    imageUrl: '/images/collection-casual-shorts.png',
  },
  {
    label: 'Studio Staples',
    url: '/collections/studio-staples',
    span: 'md',
    imageUrl: '/images/collection-studio-staples.png',
  },
  {
    label: 'Train',
    url: '/collections/training-zone',
    span: 'lg',
    imageUrl: '/images/collection-training-zone.png',
  },
  {
    label: 'Spotted on Social',
    url: '/collections/spotted-on-feeds',
    span: 'sm',
    imageUrl: '/images/collection-spotted-on-feeds.png',
  },
];

export function CategoryMasonryGrid() {
  return (
    <section className="masonry-grid-section" aria-label="Shop by category">
      <div className="section-header-center">
        <span className="section-eyebrow">Editorial Shop</span>
        <h2 className="section-heading section-heading-serif">
          Browse the full edit
        </h2>
      </div>
      <ul className="masonry-grid">
        {TILES.map((tile) => (
          <li
            key={tile.label}
            className={`masonry-grid-item masonry-grid-item-${tile.span}`}
          >
            <Link
              to={tile.url}
              prefetch="intent"
              className="masonry-grid-tile"
              style={{backgroundImage: `url(${tile.imageUrl})`}}
            >
              <span className="masonry-grid-scrim" aria-hidden="true" />
              <span className="masonry-grid-label">{tile.label}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
