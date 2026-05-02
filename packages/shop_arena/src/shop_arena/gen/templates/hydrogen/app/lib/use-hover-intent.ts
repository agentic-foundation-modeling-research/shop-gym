/**
 * @fileoverview Hover-intent state hook for nav popovers.
 *
 * Owns the open/close state of a hover-driven popover (dropdown, mega
 * menu, fly-out) with a debounced close so the cursor can cross a
 * geometric gap between the trigger and the content without the
 * popover unmounting mid-traversal.
 *
 * See `docs/specs/shop_arena/template_navigation_primitives.md` (N3)
 * and `outputs/shops_fix/mock_hardware_issues_v1.md` (Issue 3) for
 * the bug class this primitive eliminates.
 */

import {useCallback, useEffect, useRef, useState} from 'react';

/**
 * Default close-delay for {@link useHoverIntent}.
 *
 * 120ms bridges typical 12–16px geometric gaps (sticky-header
 * padding, sub-menu offsets) without making intentional close feel
 * sticky to the user. Tune via the hook's `closeDelay` argument when
 * a specific surface needs a longer or shorter window.
 */
export const DEFAULT_HOVER_CLOSE_DELAY_MS = 120;

/**
 * Handler bundle to spread onto a hover-aware element.
 *
 * Both the trigger and the popover content receive the same handlers
 * so that crossing into either surface keeps the popover open.
 */
export interface HoverIntentHandlers {
  readonly onMouseEnter: () => void;
  readonly onMouseLeave: () => void;
}

/**
 * Return shape of {@link useHoverIntent}.
 */
export interface HoverIntentResult {
  /** Whether the popover should currently render as open. */
  readonly open: boolean;
  /** Handlers to spread onto the trigger element. */
  readonly triggerProps: HoverIntentHandlers;
  /** Handlers to spread onto the popover content element. */
  readonly contentProps: HoverIntentHandlers;
  /**
   * Imperative close. Use for click-driven dismissal — e.g. when a
   * link inside the popover is followed and the popover should close
   * without waiting for the hover-leave debounce.
   */
  readonly close: () => void;
}

/**
 * Debounced hover-intent state for nav triggers and overlay content.
 *
 * Spread {@link HoverIntentResult.triggerProps} onto the trigger
 * element and {@link HoverIntentResult.contentProps} onto the
 * popover content element. Cursor entering either surface opens the
 * popover and cancels any pending close. Cursor leaving either
 * surface schedules a close on a `closeDelay`-ms timer; the timer is
 * canceled the moment the cursor returns to either surface.
 *
 * The two handler bundles carry identical handlers — separate names
 * exist so that the two prop spreads stay readable when the trigger
 * and content are not in the same DOM subtree (e.g. portal-rendered
 * mega menus, or content positioned outside the trigger's wrapper to
 * span the full viewport width).
 *
 * The pending close timer is cleared on unmount.
 *
 * @param closeDelay - Milliseconds to wait before closing after the
 *   cursor leaves both surfaces. Defaults to
 *   {@link DEFAULT_HOVER_CLOSE_DELAY_MS}.
 * @returns Open state, two handler bundles, and an imperative
 *   `close()` for click-driven dismissal.
 *
 * @example
 * ```tsx
 * function ShopMenu() {
 *   const {open, triggerProps, contentProps, close} = useHoverIntent();
 *   const menuId = useId();
 *   return (
 *     <div {...triggerProps}>
 *       <NavTrigger open={open} menuId={menuId}>Shop</NavTrigger>
 *       {open ? (
 *         <MegaMenu id={menuId} {...contentProps} onNavigate={close} />
 *       ) : null}
 *     </div>
 *   );
 * }
 * ```
 */
export function useHoverIntent(
  closeDelay: number = DEFAULT_HOVER_CLOSE_DELAY_MS,
): HoverIntentResult {
  const [open, setOpen] = useState<boolean>(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancelClose = useCallback(() => {
    if (closeTimer.current !== null) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }, []);

  const handleEnter = useCallback(() => {
    cancelClose();
    setOpen(true);
  }, [cancelClose]);

  const handleLeave = useCallback(() => {
    cancelClose();
    closeTimer.current = setTimeout(() => {
      closeTimer.current = null;
      setOpen(false);
    }, closeDelay);
  }, [cancelClose, closeDelay]);

  const close = useCallback(() => {
    cancelClose();
    setOpen(false);
  }, [cancelClose]);

  // Clear any pending close timer on unmount so a parent that
  // unmounts the popover after the cursor leaves does not call
  // `setOpen` on a torn-down component.
  useEffect(() => cancelClose, [cancelClose]);

  return {
    open,
    triggerProps: {onMouseEnter: handleEnter, onMouseLeave: handleLeave},
    contentProps: {onMouseEnter: handleEnter, onMouseLeave: handleLeave},
    close,
  };
}
