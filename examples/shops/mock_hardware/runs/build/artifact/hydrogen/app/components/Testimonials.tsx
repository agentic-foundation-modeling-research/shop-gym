type Testimonial = {
  brand: string;
  role: string;
  quote: string;
  attribution: string;
  accent: string;
  imageBg: string;
};

const TESTIMONIALS: Testimonial[] = [
  {
    brand: 'Petalwood Florals',
    role: 'Luxury floral lifestyle brand',
    quote:
      'Real-time inventory and customer notes mean every walk-in feels like a private appointment. The hardware fades into the counter and the moment stays with the buyer.',
    attribution: 'Maren Ostlund, Head of Ecommerce',
    accent: '#f3e7e1',
    imageBg: '#d8c2b8',
  },
  {
    brand: 'Solene Atelier',
    role: 'Specialty design and jewelry',
    quote:
      'One day we ring up sales at the bench, the next we are at a trunk show three states away. The same kit handles both — no spreadsheets, no compromises.',
    attribution: 'Aïsha Renaud, Owner',
    accent: '#e6e9f1',
    imageBg: '#b4bccd',
  },
  {
    brand: 'Hadley & Stoke',
    role: 'Premium travel goods',
    quote:
      'Our two-person store moves twice the volume it used to and we never feel rushed. Checkout is fast, returns are simple, and the till never lies.',
    attribution: 'Theo Ainsworth, Director of Ecommerce',
    accent: '#e3ece4',
    imageBg: '#a8c1ae',
  },
];

export function Testimonials() {
  return (
    <section
      className="testimonials-section"
      aria-labelledby="testimonials-heading"
    >
      <div className="testimonials-section-inner">
        <h3 id="testimonials-heading" className="testimonials-heading">
          Trusted by the brands setting the pace in retail
        </h3>
        <ul className="testimonials-list">
          {TESTIMONIALS.map((t) => (
            <li
              key={t.brand}
              className="testimonial-card"
              style={{background: t.accent}}
            >
              <div
                className="testimonial-image"
                style={{background: t.imageBg}}
                aria-hidden="true"
              >
                <TestimonialMonogram letter={t.brand.charAt(0)} />
              </div>
              <div className="testimonial-body">
                <h4 className="testimonial-brand">{t.brand}</h4>
                <p className="testimonial-role">{t.role}</p>
                <blockquote className="testimonial-quote">
                  <p>&ldquo;{t.quote}&rdquo;</p>
                </blockquote>
                <p className="testimonial-attribution">— {t.attribution}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function TestimonialMonogram({letter}: {letter: string}) {
  return (
    <svg
      viewBox="0 0 120 120"
      xmlns="http://www.w3.org/2000/svg"
      className="testimonial-monogram"
      role="img"
      aria-label=""
    >
      <circle cx="60" cy="60" r="44" fill="#ffffff" opacity="0.85" />
      <text
        x="60"
        y="74"
        textAnchor="middle"
        fontFamily="Inter, sans-serif"
        fontSize="48"
        fontWeight="700"
        fill="#1a1a1a"
      >
        {letter}
      </text>
    </svg>
  );
}
