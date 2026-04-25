# cart_drawer

The shop renders a slide-in cart drawer anchored to the right edge of
the viewport. Three observed states:

1. **Empty.** Title "Your bag is empty" plus a CTA back to the
   highlighted collection.
2. **Filled.** Each line item shows thumbnail, title, variant pills,
   quantity stepper, line subtotal, and a remove control.
3. **Upsell.** Below the line items the drawer shows a three-tile
   "You might also like" carousel sourced from a recommendations API.

A promo-code text input sits above the totals block. Shipping is not
estimated here — the dedicated `/cart` page surfaces that calculator.
