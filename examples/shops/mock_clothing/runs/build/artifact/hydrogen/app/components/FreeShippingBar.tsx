import {useEffect, useState} from 'react';
import type {ProductFragment} from 'storefrontapi.generated';

const THRESHOLD = 75;

export function FreeShippingBar({
  selectedVariant,
}: {
  selectedVariant: ProductFragment['selectedOrFirstAvailableVariant'];
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  if (!mounted || !selectedVariant?.price) return null;

  const amount = parseFloat(selectedVariant.price.amount);
  const remaining = Math.max(0, THRESHOLD - amount);
  const progress = Math.min(100, (amount / THRESHOLD) * 100);
  const qualifies = amount >= THRESHOLD;

  return (
    <div className="pdp-free-ship-bar" aria-live="polite">
      <div className="pdp-free-ship-bar-inner">
        <span className="pdp-free-ship-bar-text">
          {qualifies
            ? '🎁 You qualify for complimentary shipping'
            : `Add $${remaining.toFixed(0)} for complimentary shipping`}
        </span>
        <span className="pdp-free-ship-bar-track" aria-hidden="true">
          <span
            className="pdp-free-ship-bar-fill"
            style={{width: `${progress}%`}}
          />
        </span>
      </div>
    </div>
  );
}
