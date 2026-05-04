import {useEffect, useState} from 'react';

const STORAGE_KEY = 'cookie-consent-accepted';

export function CookieConsentBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (!stored) setVisible(true);
    } catch {
      setVisible(true);
    }
  }, []);

  function dismiss(value: 'accepted' | 'dismissed') {
    try {
      window.localStorage.setItem(STORAGE_KEY, value);
    } catch {
      // storage disabled — we still hide the banner
    }
    setVisible(false);
  }

  if (!visible) return null;

  return (
    <div
      className="cookie-banner"
      role="region"
      aria-label="Cookie preferences"
    >
      <div className="cookie-banner-inner">
        <div className="cookie-banner-text">
          <strong className="cookie-banner-title">We use cookies</strong>
          <p className="cookie-banner-description">
            We use cookies to remember your cart, improve our store, and
            personalize what you see. Read our{' '}
            <a href="/policies/privacy-policy" className="cookie-banner-link">
              Privacy Policy
            </a>
            .
          </p>
        </div>
        <div className="cookie-banner-actions">
          <button
            type="button"
            className="cookie-banner-btn cookie-banner-btn-secondary"
            onClick={() => dismiss('dismissed')}
          >
            Dismiss
          </button>
          <button
            type="button"
            className="cookie-banner-btn cookie-banner-btn-primary"
            onClick={() => dismiss('accepted')}
          >
            Accept All
          </button>
        </div>
      </div>
    </div>
  );
}
