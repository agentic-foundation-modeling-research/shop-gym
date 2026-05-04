import {useEffect, useState} from 'react';

const OPTIONS = [
  {id: 'bag', label: 'Signature gift bag', price: 6, copy: 'Cotton-handle gift bag with tissue.'},
  {id: 'box', label: 'Gift box', price: 12, copy: 'Hard-shell box with magnetic closure.'},
  {id: 'card', label: 'Personalised card', price: 4, copy: 'Hand-finished card with your message.'},
];

export function GiftPackagingDrawer({
  productTitle,
  onClose,
}: {
  productTitle: string;
  onClose: () => void;
}) {
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const total = OPTIONS.reduce(
    (sum, o) => (selected[o.id] ? sum + o.price : sum),
    0,
  );

  return (
    <div
      className="pdp-gift-drawer-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Gift packaging options"
      onClick={onClose}
    >
      <aside
        className="pdp-gift-drawer"
        onClick={(e) => e.stopPropagation()}
        role="presentation"
      >
        <header className="pdp-gift-drawer-head">
          <p className="pdp-gift-drawer-eyebrow">Added to bag</p>
          <h2 className="pdp-gift-drawer-title">Make it a gift?</h2>
          <button
            type="button"
            className="pdp-gift-drawer-close"
            onClick={onClose}
            aria-label="Close gift packaging options"
          >
            ×
          </button>
        </header>
        <p className="pdp-gift-drawer-sub">
          Add finishing touches to{' '}
          <span className="pdp-gift-drawer-product">{productTitle}</span> before
          checkout.
        </p>
        <ul className="pdp-gift-drawer-options">
          {OPTIONS.map((option) => {
            const isOn = !!selected[option.id];
            return (
              <li
                key={option.id}
                className={`pdp-gift-drawer-option${isOn ? ' is-on' : ''}`}
              >
                <button
                  type="button"
                  className="pdp-gift-drawer-option-btn"
                  onClick={() =>
                    setSelected((prev) => ({...prev, [option.id]: !prev[option.id]}))
                  }
                  aria-pressed={isOn}
                >
                  <span className="pdp-gift-drawer-option-check" aria-hidden="true">
                    {isOn ? '✓' : ''}
                  </span>
                  <span className="pdp-gift-drawer-option-text">
                    <span className="pdp-gift-drawer-option-label">
                      {option.label}
                    </span>
                    <span className="pdp-gift-drawer-option-copy">
                      {option.copy}
                    </span>
                  </span>
                  <span className="pdp-gift-drawer-option-price">
                    +${option.price.toFixed(2)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        <footer className="pdp-gift-drawer-foot">
          <div className="pdp-gift-drawer-total">
            <span>Add-on total</span>
            <span>${total.toFixed(2)}</span>
          </div>
          <button
            type="button"
            className="btn btn-primary pdp-gift-drawer-confirm"
            onClick={onClose}
          >
            View Bag
          </button>
          <button
            type="button"
            className="pdp-gift-drawer-skip"
            onClick={onClose}
          >
            No thanks, continue shopping
          </button>
        </footer>
      </aside>
    </div>
  );
}
