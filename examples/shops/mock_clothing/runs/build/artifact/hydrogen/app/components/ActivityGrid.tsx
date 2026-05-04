import {Link} from 'react-router';

interface ActivityTile {
  label: string;
  caption: string;
  url: string;
  imageUrl: string;
}

const ACTIVITIES: ActivityTile[] = [
  {
    label: 'Pilates',
    caption: 'Mat-friendly pieces with grip and stretch',
    url: '/collections/reformer-ready',
    imageUrl: '/images/collection-reformer-ready.png',
  },
  {
    label: 'Lounge',
    caption: 'Soft-touch knits for slow mornings',
    url: '/collections/at-home-comfort',
    imageUrl: '/images/collection-at-home-comfort.png',
  },
  {
    label: 'Run',
    caption: 'Lightweight layers built for the long miles',
    url: '/collections/womens-run-club',
    imageUrl: '/images/collection-womens-run-club.png',
  },
  {
    label: 'Train',
    caption: 'High-impact pieces engineered for sweat',
    url: '/collections/training-zone',
    imageUrl: '/images/collection-training-zone.png',
  },
  {
    label: 'Court Sports',
    caption: 'Studio-tested layers for play and pivot',
    url: '/collections/racquet-club',
    imageUrl: '/images/collection-racquet-club.png',
  },
  {
    label: 'Studio',
    caption: 'Bras, leggings, and dresses for the studio floor',
    url: '/collections/studio-staples',
    imageUrl: '/images/collection-studio-staples.png',
  },
];

export function ActivityGrid() {
  return (
    <section className="activity-grid-section" aria-label="Shop by activity">
      <div className="section-header-center">
        <span className="section-eyebrow">Shop By Activity</span>
        <h2 className="section-heading section-heading-serif">
          Find your next favourite kit
        </h2>
        <p className="section-subline">
          Six edits curated by the way you move — from studio mornings to court
          afternoons.
        </p>
      </div>
      <ul className="activity-grid">
        {ACTIVITIES.map((activity) => (
          <li key={activity.label}>
            <Link
              to={activity.url}
              prefetch="intent"
              className="activity-tile"
              style={{backgroundImage: `url(${activity.imageUrl})`}}
            >
              <span className="activity-tile-content">
                <span className="activity-tile-label">{activity.label}</span>
                <span className="activity-tile-caption">{activity.caption}</span>
              </span>
              <span className="activity-tile-arrow" aria-hidden="true">
                →
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
