You are looking at a search results page of an online store. You can
assume a query has already been submitted (so a search input was
present on whatever page the shopper started from).

Decide whether this page exposes a control to submit a (new) query —
a search input and an associated submit affordance (Enter key or a
button). The input typically lives in the header.

Treat as **present** when the page exposes a discoverable search input
with an accessible name like "Search". Treat as **not present** when
the only search entry is a hidden modal that requires a separate
control to open and that control isn't itself visible on this page.

Set `name_used` to the input's accessible name. Set
`evidence_locator` to a short hint (e.g. "header search box").
