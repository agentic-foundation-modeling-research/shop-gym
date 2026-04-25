# cart_drawer

The shop renders a slide-in drawer anchored to the right edge of the
viewport when the user adds an item from the PDP.

1. **Empty.** Title "Your cart is empty" plus a single CTA back to the
   catalog. No upsell row, no promo input.
2. **Filled.** Each line item shows thumbnail, title, quantity stepper,
   and line subtotal. A primary "Checkout" button anchors the drawer
   foot above a "View cart" link.

No promo-code input, no upsell carousel, and no shipping estimate are
rendered in the drawer. Shipping cost is only computed from the cart
page after the customer enters a destination at checkout.
