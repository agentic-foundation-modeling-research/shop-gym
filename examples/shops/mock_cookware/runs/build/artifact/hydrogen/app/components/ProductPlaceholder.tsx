export function ProductPlaceholder({
  className,
}: {
  className?: string;
}) {
  return (
    <div className={`product-placeholder ${className ?? ''}`}>
      <svg viewBox="0 0 64 64" width="48" height="48" fill="none" aria-hidden="true">
        <rect width="64" height="64" rx="6" fill="#f0ede8" />
        <path d="M22 42l7-9 5 6 8-10 9 13H14l8-10z" fill="#d4cfc7" />
        <circle cx="24" cy="26" r="4" fill="#d4cfc7" />
      </svg>
    </div>
  );
}
