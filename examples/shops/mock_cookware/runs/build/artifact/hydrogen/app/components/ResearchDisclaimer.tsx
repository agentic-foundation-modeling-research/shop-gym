/* @safeguard: applied v1 */
/**
 * Non-removable top-of-page banner declaring that this storefront is a
 * synthetic mock for research purposes only. Mounted into `root.tsx` by the
 * safeguard step in the shop_gen pipeline.
 *
 * Design notes:
 *  - Rendered as a non-sticky block at the very top of <body> so it scrolls
 *    away with the page and does not compete for the `top: 0` slot with the
 *    site's own sticky header.
 *  - Low z-index so cart/nav drawers and modals can cover it when they open.
 */
export function ResearchDisclaimer() {
  return (
    <div
      role="alert"
      data-safeguard-banner="true"
      style={{
        background: '#FEF3C7',
        color: '#78350F',
        padding: '8px 16px',
        textAlign: 'center',
        fontSize: '14px',
        borderBottom: '1px solid #F59E0B',
        position: 'relative',
        zIndex: 1,
      }}
    >
      ⚠️ This is a synthetic mock storefront for research purposes only. No commercial use.
    </div>
  );
}
