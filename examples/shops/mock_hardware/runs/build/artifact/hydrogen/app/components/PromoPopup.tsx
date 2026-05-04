import {useEffect, useState} from 'react';
import {useFetcher, useLocation} from 'react-router';

const STORAGE_KEY = 'promo-popup-dismissed';
const DELAY_MS = 5000;

export function PromoPopup() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const fetcher = useFetcher<{ok: boolean}>();

  useEffect(() => {
    if (location.pathname !== '/') return;
    try {
      if (window.localStorage.getItem(STORAGE_KEY) === 'true') return;
    } catch {
      return;
    }
    const id = window.setTimeout(() => setOpen(true), DELAY_MS);
    return () => window.clearTimeout(id);
  }, [location.pathname]);

  useEffect(() => {
    if (fetcher.data?.ok) {
      setSubmitted(true);
      const id = window.setTimeout(() => dismiss(), 1800);
      return () => window.clearTimeout(id);
    }
  }, [fetcher.data]);

  function dismiss() {
    setOpen(false);
    try {
      window.localStorage.setItem(STORAGE_KEY, 'true');
    } catch {
      /* ignore */
    }
  }

  if (!open) return null;

  return (
    <div
      className="promo-popup-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="promo-popup-heading"
      onClick={dismiss}
    >
      <div
        className="promo-popup"
        onClick={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          className="promo-popup-close"
          aria-label="Close popup"
          onClick={dismiss}
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>

        {submitted ? (
          <div className="promo-popup-success">
            <h2 className="promo-popup-heading" id="promo-popup-heading">
              Thank you!
            </h2>
            <p className="promo-popup-subhead">
              Check your inbox for your 10% off welcome code.
            </p>
          </div>
        ) : (
          <>
            <p className="promo-popup-eyebrow">Welcome offer</p>
            <h2 className="promo-popup-heading" id="promo-popup-heading">
              Get 10% Off Your First Order
            </h2>
            <p className="promo-popup-subhead">
              Sign up for hardware tips, new product drops, and exclusive deals.
            </p>
            <fetcher.Form
              method="post"
              action="/api/klaviyo"
              className="promo-popup-form"
            >
              <label htmlFor="promo-popup-email" className="sr-only">
                Email address
              </label>
              <input
                id="promo-popup-email"
                type="email"
                name="email"
                placeholder="Enter your email"
                required
                className="promo-popup-input"
              />
              <button
                type="submit"
                className="promo-popup-submit"
                disabled={fetcher.state !== 'idle'}
              >
                {fetcher.state !== 'idle' ? 'Signing up…' : 'Sign Up'}
              </button>
            </fetcher.Form>
            <button
              type="button"
              className="promo-popup-decline"
              onClick={dismiss}
            >
              No thanks
            </button>
          </>
        )}
      </div>
    </div>
  );
}
