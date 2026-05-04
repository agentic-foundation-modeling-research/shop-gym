import {useEffect, useState} from 'react';

const STORAGE_KEY = 'cookie-consent-accepted';

export function CookieConsentBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    try {
      if (window.localStorage.getItem(STORAGE_KEY) !== 'true') {
        setVisible(true);
      }
    } catch {
      /* localStorage may be unavailable; render nothing */
    }
  }, []);

  function dismiss() {
    setVisible(false);
    try {
      window.localStorage.setItem(STORAGE_KEY, 'true');
    } catch {
      /* ignore */
    }
  }

  if (!visible) return null;

  return (
    <div className="cookie-banner" role="dialog" aria-label="Cookie consent">
      <div className="cookie-banner-inner">
        <p className="cookie-banner-text">
          We use cookies to improve your experience, analyze site traffic, and
          serve personalized content. By clicking “Accept All,” you consent to
          our use of cookies.
        </p>
        <div className="cookie-banner-actions">
          <button
            type="button"
            className="cookie-banner-btn cookie-banner-btn-secondary"
            onClick={dismiss}
          >
            Dismiss
          </button>
          <button
            type="button"
            className="cookie-banner-btn cookie-banner-btn-primary"
            onClick={dismiss}
          >
            Accept All
          </button>
        </div>
      </div>
    </div>
  );
}
