/**
 * @fileoverview Button-styled-as-link primitive for nav triggers.
 *
 * A `<button>` that asserts the typographic-reset rules ordinarily
 * supplied by `app/styles/reset.css` (`template_baseline_fixes` P3)
 * inline, so the trigger looks identical to neighboring `<a>`-based
 * nav links even when the global reset has not yet been applied.
 *
 * Owns the popover-trigger ARIA contract
 * (`aria-haspopup`, `aria-expanded`, `aria-controls`) so consumers
 * cannot drift into a partially-correct accessibility shape.
 *
 * See `docs/specs/shop_arena/template_navigation_primitives.md` (N2)
 * for the design rationale and `outputs/shops_fix/` shop-ui-fixes #8
 * for the bug class this primitive eliminates.
 */

import {forwardRef} from 'react';
import type {ButtonHTMLAttributes, CSSProperties, ForwardedRef} from 'react';

/**
 * Inline style enforcing the button-as-link reset.
 *
 * Mirrors the rule in `app/styles/reset.css`
 * (`template_baseline_fixes` P3); applied inline so the primitive
 * works in template trees where P3 has not yet landed and so the
 * reset survives stylesheet ordering accidents in consumer CSS.
 */
const TRIGGER_RESET_STYLE: CSSProperties = {
  font: 'inherit',
  lineHeight: 'inherit',
  color: 'inherit',
  background: 'transparent',
  border: 0,
  padding: 0,
  cursor: 'pointer',
};

/**
 * Props for {@link NavTrigger}.
 *
 * Extends the standard `<button>` attribute set with the two
 * popover-state inputs the primitive needs to assemble its ARIA
 * contract.
 *
 * `aria-haspopup`, `aria-expanded`, and `aria-controls` are owned
 * by the primitive — passing them as overrides is unsupported by
 * design.
 */
export interface NavTriggerProps
  extends Omit<
    ButtonHTMLAttributes<HTMLButtonElement>,
    'aria-haspopup' | 'aria-expanded' | 'aria-controls'
  > {
  /** Whether the popover this trigger controls is currently open. */
  readonly open: boolean;
  /**
   * `id` of the popover element this trigger controls. Used for
   * `aria-controls`; consumers should set the same value on the
   * popover content's `id`.
   */
  readonly menuId: string;
}

/**
 * Button primitive for nav-row triggers (dropdowns, mega menus).
 *
 * Renders a `<button type="button">` with the typographic reset
 * applied inline and the popover-trigger ARIA attributes wired from
 * `open` and `menuId`. Forwards `ref` to the underlying `<button>`
 * so consumers can integrate with focus management, popover
 * positioning libraries, and imperative-focus patterns.
 *
 * Consumer-provided `style` is merged with the reset; the reset
 * properties take precedence so the visual baseline cannot drift.
 *
 * @example
 * ```tsx
 * const {open, triggerProps} = useHoverIntent();
 * const menuId = useId();
 * <div {...triggerProps}>
 *   <NavTrigger open={open} menuId={menuId}>Shop</NavTrigger>
 *   {open ? <ul id={menuId}>…</ul> : null}
 * </div>
 * ```
 */
export const NavTrigger = forwardRef<HTMLButtonElement, NavTriggerProps>(
  function NavTrigger(
    {open, menuId, type, style, children, ...rest}: NavTriggerProps,
    ref: ForwardedRef<HTMLButtonElement>,
  ) {
    return (
      <button
        {...rest}
        ref={ref}
        type={type ?? 'button'}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        style={style ? {...style, ...TRIGGER_RESET_STYLE} : TRIGGER_RESET_STYLE}
      >
        {children}
      </button>
    );
  },
);
