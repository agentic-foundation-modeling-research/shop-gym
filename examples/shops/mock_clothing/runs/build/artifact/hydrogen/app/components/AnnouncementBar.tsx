import {useState} from 'react';

const MESSAGES = [
  '15% off sitewide with code SOFTLIFE15',
  'Free shipping on orders over $75 · Free returns within 30 days',
];

export function AnnouncementBar() {
  const [paused, setPaused] = useState(false);

  return (
    <div
      className="announcement-bar"
      role="region"
      aria-label="Site announcements"
    >
      <div
        className={`announcement-bar-track${paused ? ' is-paused' : ''}`}
        aria-live="polite"
      >
        <div className="announcement-bar-marquee" aria-hidden={paused}>
          {[0, 1].map((repeat) => (
            <div className="announcement-bar-set" key={repeat}>
              {MESSAGES.map((message, idx) => (
                <span
                  className="announcement-bar-item"
                  key={`${repeat}-${idx}`}
                >
                  <span className="announcement-bar-dot" aria-hidden="true" />
                  {message}
                </span>
              ))}
            </div>
          ))}
        </div>
      </div>
      <button
        type="button"
        className="announcement-bar-pause"
        onClick={() => setPaused((p) => !p)}
        aria-label={paused ? 'Resume announcements' : 'Pause announcements'}
        aria-pressed={paused}
      >
        {paused ? <PlayIcon /> : <PauseIcon />}
      </button>
    </div>
  );
}

function PauseIcon() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="currentColor"
      aria-hidden="true"
    >
      <rect x="2.5" y="2" width="2.5" height="8" rx="0.5" />
      <rect x="7" y="2" width="2.5" height="8" rx="0.5" />
    </svg>
  );
}

function PlayIcon() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M3 2l7 4-7 4V2z" />
    </svg>
  );
}
