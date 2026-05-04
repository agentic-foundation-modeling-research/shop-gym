import {Link, useLocation} from 'react-router';

export function Pagination({
  totalPages,
  currentPage,
}: {
  totalPages: number;
  currentPage: number;
}) {
  const {pathname, search} = useLocation();
  if (totalPages <= 1) return null;

  const items = buildPageItems(totalPages, currentPage);

  function pageHref(page: number): string {
    const params = new URLSearchParams(search);
    if (page <= 1) {
      params.delete('page');
    } else {
      params.set('page', String(page));
    }
    const qs = params.toString();
    return qs ? `${pathname}?${qs}` : pathname;
  }

  return (
    <nav className="pagination" aria-label="Pagination">
      <Link
        to={pageHref(Math.max(1, currentPage - 1))}
        className={`pagination-arrow${currentPage === 1 ? ' is-disabled' : ''}`}
        aria-disabled={currentPage === 1}
        aria-label="Previous page"
      >
        ‹
      </Link>
      {items.map((item, idx) =>
        typeof item === 'number' ? (
          <Link
            key={`p-${item}`}
            to={pageHref(item)}
            className={`pagination-page${
              item === currentPage ? ' is-current' : ''
            }`}
            aria-current={item === currentPage ? 'page' : undefined}
          >
            {item}
          </Link>
        ) : (
          <span key={`gap-${idx}`} className="pagination-gap" aria-hidden="true">
            …
          </span>
        ),
      )}
      <Link
        to={pageHref(Math.min(totalPages, currentPage + 1))}
        className={`pagination-arrow${
          currentPage === totalPages ? ' is-disabled' : ''
        }`}
        aria-disabled={currentPage === totalPages}
        aria-label="Next page"
      >
        ›
      </Link>
    </nav>
  );
}

function buildPageItems(
  totalPages: number,
  currentPage: number,
): Array<number | 'gap'> {
  if (totalPages <= 7) {
    return Array.from({length: totalPages}, (_, i) => i + 1);
  }
  const items: Array<number | 'gap'> = [1];
  const start = Math.max(2, currentPage - 1);
  const end = Math.min(totalPages - 1, currentPage + 1);
  if (start > 2) items.push('gap');
  for (let i = start; i <= end; i++) items.push(i);
  if (end < totalPages - 1) items.push('gap');
  items.push(totalPages);
  return items;
}
