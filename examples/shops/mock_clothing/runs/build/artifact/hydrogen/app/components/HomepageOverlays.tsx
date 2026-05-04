import {useEffect, useState} from 'react';

export function HomepageOverlays() {
  return (
    <>
      <FreeShippingBadge />
      <LiveChatWidget />
      <ScrollToTopButton />
    </>
  );
}

function FreeShippingBadge() {
  const [hidden, setHidden] = useState(true);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const stored = window.sessionStorage.getItem('mock-apparel:shipping-badge');
    if (stored === 'dismissed') {
      setDismissed(true);
    } else {
      setHidden(false);
    }
  }, []);

  if (hidden || dismissed) return null;

  const dismiss = () => {
    window.sessionStorage.setItem('mock-apparel:shipping-badge', 'dismissed');
    setDismissed(true);
  };

  return (
    <div className="floating-shipping" role="status" aria-live="polite">
      <span className="floating-shipping-icon" aria-hidden="true">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 16V7h13v9" />
          <path d="M16 10h4l1 6h-5z" />
          <circle cx="7" cy="18" r="2" />
          <circle cx="18" cy="18" r="2" />
        </svg>
      </span>
      <span className="floating-shipping-text">
        <strong>Free shipping</strong> on orders over $75
      </span>
      <button
        type="button"
        className="floating-shipping-dismiss"
        onClick={dismiss}
        aria-label="Dismiss free shipping reminder"
      >
        ×
      </button>
    </div>
  );
}

function LiveChatWidget() {
  const [open, setOpen] = useState(false);
  return (
    <div className="floating-chat-wrapper">
      {open ? (
        <div className="floating-chat-panel" role="dialog" aria-label="Live chat">
          <div className="floating-chat-header">
            <span className="floating-chat-title">We're here to help</span>
            <button
              type="button"
              className="floating-chat-close"
              onClick={() => setOpen(false)}
              aria-label="Close chat"
            >
              ×
            </button>
          </div>
          <div className="floating-chat-body">
            <p className="floating-chat-message">
              Hi! Our concierge team is online from 9am–8pm GMT. Drop us a note
              and we'll reply right away.
            </p>
            <textarea
              className="floating-chat-input"
              placeholder="Type your message…"
              rows={3}
            />
            <button type="button" className="btn btn-primary floating-chat-send">
              Send
            </button>
          </div>
        </div>
      ) : null}
      <button
        type="button"
        className="floating-chat-fab"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={open ? 'Close chat' : 'Open chat'}
      >
        <svg
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M21 15a4 4 0 0 1-4 4H8l-5 4V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z" />
        </svg>
        <span className="floating-chat-label">Chat with Us</span>
      </button>
    </div>
  );
}

function ScrollToTopButton() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const handler = () => setVisible(window.scrollY > 400);
    handler();
    window.addEventListener('scroll', handler, {passive: true});
    return () => window.removeEventListener('scroll', handler);
  }, []);

  if (!visible) return null;

  return (
    <button
      type="button"
      className="floating-scroll-top"
      aria-label="Scroll back to top"
      onClick={() => window.scrollTo({top: 0, behavior: 'smooth'})}
    >
      ↑
    </button>
  );
}

