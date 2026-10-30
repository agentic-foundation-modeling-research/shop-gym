import { useId, useState } from 'react';
import type { DiscountCodeHint } from '~/lib/types';

/**
 * Dawn's announcement bar, a full-width strip above the header with one
 * slide for each Discount code, "<code> - <hint>", in Dataset order. With
 * two or more codes it is the "Announcement bar" carousel: only the current
 * slide shows, named "<n> of <total>", and the "Previous announcement" and
 * "Next announcement" arrows go round the slides. It starts at the first
 * code and never moves by itself. The root keys it by path, so each page
 * starts again at the first code, as a full page load does in Dawn. One
 * code shows as a plain "Announcement" region with no arrows; with no
 * codes there is no bar.
 */
export function AnnouncementBar({ hints }: { readonly hints: readonly DiscountCodeHint[] }) {
  const sliderId = useId();
  const [current, setCurrent] = useState(0);
  const [first] = hints;
  if (first === undefined) return null;
  if (hints.length === 1) {
    return (
      <section className="announcement-bar" aria-label="Announcement">
        <AnnouncementMessage hint={first} />
      </section>
    );
  }

  const move = (step: number) =>
    setCurrent((index) => (index + step + hints.length) % hints.length);
  return (
    <section
      className="announcement-bar"
      aria-roledescription="Carousel"
      aria-label="Announcement bar"
    >
      <button
        type="button"
        className="announcement-arrow"
        aria-label="Previous announcement"
        aria-controls={sliderId}
        onClick={() => move(-1)}
      >
        <CaretIcon className="announcement-caret-previous" />
      </button>
      <div id={sliderId} className="announcement-slider" aria-live="polite" aria-atomic="true">
        {hints.map((hint, index) => (
          <div
            key={hint.code}
            // biome-ignore lint/a11y/useSemanticElements: Dawn's slide is a group, not a form fieldset
            role="group"
            aria-roledescription="Announcement"
            aria-label={`${index + 1} of ${hints.length}`}
            hidden={index !== current}
          >
            <AnnouncementMessage hint={hint} />
          </div>
        ))}
      </div>
      <button
        type="button"
        className="announcement-arrow"
        aria-label="Next announcement"
        aria-controls={sliderId}
        onClick={() => move(1)}
      >
        <CaretIcon className="announcement-caret-next" />
      </button>
    </section>
  );
}

function AnnouncementMessage({ hint }: { readonly hint: DiscountCodeHint }) {
  return <p className="announcement-message">{`${hint.code} - ${hint.hint}`}</p>;
}

/** Dawn's caret, which points down; `className` turns it to the left or the right. */
function CaretIcon({ className }: { readonly className: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 10 6"
      width="10"
      height="6"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}
