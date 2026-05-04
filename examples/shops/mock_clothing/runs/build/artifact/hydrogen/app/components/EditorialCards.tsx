import {useState} from 'react';
import {Link} from 'react-router';

interface EditorialCard {
  eyebrow: string;
  headline: string;
  description: string;
  ctaLabel: string;
  ctaUrl: string;
  gradient: string;
}

const CARDS: EditorialCard[] = [
  {
    eyebrow: 'Made for movement',
    headline: 'Studio-to-street layering',
    description:
      'Buttery-soft tights, breathable bras, and sculpted silhouettes for every kind of practice.',
    ctaLabel: 'Shop activewear',
    ctaUrl: '/collections/training-zone',
    gradient: 'linear-gradient(160deg, #d4b89e, #6e553f)',
  },
  {
    eyebrow: 'Warm, quiet luxury',
    headline: 'Knits that travel',
    description:
      'Softened modal blends and brushed fleece in tonal neutrals — destined to be packed and worn often.',
    ctaLabel: 'Shop loungewear',
    ctaUrl: '/collections/lounge-collection',
    gradient: 'linear-gradient(160deg, #efd8be, #a07e6c)',
  },
  {
    eyebrow: 'Wear it together',
    headline: 'Coordinated sets',
    description:
      'Bra-and-legging pairings and matching tops-and-bottoms designed to work as one outfit — no guesswork required.',
    ctaLabel: 'Shop sets',
    ctaUrl: '/collections/coordinated-sets',
    gradient: 'linear-gradient(160deg, #c5a47e, #82684a)',
  },
  {
    eyebrow: 'Cold weather, covered',
    headline: 'Frost season layers',
    description:
      'Cozy pullovers, jackets, and warm-weather socks for the months when softness matters most.',
    ctaLabel: 'Shop frost season',
    ctaUrl: '/collections/frost-season-collection',
    gradient: 'linear-gradient(160deg, #b8a386, #5d4d40)',
  },
];

export function EditorialCards() {
  const [pair, setPair] = useState(0);
  const totalPairs = Math.ceil(CARDS.length / 2);

  const handlePrev = () => setPair((p) => (p - 1 + totalPairs) % totalPairs);
  const handleNext = () => setPair((p) => (p + 1) % totalPairs);

  const visible = CARDS.slice(pair * 2, pair * 2 + 2);

  return (
    <section className="editorial-cards-section" aria-label="Editorial highlights">
      <div className="editorial-cards-header">
        <div>
          <span className="section-eyebrow">In the studio</span>
          <h2 className="section-heading section-heading-serif">
            The latest stories
          </h2>
        </div>
        <div className="editorial-cards-controls" role="group" aria-label="Pagination">
          <button
            type="button"
            className="editorial-cards-arrow"
            onClick={handlePrev}
            aria-label="Previous editorial pair"
          >
            ←
          </button>
          <span className="editorial-cards-progress" aria-hidden="true">
            {pair + 1} / {totalPairs}
          </span>
          <button
            type="button"
            className="editorial-cards-arrow"
            onClick={handleNext}
            aria-label="Next editorial pair"
          >
            →
          </button>
        </div>
      </div>
      <ul className="editorial-cards-list">
        {visible.map((card) => (
          <li key={card.headline} className="editorial-card">
            <Link
              to={card.ctaUrl}
              prefetch="intent"
              className="editorial-card-link"
            >
              <span
                className="editorial-card-image"
                style={{background: card.gradient}}
                aria-hidden="true"
              />
              <span className="editorial-card-body">
                <span className="editorial-card-eyebrow">{card.eyebrow}</span>
                <span className="editorial-card-headline">{card.headline}</span>
                <span className="editorial-card-description">
                  {card.description}
                </span>
                <span className="editorial-card-cta">{card.ctaLabel} →</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
