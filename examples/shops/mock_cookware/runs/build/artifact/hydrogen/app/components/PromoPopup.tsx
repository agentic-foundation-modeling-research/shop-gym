import {useEffect, useRef, useState, type FormEvent} from 'react';
import {useFetcher, useLocation} from 'react-router';

const STORAGE_KEY = 'promo-popup-dismissed';
const DELAY_MS = 5000;

export function PromoPopup() {
  const [visible, setVisible] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const fetcher = useFetcher<{ok: boolean}>();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const location = useLocation();

  useEffect(() => {
    if (location.pathname !== '/') return;

    let dismissed = false;
    try {
      dismissed = window.localStorage.getItem(STORAGE_KEY) === 'true';
    } catch {
      dismissed = false;
    }
    if (dismissed) return;

    const timer = window.setTimeout(() => setVisible(true), DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [location.pathname]);

  useEffect(() => {
    if (!visible) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') dismiss();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [visible]);

  useEffect(() => {
    if (visible) {
      const previous = document.activeElement as HTMLElement | null;
      dialogRef.current?.focus();
      return () => {
        previous?.focus?.();
      };
    }
  }, [visible]);

  function dismiss() {
    try {
      window.localStorage.setItem(STORAGE_KEY, 'true');
    } catch {
      // ignore storage errors
    }
    setVisible(false);
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const email = String(formData.get('email') || '').trim();
    if (!email || !/^\S+@\S+\.\S+$/.test(email)) return;
    fetcher.submit(formData, {method: 'POST', action: '/api/newsletter'});
    setSubmitted(true);
    window.setTimeout(() => dismiss(), 1500);
  }

  if (!visible) return null;

  return (
    <div className="promo-popup-overlay" role="presentation" onClick={dismiss}>
      <div
        ref={dialogRef}
        className="promo-popup"
        role="dialog"
        aria-modal="true"
        aria-labelledby="promo-popup-title"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className="promo-popup-close"
          onClick={dismiss}
          aria-label="Close offer"
        >
          ×
        </button>
        <p className="promo-popup-eyebrow">Welcome offer</p>
        <h2 id="promo-popup-title" className="promo-popup-title">
          Get 10% Off Your First Order
        </h2>
        <p className="promo-popup-body">
          Subscribe for recipes, care guides, and an instant 10% off code on
          your first cookware order.
        </p>
        {submitted ? (
          <p className="promo-popup-success" role="status">
            Thanks! Check your inbox for your code.
          </p>
        ) : (
          <form className="promo-popup-form" onSubmit={onSubmit} noValidate>
            <label htmlFor="promo-popup-email" className="sr-only">
              Email address
            </label>
            <input
              id="promo-popup-email"
              name="email"
              type="email"
              className="promo-popup-input"
              placeholder="contact@mock-shop.example"
              autoComplete="email"
              required
            />
            <button type="submit" className="promo-popup-submit">
              Sign Up
            </button>
          </form>
        )}
        <button
          type="button"
          className="promo-popup-dismiss"
          onClick={dismiss}
        >
          No thanks
        </button>
      </div>
    </div>
  );
}
