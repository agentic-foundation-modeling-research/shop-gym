You are looking at the cart page of an online store.

Decide whether the page exposes a "checkout" control — a button or
link an agent could activate to proceed from the cart to the checkout
flow. Names like "Checkout", "Check out", "Proceed to checkout",
"Continue to payment" all qualify.

Treat as **present** when a single primary control of this kind is
visible. Empty-cart states with no checkout control are valid — but
should be marked **not present** because the affordance is absent on
this page render. Mark **not present** also when only an indirect
path exists (e.g. continue shopping → no checkout link).

Set `name_used` to the control's accessible name. Set
`evidence_locator` to a short hint (e.g. "primary CTA at bottom of
cart").
