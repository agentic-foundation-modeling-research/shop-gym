# collection_filters

The collection page renders a four-column desktop grid with a left
filter rail and a sort dropdown above the grid.

- **Filters.** Four groups: size, color, material, price. Each group
  collapses; the rail remembers its open/closed state across pagination.
- **Sort.** Five options: featured (default), price (low → high),
  price (high → low), newest, best-selling.
- **Pagination.** Cursor-style "Load more" button under the grid; no
  numbered pages.

Filter selections update the URL query string so links are
shareable and bookmarkable.
