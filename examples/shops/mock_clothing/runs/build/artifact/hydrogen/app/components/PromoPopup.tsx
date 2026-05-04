import {useEffect, useState} from 'react';
import {useLocation} from 'react-router';

const STORAGE_KEY = 'promo-popup-dismissed';
const SHOW_DELAY_MS = 5000;

export function PromoPopup() {
  const {pathname} = useLocation();
  const [visible, setVisible] = useState(false);
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (pathname !== '/') return;

    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === 'dismissed' || stored === 'subscribed') return;

    const t = window.setTimeout(() => setVisible(true), SHOW_DELAY_MS);
    return () => window.clearTimeout(t);
  }, [pathname]);

  const dismiss = () => {
    window.localStorage.setItem(STORAGE_KEY, 'dismissed');
    setVisible(false);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!email.trim() || submitting) return;
    setSubmitting(true);
    try {
      await fetch('/api/klaviyo', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email}),
      });
    } catch (err) {
      // Mock endpoint — failures are non-fatal.
      console.error('Klaviyo signup error', err);
    }
    window.localStorage.setItem(STORAGE_KEY, 'subscribed');
    setSubmitted(true);
    setSubmitting(false);
    window.setTimeout(() => setVisible(false), 2000);
  };

  if (!visible) return null;

  return (
    <div
      className="promo-popup-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="promo-popup-heading"
      onClick={dismiss}
    >
      <div
        className="promo-popup-card"
        onClick={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          className="promo-popup-close"
          aria-label="Close popup"
          onClick={dismiss}
        >
          ×
        </button>
        <span className="promo-popup-eyebrow">Subscriber exclusive</span>
        <h3 id="promo-popup-heading" className="promo-popup-heading">
          Get 10% Off Your First Order
        </h3>
        <p className="promo-popup-body">
          Sign up for the newsletter and we&rsquo;ll send your discount code
          straight to your inbox.
        </p>
        {submitted ? (
          <p className="promo-popup-success">
            Thanks! Check your inbox for your code.
          </p>
        ) : (
          <form className="promo-popup-form" onSubmit={submit}>
            <label className="sr-only" htmlFor="promo-popup-input">
              Email address
            </label>
            <input
              id="promo-popup-input"
              type="email"
              required
              placeholder="Your email address"
              className="promo-popup-input"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={submitting}
            />
            <button
              type="submit"
              className="promo-popup-submit"
              disabled={submitting}
            >
              {submitting ? 'Sending…' : 'Sign Up'}
            </button>
          </form>
        )}
        <button
          type="button"
          className="promo-popup-skip"
          onClick={dismiss}
        >
          No thanks
        </button>
      </div>
    </div>
  );
}
