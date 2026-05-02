You are looking at a search results page of an online store after the
shopper submitted a query.

Decide whether the page exposes either (a) a list of results
(products / suggestions an agent could enumerate) **or** (b) a clear
no-results state that tells the shopper their query produced nothing.

Treat as **present** in either case — both are valid outcomes of a
search. Treat as **not present** only when the page is broken or
generic and gives no signal about whether there are results.

Set `name_used` to the result count if visible (e.g. "3 results")
or to the no-results message. Set `evidence_locator` to a short hint
identifying the list region or no-results banner.
