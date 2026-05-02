/**
 * @fileoverview Dismissible announcement-bar primitive.
 *
 * Sticky bar rendered above the header that owns three concerns every
 * shop's announcement bar otherwise re-derives:
 *
 * 1. **Dismissal persistence** — a click on the close button writes a
 *    flag to `localStorage` so the dismissal survives reloads (and so
 *    the consumer doesn't ship an in-memory dismiss that re-appears on
 *    every navigation).
 * 2. **Message rotation** — when more than one message is supplied,
 *    the bar advances through them on a fixed interval (default 5s).
 * 3. **ARIA live-region** — declares `role="status"` so screen readers
 *    pick up rotation changes politely.
 *
 * Visibility is opt-out: the consumer hides the bar by not mounting
 * the component (or by passing an empty `messages` array). The
 * `SiteShell.has_announcement_bar` capability flag drives the mount
 * decision in `Header.tsx`.
 *
 * SSR-safe by construction: every `localStorage` and `setInterval`
 * call lives inside a `useEffect`, so the server-rendered HTML is
 * identical to the first client render — the dismissed state and the
 * rotation index only diverge from their initial values *after* the
 * effect has run on the client.
 *
 * See `docs/specs/shop_arena/template_navigation_primitives.md` §N7.
 */

import {useEffect, useState} from 'react';

/**
 * Default `localStorage` key used to persist the dismissal flag.
 *
 * Exported so consumers can clear the dismissal programmatically (e.g.
 * a "show announcement again" debug control) without re-deriving the
 * key string.
 */
export const DEFAULT_ANNOUNCEMENT_STORAGE_KEY = 'shop_announcement_dismissed';

/**
 * Default rotation interval, in milliseconds, between successive
 * messages when `messages.length > 1`.
 */
export const DEFAULT_ANNOUNCEMENT_ROTATION_MS = 5000;

/**
 * Sentinel value written to `localStorage` to mark the bar dismissed.
 *
 * The exact string is unimportant — only its presence is checked — but
 * fixing it as `'1'` keeps the storage payload small and matches the
 * convention used by `Aside` for similar UI flags.
 */
const DISMISSED_VALUE = '1';

/**
 * Props for {@link AnnouncementBar}.
 */
export interface AnnouncementBarProps {
  /**
   * Messages to display in the bar. When `length === 0` the component
   * renders `null`. When `length > 1` the bar rotates through them on
   * a fixed interval; when `length === 1` the bar is static.
   */
  readonly messages: readonly string[];
  /**
   * Optional click-through target. When set, the message is wrapped in
   * an `<a>` so the entire message (including the rotated content) is
   * clickable. The dismiss button remains a sibling, never nested
   * inside the link.
   */
  readonly href?: string;
  /**
   * `localStorage` key used to persist the dismissal. Override when a
   * shop runs multiple bar variants (e.g. a marketing bar and a
   * shipping-disclaimer bar) and each needs an independent dismissal.
   *
   * Defaults to {@link DEFAULT_ANNOUNCEMENT_STORAGE_KEY}.
   */
  readonly storageKey?: string;
}

/**
 * Renders a dismissible, optionally-rotating announcement bar.
 *
 * Consumer-owned styling lives behind the `.announcement-bar`,
 * `.announcement-bar-message`, and `.announcement-bar-dismiss` class
 * names — the primitive does not ship CSS (the spec splits structure
 * from styling: structure here, styling in the consumer's stylesheet).
 *
 * @example
 * ```tsx
 * <AnnouncementBar
 *   messages={['Free shipping over $50', 'New season specials']}
 *   href="/collections/new"
 * />
 * ```
 */
export function AnnouncementBar({
  messages,
  href,
  storageKey = DEFAULT_ANNOUNCEMENT_STORAGE_KEY,
}: AnnouncementBarProps) {
  // Both states default to values that produce a *server-safe* first
  // render (`dismissed: false`, `index: 0`); the effects below adopt
  // any client-only deltas after mount. This ordering is what keeps
  // the SSR markup byte-identical to the first client render and so
  // avoids hydration warnings.
  const [dismissed, setDismissed] = useState(false);
  const [index, setIndex] = useState(0);

  // Post-mount: pick up an existing dismissal from `localStorage`. The
  // storage read must not run at render time — see the SSR note above.
  useEffect(() => {
    try {
      if (window.localStorage.getItem(storageKey) === DISMISSED_VALUE) {
        setDismissed(true);
      }
    } catch {
      // `localStorage` access can throw in privacy modes / sandboxed
      // iframes; treat as "not dismissed" and move on.
    }
  }, [storageKey]);

  // Post-mount: rotate through `messages` when there is more than one
  // to display. Single-message and empty cases skip the interval
  // entirely so we don't waste a timer on a no-op.
  const messageCount = messages.length;
  useEffect(() => {
    if (messageCount <= 1) {
      return;
    }
    const id = window.setInterval(() => {
      setIndex((prev) => (prev + 1) % messageCount);
    }, DEFAULT_ANNOUNCEMENT_ROTATION_MS);
    return () => {
      window.clearInterval(id);
    };
  }, [messageCount]);

  if (dismissed || messageCount === 0) {
    return null;
  }

  // Defensive clamp: if `messages` shrinks below the current index
  // between renders (e.g. a parent swaps the array), fall back to 0
  // rather than rendering `undefined`. `noUncheckedIndexedAccess` in
  // the template's `tsconfig.base.json` makes this guard load-bearing.
  const safeIndex = index < messageCount ? index : 0;
  const current = messages[safeIndex] ?? '';

  const handleDismiss = () => {
    try {
      window.localStorage.setItem(storageKey, DISMISSED_VALUE);
    } catch {
      // See the read-side `try/catch` above — persistence is best-effort.
    }
    setDismissed(true);
  };

  const messageNode = href ? <a href={href}>{current}</a> : current;

  return (
    <div className="announcement-bar" role="status">
      <span className="announcement-bar-message">{messageNode}</span>
      <button
        type="button"
        className="announcement-bar-dismiss"
        aria-label="Dismiss announcement"
        onClick={handleDismiss}
      >
        ×
      </button>
    </div>
  );
}
