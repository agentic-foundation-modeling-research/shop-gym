export function ShippingDeadlineStrip() {
  return (
    <section className="shipping-deadline-strip" role="region" aria-label="Shipping deadline">
      <div className="shipping-deadline-strip-inner">
        <span className="shipping-deadline-icon" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 16V7h13v9" />
            <path d="M16 10h4l1 6h-5z" />
            <circle cx="7" cy="18" r="2" />
            <circle cx="18" cy="18" r="2" />
          </svg>
        </span>
        <p className="shipping-deadline-text">
          <strong>Order by May 8</strong> for guaranteed Mother's Day delivery —
          free standard shipping on orders over $75.
        </p>
      </div>
    </section>
  );
}
