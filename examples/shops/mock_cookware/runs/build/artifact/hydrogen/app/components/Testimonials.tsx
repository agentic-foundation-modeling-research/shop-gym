import {useEffect, useState} from 'react';

type Testimonial = {
  quote: string;
  author: string;
  detail: string;
};

const TESTIMONIALS: Testimonial[] = [
  {
    quote:
      'I cook for a family of five every night. These pans have replaced everything in my cabinet — they heat evenly and look new after two years.',
    author: 'Priya R.',
    detail: 'Verified buyer, 10-Piece Hard-Anodized Set',
  },
  {
    quote:
      'The cast-iron skillet is the best I’ve ever owned. Pre-seasoned out of the box, and it cleans up in seconds.',
    author: 'Marcus L.',
    detail: 'Verified buyer, Cast-Iron Skillet 12"',
  },
  {
    quote:
      'I gave the chef knife as a wedding gift and ended up buying one for myself. Holds an edge through pounds of prep.',
    author: 'Elena K.',
    detail: 'Verified buyer, 8-inch Forged Chef’s Knife',
  },
  {
    quote:
      'Fast shipping and customer service responded the same day when I had a question about my warranty.',
    author: 'Daniel T.',
    detail: 'Verified buyer, Tri-Ply Stainless Stockpot 8 qt',
  },
];

export function Testimonials() {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setIndex((cur) => (cur + 1) % TESTIMONIALS.length);
    }, 6000);
    return () => clearInterval(id);
  }, []);

  const current = TESTIMONIALS[index];

  return (
    <section className="testimonials" aria-label="Customer reviews">
      <div className="section-container testimonials-inner">
        <div
          className="testimonials-rating"
          role="img"
          aria-label="4.8 of 5 stars"
        >
          <span className="testimonials-stars" aria-hidden="true">
            ★★★★★
          </span>
          <span className="testimonials-rating-text">
            4.8 / 5 — 12,000+ Reviews
          </span>
        </div>
        <blockquote className="testimonials-quote">
          “{current.quote}”
        </blockquote>
        <p className="testimonials-author">
          <strong>{current.author}</strong>
          <span> · {current.detail}</span>
        </p>
        <div className="testimonials-dots" role="tablist" aria-label="Choose review">
          {TESTIMONIALS.map((t, i) => (
            <button
              key={t.author}
              type="button"
              role="tab"
              aria-selected={i === index}
              className={`testimonials-dot${i === index ? ' is-active' : ''}`}
              onClick={() => setIndex(i)}
              aria-label={`Show review ${i + 1}`}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
