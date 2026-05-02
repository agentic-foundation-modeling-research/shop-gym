import {HydratedRouter} from 'react-router/dom';
import {startTransition, StrictMode} from 'react';
import {hydrateRoot} from 'react-dom/client';
import {NonceProvider} from '@shopify/hydrogen';

if (!window.location.origin.includes('webcache.googleusercontent.com')) {
  startTransition(() => {
    // Extract nonce from existing script tags
    const existingNonce =
      document.querySelector<HTMLScriptElement>('script[nonce]')?.nonce;

    hydrateRoot(
      document,
      <StrictMode>
        <NonceProvider value={existingNonce}>
          <HydratedRouter />
        </NonceProvider>
      </StrictMode>,
    );
  });
}

// Safeguard: block navigation to any origin outside this site so the mock
// storefront cannot send research users to live third-party destinations.
// `mailto:` and `tel:` are preserved so contact affordances still work, and
// cdn.shopify.com / shopify.com are allowed so product images and the
// Shopify runtime continue to load. Shops can extend this by setting
// `window.__SAFEGUARD_ALLOWED_HOSTS__` before hydration.
declare global {
  interface Window {
    __SAFEGUARD_ALLOWED_HOSTS__?: readonly string[];
  }
}

if (typeof document !== 'undefined') {
  const DEFAULT_ALLOWED = [
    'cdn.shopify.com',
    'shopify.com',
    'monorail-edge.shopifysvc.com',
  ] as const;

  document.addEventListener(
    'click',
    (event) => {
      const target = event.target as HTMLElement | null;
      if (!target) return;
      const link = target.closest('a[href]') as HTMLAnchorElement | null;
      if (!link) return;
      try {
        const url = new URL(link.href, location.origin);
        const sameOrigin = url.origin === location.origin;
        const protocolOk =
          url.protocol === 'mailto:' || url.protocol === 'tel:';
        const allowed =
          sameOrigin ||
          protocolOk ||
          [...DEFAULT_ALLOWED, ...(window.__SAFEGUARD_ALLOWED_HOSTS__ ?? [])].some(
            (host) => url.hostname === host || url.hostname.endsWith('.' + host),
          );
        if (!allowed) {
          event.preventDefault();
          // eslint-disable-next-line no-console
          console.warn('[safeguard] blocked external navigation:', link.href);
        }
      } catch {
        /* non-URL href — ignore */
      }
    },
    true,
  );
}
