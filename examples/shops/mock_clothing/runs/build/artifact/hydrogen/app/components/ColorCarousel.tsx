import {Link} from 'react-router';

interface ColorTile {
  name: string;
  swatch: string;
  caption: string;
  url: string;
}

const COLORS: ColorTile[] = [
  {
    name: 'Warm Neutral',
    swatch: 'linear-gradient(160deg, #efe6d6 0%, #b9a98c 100%)',
    caption: 'Foundational sand tones built to layer',
    url: '/collections/shop-by-hue',
  },
  {
    name: 'Sun-Washed Yellow',
    swatch: 'linear-gradient(160deg, #f0d977 0%, #c5a35a 100%)',
    caption: 'Warm light, captured for spring days',
    url: '/collections/vernal-season-edit',
  },
  {
    name: 'Dusty Rose',
    swatch: 'linear-gradient(160deg, #e9bdb0 0%, #b27465 100%)',
    caption: 'Soft warmth, season after season',
    url: '/collections/shop-by-hue',
  },
  {
    name: 'Muted Olive',
    swatch: 'linear-gradient(160deg, #9aa787 0%, #4d6a4a 100%)',
    caption: 'Studio greens for quiet mornings',
    url: '/collections/camo-pullover-pairing',
  },
  {
    name: 'Cool Heather',
    swatch: 'linear-gradient(160deg, #b3b8c0 0%, #5b6671 100%)',
    caption: 'Cooled-down hues with a quiet edge',
    url: '/collections/ocean-tone-hoodies',
  },
  {
    name: 'Deep Plum',
    swatch: 'linear-gradient(160deg, #7d4f6c 0%, #43253b 100%)',
    caption: 'Rich shades that move from day to dinner',
    url: '/collections/onyx-palette-trial',
  },
];

export function ColorCarousel() {
  return (
    <section className="color-carousel-section" aria-label="Shop by color">
      <div className="section-header-center">
        <span className="section-eyebrow">Spring Palette</span>
        <h2 className="section-heading section-heading-serif">Shop by Color</h2>
        <p className="section-subline">
          Six hand-chosen hues — from grounded earths to soft neutrals — to
          mix, match, and live in.
        </p>
      </div>
      <div className="color-carousel-track">
        {COLORS.map((color) => (
          <Link
            key={color.name}
            to={color.url}
            prefetch="intent"
            className="color-carousel-card"
          >
            <span
              className="color-carousel-swatch"
              style={{background: color.swatch}}
              aria-hidden="true"
            />
            <span className="color-carousel-meta">
              <span className="color-carousel-name">{color.name}</span>
              <span className="color-carousel-caption">{color.caption}</span>
              <span className="color-carousel-cta">
                Shop {color.name} →
              </span>
            </span>
          </Link>
        ))}
        <div className="color-carousel-fade" aria-hidden="true" />
      </div>
    </section>
  );
}
