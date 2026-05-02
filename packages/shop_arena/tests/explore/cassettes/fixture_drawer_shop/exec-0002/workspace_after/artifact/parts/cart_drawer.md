# cart_drawer

The shop renders a slide-in cart drawer anchored to the right viewport
edge. Three observed states:

1. **Empty.** Headline "Your cart is empty" plus a CTA back to the
   featured collection. No line items rendered.
2. **Filled.** Each line item shows thumbnail, title, variant pills,
   quantity stepper, line subtotal, and a remove control. A promo-code
   text input sits above the totals block. An "Often bought together"
   row offers two upsell tiles.
3. **Quantity change.** The stepper updates the line subtotal and the
   drawer total inline without a full reload.

Shipping is not estimated in the drawer; that surface is reached only
from the dedicated `/cart` page.
