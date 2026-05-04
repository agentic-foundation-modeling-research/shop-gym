import {useEffect, useState} from 'react';
import {Link} from 'react-router';

const STORAGE_KEY = 'announcement-dismissed-v1';

export function AnnouncementBar() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const dismissed = window.localStorage.getItem(STORAGE_KEY);
    if (!dismissed) setVisible(true);
  }, []);

  if (!visible) return null;

  return (
    <div className="announcement-bar" role="region" aria-label="Promotion">
      <div className="announcement-bar-inner">
        <span className="announcement-bar-message">
          Free shipping on orders over $75
        </span>
        <span className="announcement-bar-divider" aria-hidden="true">
          |
        </span>
        <Link
          className="announcement-bar-link"
          to="/collections/sale"
          prefetch="intent"
        >
          Shop the Sale →
        </Link>
        <button
          className="announcement-bar-close"
          aria-label="Dismiss announcement"
          onClick={() => {
            window.localStorage.setItem(STORAGE_KEY, '1');
            setVisible(false);
          }}
        >
          ×
        </button>
      </div>
    </div>
  );
}
