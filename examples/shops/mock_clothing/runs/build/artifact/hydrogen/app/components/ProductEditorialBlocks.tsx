import {Link} from 'react-router';

const BLOCKS = [
  {
    eyebrow: 'The Studio Edit',
    headline: 'Built for the rhythm of every workout.',
    body: 'High-performance pieces in technical fabrics that move with you — engineered for sweat, comfort, and softness against the skin.',
    cta: 'Explore Activewear',
    href: '/collections/training-zone',
    palette: 'linear-gradient(135deg, #c5a47e 0%, #6e553f 100%)',
    glyph: 'studio',
  },
  {
    eyebrow: 'Wear It Together',
    headline: 'Coordinated sets that pair without thinking.',
    body: 'Bra-and-legging pairings and matching tops-and-bottoms designed to work as one outfit — no guesswork, just go.',
    cta: 'Shop Coordinated Sets',
    href: '/collections/coordinated-sets',
    palette: 'linear-gradient(150deg, #efe6d6 0%, #c5a47e 60%, #5b4838 100%)',
    glyph: 'engrave',
  },
];

export function ProductEditorialBlocks() {
  return (
    <section className="pdp-editorial-blocks">
      {BLOCKS.map((b) => (
        <article className="pdp-editorial-card" key={b.href}>
          <div
            className="pdp-editorial-card-art"
            style={{background: b.palette}}
            aria-hidden="true"
          >
            <EditorialGlyph kind={b.glyph} />
          </div>
          <div className="pdp-editorial-card-body">
            <p className="pdp-editorial-card-eyebrow">{b.eyebrow}</p>
            <h3 className="pdp-editorial-card-headline">{b.headline}</h3>
            <p className="pdp-editorial-card-copy">{b.body}</p>
            <Link
              to={b.href}
              prefetch="intent"
              className="btn btn-primary pdp-editorial-card-cta"
            >
              {b.cta}
            </Link>
          </div>
        </article>
      ))}
    </section>
  );
}

function EditorialGlyph({kind}: {kind: string}) {
  if (kind === 'studio') {
    return (
      <svg
        viewBox="0 0 320 200"
        preserveAspectRatio="xMidYMid slice"
        className="pdp-editorial-glyph"
      >
        <g opacity="0.4" stroke="#fbf8f3" strokeWidth="1.5" fill="none">
          <path d="M40 140 q50 -90 110 -60 q60 30 130 -10" />
          <path d="M40 160 q60 -60 130 -40 q70 20 110 -30" />
        </g>
        <g fill="rgba(251, 248, 243, 0.6)">
          <circle cx="80" cy="140" r="12" />
          <circle cx="220" cy="80" r="10" />
        </g>
      </svg>
    );
  }
  return (
    <svg
      viewBox="0 0 320 200"
      preserveAspectRatio="xMidYMid slice"
      className="pdp-editorial-glyph"
    >
      <g opacity="0.55" fill="none" stroke="#fbf8f3" strokeWidth="1.4">
        <path d="M120 70 q20 -10 40 0 q20 10 0 40 q-20 30 -40 60 q-20 -30 -40 -60 q-20 -30 0 -40 q20 -10 40 0z" />
        <path d="M200 100 q15 -5 30 0 q15 5 0 30 q-15 25 -30 45 q-15 -20 -30 -45 q-15 -25 0 -30 q15 -5 30 0z" />
      </g>
    </svg>
  );
}
