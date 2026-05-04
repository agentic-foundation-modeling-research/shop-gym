import {useEffect} from 'react';
import {Money} from '@shopify/hydrogen';
import type {MoneyV2} from '@shopify/hydrogen/storefront-api-types';

export function FinancingModal({
  open,
  onClose,
  price,
}: {
  open: boolean;
  onClose: () => void;
  price?: MoneyV2;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const installmentAmount = price
    ? {
        amount: (parseFloat(price.amount) / 4).toFixed(2),
        currencyCode: price.currencyCode,
      }
    : undefined;

  return (
    <div className="pdp-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="pdp-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="financing-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="pdp-modal-header">
          <h2 id="financing-title" className="pdp-modal-title">
            Check your purchase power
          </h2>
          <button
            type="button"
            className="pdp-modal-close"
            aria-label="Close financing details"
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <div className="pdp-modal-body">
          <p>
            Spread the cost across 4 interest-free payments or finance over 6 to
            12 months. Eligibility decisions appear in seconds with no impact to
            your credit score.
          </p>
          {installmentAmount ? (
            <div className="pdp-financing-row">
              <span>4 payments of</span>
              <strong>
                <Money data={installmentAmount} />
              </strong>
            </div>
          ) : null}
          <ul className="pdp-financing-points">
            <li>No hidden fees or compounding interest.</li>
            <li>Approval decisions are soft-pull only.</li>
            <li>Pay any installment early with no penalty.</li>
          </ul>
          <p className="pdp-financing-disclosure">
            Subject to approval by our financing partner. Terms vary by region.
          </p>
        </div>
      </div>
    </div>
  );
}
