import {useState} from 'react';

export function TrustBadges({hasLifetimeWarranty}: {hasLifetimeWarranty: boolean}) {
  const [claimsOpen, setClaimsOpen] = useState(false);
  return (
    <div className="pdp-trust-badges">
      <div className="pdp-trust-badge">
        <ShipIcon />
        <span>Free shipping over $75</span>
      </div>
      <div className="pdp-trust-badge">
        <ReturnIcon />
        <span>30-day returns</span>
      </div>
      {hasLifetimeWarranty && (
        <div className="pdp-trust-badge">
          <ShieldIcon />
          <span>Lifetime warranty</span>
        </div>
      )}
      <button
        type="button"
        className="pdp-trust-claims"
        aria-expanded={claimsOpen}
        onClick={() => setClaimsOpen((v) => !v)}
      >
        Chemical-safety attributes
        <span className={`pdp-trust-claims-arrow${claimsOpen ? ' is-open' : ''}`}>
          ▾
        </span>
      </button>
      {claimsOpen && (
        <ul className="pdp-trust-claims-list">
          <li>PFOA-free coating</li>
          <li>PTFE-free interior</li>
          <li>No lead, cadmium, or heavy metals</li>
          <li>Food-contact safe at high temperatures</li>
          <li>Tested to FDA and Prop 65 standards</li>
        </ul>
      )}
    </div>
  );
}

function ShipIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3 7h11v9H3z" />
      <path d="M14 10h4l3 4v2h-7" />
      <circle cx="7" cy="18" r="2" />
      <circle cx="17" cy="18" r="2" />
    </svg>
  );
}

function ReturnIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 4v5h5" />
    </svg>
  );
}

function ShieldIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 3l8 3v6c0 5-4 8-8 9-4-1-8-4-8-9V6l8-3z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}
