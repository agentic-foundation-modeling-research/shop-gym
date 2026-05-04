import {Link} from 'react-router';

interface RecipientTile {
  label: string;
  url: string;
  caption: string;
  gradient: string;
}

const RECIPIENTS: RecipientTile[] = [
  {
    label: 'For Her',
    url: '/collections/best-gifts-for-her',
    caption: 'Sports bras, leggings, and lounge layers she will reach for daily',
    gradient: 'linear-gradient(160deg, #f0d9c2 0%, #c5a47e 100%)',
  },
  {
    label: 'For Him',
    url: '/collections/mens-browse-all',
    caption: 'Tees, hoodies, and everyday staples for the men in your life',
    gradient: 'linear-gradient(160deg, #b3a08a 0%, #5d4d40 100%)',
  },
  {
    label: 'Under $150',
    url: '/collections/gifts-under-one-fifty',
    caption: 'Thoughtful picks at every price — wrapped and ready to give',
    gradient: 'linear-gradient(160deg, #e8c5b3 0%, #a07e6c 100%)',
  },
  {
    label: 'For Anyone',
    url: '/collections/universal-gift-guide',
    caption: 'Our curated gift guide — something for everyone on your list',
    gradient: 'linear-gradient(160deg, #d4b78b 0%, #82684a 100%)',
  },
];

export function GiftRecipientGrid() {
  return (
    <section className="gift-recipient-grid-section">
      <div className="section-header-center">
        <span className="section-eyebrow">Gifting Edit</span>
        <h2 className="section-heading section-heading-serif">
          Gifts they'll come back for
        </h2>
        <p className="section-subline">
          Curated capsules for every recipient — beautifully boxed, ready to
          travel, easy to love.
        </p>
      </div>
      <ul className="gift-recipient-grid">
        {RECIPIENTS.map((tile) => (
          <li key={tile.label}>
            <Link
              to={tile.url}
              prefetch="intent"
              className="gift-recipient-tile"
            >
              <span
                className="gift-recipient-tile-image"
                style={{background: tile.gradient}}
                aria-hidden="true"
              >
                <RecipientGlyph label={tile.label} />
              </span>
              <span className="gift-recipient-tile-overlay">
                <span className="gift-recipient-tile-label">{tile.label}</span>
                <span className="gift-recipient-tile-caption">
                  {tile.caption}
                </span>
                <span className="gift-recipient-tile-cta">Shop the edit →</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RecipientGlyph({label}: {label: string}) {
  return (
    <svg
      className="gift-recipient-tile-glyph"
      viewBox="0 0 200 240"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      <g
        stroke="rgba(255,255,255,0.55)"
        fill="none"
        strokeWidth="1.5"
        strokeLinecap="round"
      >
        <path d="M30 200 q60 -120 140 -40 q-30 80 -110 60" />
        <path d="M50 220 q40 -60 110 -20" />
      </g>
      <text
        x="50%"
        y="92%"
        textAnchor="middle"
        fill="rgba(255,255,255,0.85)"
        fontSize="18"
        letterSpacing="6"
        fontFamily="Inter, sans-serif"
      >
        {label.toUpperCase()}
      </text>
    </svg>
  );
}
