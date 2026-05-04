import {Link} from 'react-router';

export function HeroBanner() {
  return (
    <section className="hero-banner" aria-label="Featured promotion">
      <div className="hero-banner-media" aria-hidden="true">
        <img
          src="/images/homepage-hero.png"
          alt=""
          className="hero-banner-image"
          loading="eager"
          decoding="async"
        />
      </div>
      <div className="hero-banner-inner">
        <p className="hero-banner-eyebrow">New Season Cookware</p>
        <h1 className="hero-banner-headline">
          Pans built to outlast every dinner rush
        </h1>
        <p className="hero-banner-subline">
          Heirloom-grade cookware engineered for daily cooks and chef-tested
          across hundreds of recipes. Trade up your kitchen with sets that earn
          their place on the stove.
        </p>
        <div className="hero-banner-ctas">
          <Link
            to="/collections/best-sellers"
            prefetch="intent"
            className="hero-banner-cta hero-banner-cta-primary"
          >
            Shop Best Sellers
          </Link>
          <Link
            to="/collections/cookware-sets"
            prefetch="intent"
            className="hero-banner-cta hero-banner-cta-secondary"
          >
            Explore Sets
          </Link>
        </div>
      </div>
    </section>
  );
}
