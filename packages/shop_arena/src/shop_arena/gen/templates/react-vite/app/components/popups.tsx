import {useEffect, useRef, useState, type FormEvent} from 'react';
import {Link} from 'react-router';
import type {Policy, Shop} from '~/lib/types';

const COOKIE_CONSENT_STORAGE_KEY = 'shopGymCookieConsentV1';
const SUBSCRIBE_POPUP_STORAGE_KEY = 'shopGymSubscribePopupDismissedV1';

type ActivePopup = 'checking' | 'cookie' | 'subscribe' | 'none';
type CookieChoice = 'accepted' | 'declined';

export function CustomerPopups({
  shop,
  policies,
}: {
  readonly shop: Shop;
  readonly policies: readonly Policy[];
}) {
  const [activePopup, setActivePopup] = useState<ActivePopup>('checking');
  const privacyPolicy =
    policies.find((policy) => policy.handle === 'privacy-policy') ?? null;

  useEffect(() => {
    setActivePopup(nextPopup());
  }, []);

  function chooseCookie(choice: CookieChoice) {
    writeStoredValue(COOKIE_CONSENT_STORAGE_KEY, choice);
    setActivePopup(
      hasStoredValue(SUBSCRIBE_POPUP_STORAGE_KEY) ? 'none' : 'subscribe',
    );
  }

  function dismissSubscribe(value = 'dismissed') {
    writeStoredValue(SUBSCRIBE_POPUP_STORAGE_KEY, value);
    setActivePopup('none');
  }

  if (activePopup === 'cookie') {
    return (
      <CookieConsentPopup
        privacyPolicy={privacyPolicy}
        onChoice={chooseCookie}
      />
    );
  }

  if (activePopup === 'subscribe') {
    return <SubscribePopup shop={shop} onDismiss={dismissSubscribe} />;
  }

  return null;
}

function CookieConsentPopup({
  privacyPolicy,
  onChoice,
}: {
  readonly privacyPolicy: Policy | null;
  readonly onChoice: (choice: CookieChoice) => void;
}) {
  return (
    <section
      className="cookie-popup"
      role="dialog"
      aria-labelledby="cookie-popup-title"
      aria-describedby="cookie-popup-description"
    >
      <div className="stack">
        <div>
          <h2 id="cookie-popup-title">Cookie preferences</h2>
          <p id="cookie-popup-description">
            We use essential cookies to keep cart and session features
            working. Optional cookies help remember storefront preferences.
          </p>
        </div>
        {privacyPolicy ? (
          <Link to={`/policies/${privacyPolicy.handle}`}>Privacy policy</Link>
        ) : null}
      </div>
      <div className="popup-actions">
        <button
          type="button"
          className="secondary-button"
          onClick={() => onChoice('declined')}
        >
          Decline optional
        </button>
        <button type="button" onClick={() => onChoice('accepted')}>
          Accept
        </button>
      </div>
    </section>
  );
}

function SubscribePopup({
  shop,
  onDismiss,
}: {
  readonly shop: Shop;
  readonly onDismiss: (value?: string) => void;
}) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onDismiss('subscribed');
  }

  useEffect(() => {
    const activeElement = document.activeElement;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onDismiss();
      }
    }

    closeButtonRef.current?.focus({preventScroll: true});
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      if (activeElement instanceof HTMLElement) {
        activeElement.focus({preventScroll: true});
      }
    };
  }, [onDismiss]);

  return (
    <div className="subscribe-popup">
      <button
        type="button"
        className="subscribe-backdrop"
        aria-label="Close subscribe popup"
        onClick={() => onDismiss()}
      />
      <section
        className="subscribe-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="subscribe-popup-title"
        aria-describedby="subscribe-popup-description"
      >
        <div className="subscribe-dialog-header">
          <p className="eyebrow">{shop.name}</p>
          <button
            type="button"
            className="secondary-button"
            ref={closeButtonRef}
            onClick={() => onDismiss()}
          >
            Close
          </button>
        </div>
        <div className="stack">
          <h2 id="subscribe-popup-title">Subscribe for updates</h2>
          <p id="subscribe-popup-description">
            Get product notes, collection updates, and storefront news from
            {` ${shop.name}`}.
          </p>
        </div>
        <form className="subscribe-form" onSubmit={handleSubmit}>
          <label>
            Email
            <input
              type="email"
              name="email"
              autoComplete="email"
              placeholder="you@example.com"
              required
            />
          </label>
          <div className="popup-actions">
            <button type="submit">Subscribe</button>
            <Link
              className="button-link secondary-button"
              to="/collections"
              onClick={() => onDismiss()}
            >
              Shop collections
            </Link>
          </div>
        </form>
        <div className="popup-actions">
          <button
            type="button"
            className="text-button"
            onClick={() => onDismiss()}
          >
            Not now
          </button>
        </div>
      </section>
    </div>
  );
}

function nextPopup(): ActivePopup {
  if (!hasStoredValue(COOKIE_CONSENT_STORAGE_KEY)) return 'cookie';
  if (!hasStoredValue(SUBSCRIBE_POPUP_STORAGE_KEY)) return 'subscribe';
  return 'none';
}

function hasStoredValue(key: string): boolean {
  try {
    return window.localStorage.getItem(key) !== null;
  } catch {
    return false;
  }
}

function writeStoredValue(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // The popup can still be dismissed for the current page view.
  }
}
