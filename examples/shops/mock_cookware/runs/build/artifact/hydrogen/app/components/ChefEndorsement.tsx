import {useState} from 'react';

export function ChefEndorsement() {
  const [open, setOpen] = useState(false);

  return (
    <section className="chef-endorsement" aria-label="Chef endorsement">
      <div className="section-container chef-endorsement-grid">
        <button
          type="button"
          className="chef-endorsement-video"
          onClick={() => setOpen(true)}
          aria-label="Play chef testimonial video"
        >
          <span className="chef-endorsement-thumb" aria-hidden="true">
            <img
              src="/images/homepage-chef-endorsement.png"
              alt=""
              loading="lazy"
              decoding="async"
            />
          </span>
          <span className="chef-endorsement-play" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
              <path d="M8 5l11 7-11 7V5z" />
            </svg>
          </span>
        </button>
        <div className="chef-endorsement-copy">
          <p className="section-eyebrow accent">Chef Endorsed</p>
          <blockquote className="chef-endorsement-quote">
            “These pans hold heat the way a restaurant range does. I’ve put
            them through every shift on my line and they keep showing up.”
          </blockquote>
          <p className="chef-endorsement-attribution">
            <strong>A working chef</strong>
            <span>Restaurant kitchen</span>
          </p>
          <div className="chef-endorsement-rating" role="img" aria-label="4.8 out of 5 from 12,000 reviews">
            <span className="chef-endorsement-stars" aria-hidden="true">
              ★★★★★
            </span>
            <span className="chef-endorsement-rating-text">
              4.8 / 5 from 12,000+ verified reviews
            </span>
          </div>
        </div>
      </div>
      {open && (
        <div
          className="video-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Chef testimonial video"
          onClick={() => setOpen(false)}
        >
          <button
            type="button"
            className="video-modal-close"
            onClick={() => setOpen(false)}
            aria-label="Close video"
          >
            ×
          </button>
          <div
            className="video-modal-frame"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="video-modal-placeholder">
              <p>A working chef — On the line</p>
              <p className="video-modal-note">
                (Video playback unavailable in demo store)
              </p>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
