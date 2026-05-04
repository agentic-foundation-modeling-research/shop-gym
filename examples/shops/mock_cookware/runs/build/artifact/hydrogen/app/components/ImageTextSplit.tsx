import {Link} from 'react-router';

export function ImageTextSplit() {
  return (
    <section className="image-text-split" aria-label="Knives collection feature">
      <div className="section-container image-text-split-grid">
        <div className="image-text-split-media" aria-hidden="true">
          <img
            src="/images/homepage-knives-split.png"
            alt=""
            loading="lazy"
            decoding="async"
          />
        </div>
        <div className="image-text-split-panel">
          <p className="section-eyebrow accent">The Knife Edit</p>
          <h2 className="image-text-split-title">
            Forged blades for prep that flows
          </h2>
          <p className="image-text-split-body">
            Cold-forged from German steel and balanced for day-long
            prep. From paring knives to santokus, every blade ships
            sharpened by hand and ready to cook.
          </p>
          <Link
            to="/collections/knives"
            prefetch="intent"
            className="image-text-split-cta"
          >
            Shop the Knife Edit →
          </Link>
        </div>
      </div>
    </section>
  );
}
