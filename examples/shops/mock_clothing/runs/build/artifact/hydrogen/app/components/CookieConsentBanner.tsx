import {useEffect, useState} from 'react';

const STORAGE_KEY = 'cookie-consent-accepted';

export function CookieConsentBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (!stored) {
      const t = window.setTimeout(() => setVisible(true), 800);
      return () => window.clearTimeout(t);
    }
  }, []);

  if (!visible) return null;

  const accept = () => {
    window.localStorage.setItem(STORAGE_KEY, 'accepted');
    setVisible(false);
  };

  const dismiss = () => {
    window.localStorage.setItem(STORAGE_KEY, 'dismissed');
    setVisible(false);
  };

  return (
    <div
      className="cookie-consent-banner"
      role="region"
      aria-label="Cookie preferences"
    >
      <div className="cookie-consent-inner">
        <p className="cookie-consent-text">
          We use cookies to personalise your experience and analyse site usage.
          See our{' '}
          <a href="/policies/privacy-policy" className="cookie-consent-link">
            Privacy Policy
          </a>{' '}
          for details.
        </p>
        <div className="cookie-consent-actions">
          <button
            type="button"
            className="cookie-consent-dismiss"
            onClick={dismiss}
          >
            Dismiss
          </button>
          <button
            type="button"
            className="cookie-consent-accept"
            onClick={accept}
          >
            Accept All
          </button>
        </div>
      </div>
    </div>
  );
}
