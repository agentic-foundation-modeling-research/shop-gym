export function TrustBadges() {
  return (
    <ul className="trust-badges" aria-label="Shipping and returns">
      <li className="trust-badge">
        <svg
          className="trust-badge-icon"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 7h11v9H3z" />
          <path d="M14 10h4l3 3v3h-7" />
          <circle cx="7" cy="17" r="1.8" />
          <circle cx="17" cy="17" r="1.8" />
        </svg>
        <span>Free shipping on orders $99+</span>
      </li>
      <li className="trust-badge">
        <svg
          className="trust-badge-icon"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 12a9 9 0 1 0 3-6.7" />
          <polyline points="3 4 3 9 8 9" />
        </svg>
        <span>Free 30-day returns</span>
      </li>
    </ul>
  );
}
