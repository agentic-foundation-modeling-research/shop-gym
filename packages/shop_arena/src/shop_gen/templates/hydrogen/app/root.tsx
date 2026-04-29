import {Analytics, getShopAnalytics, useNonce} from '@shopify/hydrogen';
import {
  Outlet,
  useRouteError,
  isRouteErrorResponse,
  type ShouldRevalidateFunction,
  Links,
  Meta,
  Scripts,
  ScrollRestoration,
  useRouteLoaderData,
} from 'react-router';
import type {Route} from './+types/root';
import favicon from '~/assets/favicon.svg';
import {FOOTER_QUERY, HEADER_QUERY} from '~/lib/fragments';
import type {FooterQuery} from 'storefrontapi.generated';
import resetStyles from '~/styles/reset.css?url';
import appStyles from '~/styles/app.css?url';
import {PageLayout} from './components/PageLayout';
import {ResearchDisclaimer} from './components/ResearchDisclaimer';

export type RootLoader = typeof loader;

/**
 * This is important to avoid re-fetching root queries on sub-navigations
 */
export const shouldRevalidate: ShouldRevalidateFunction = ({
  formMethod,
  currentUrl,
  nextUrl,
}) => {
  // revalidate when a mutation is performed e.g add to cart, login...
  if (formMethod && formMethod !== 'GET') return true;

  // revalidate when manually revalidating via useRevalidator
  if (currentUrl.toString() === nextUrl.toString()) return true;

  // Defaulting to no revalidation for root loader data to improve performance.
  // When using this feature, you risk your UI getting out of sync with your server.
  // Use with caution. If you are uncomfortable with this optimization, update the
  // line below to `return defaultShouldRevalidate` instead.
  // For more details see: https://remix.run/docs/en/main/route/should-revalidate
  return false;
};

/**
 * The main and reset stylesheets are added in the Layout component
 * to prevent a bug in development HMR updates.
 *
 * This avoids the "failed to execute 'insertBefore' on 'Node'" error
 * that occurs after editing and navigating to another page.
 *
 * It's a temporary fix until the issue is resolved.
 * https://github.com/remix-run/remix/issues/9242
 */
export function links() {
  return [
    {
      rel: 'preconnect',
      href: 'https://cdn.shopify.com',
    },
    {
      rel: 'preconnect',
      href: 'https://shop.app',
    },
    {rel: 'icon', type: 'image/svg+xml', href: favicon},
  ];
}

export async function loader(args: Route.LoaderArgs) {
  // Start fetching non-critical data without blocking time to first byte
  const deferredData = loadDeferredData(args);

  // Await the critical data required to render initial state of the page
  const criticalData = await loadCriticalData(args);

  const {storefront, env} = args.context;

  return {
    ...deferredData,
    ...criticalData,
    publicStoreDomain: env.PUBLIC_STORE_DOMAIN,
    shop: getShopAnalytics({
      storefront,
      publicStorefrontId: env.PUBLIC_STOREFRONT_ID,
    }),
    consent: {
      checkoutDomain: env.PUBLIC_CHECKOUT_DOMAIN,
      storefrontAccessToken: env.PUBLIC_STOREFRONT_API_TOKEN,
      withPrivacyBanner: false,
      // localize the privacy banner
      country: args.context.storefront.i18n.country,
      language: args.context.storefront.i18n.language,
    },
  };
}

/**
 * Load data necessary for rendering content above the fold. This is the critical data
 * needed to render the page. If it's unavailable, the whole page should 400 or 500 error.
 */
async function loadCriticalData({context}: Route.LoaderArgs) {
  const {storefront} = context;

  const [header] = await Promise.all([
    storefront.query(HEADER_QUERY, {
      cache: storefront.CacheLong(),
      variables: {
        headerMenuHandle: 'main-menu', // Adjust to your header menu handle
      },
    }),
    // Add other queries here, so that they are loaded in parallel
  ]);

  return {header};
}

/**
 * Default footer menu handle used when `env.PUBLIC_FOOTER_MENU_HANDLES` is
 * unset or empty. Matches the single-handle behavior the loader shipped with
 * before T3.2.
 */
const DEFAULT_FOOTER_MENU_HANDLE = 'footer';

/**
 * Parses the comma-separated `PUBLIC_FOOTER_MENU_HANDLES` env var into a
 * deduplicated list of handles. Falls back to `[DEFAULT_FOOTER_MENU_HANDLE]`
 * when the var is missing, empty, or all-whitespace so existing artifacts
 * continue to render their single-column footer.
 */
function parseFooterMenuHandles(raw: string | undefined): string[] {
  if (!raw) return [DEFAULT_FOOTER_MENU_HANDLE];
  const handles = raw
    .split(',')
    .map((handle) => handle.trim())
    .filter((handle) => handle.length > 0);
  if (handles.length === 0) return [DEFAULT_FOOTER_MENU_HANDLE];
  // Deduplicate while preserving first-occurrence order.
  return Array.from(new Set(handles));
}

/**
 * Load data for rendering content below the fold. This data is deferred and will be
 * fetched after the initial page load. If it's unavailable, the page should still 200.
 * Make sure to not throw any errors here, as it will cause the page to 500.
 */
function loadDeferredData({context}: Route.LoaderArgs) {
  const {storefront, customerAccount, cart, env} = context;

  const footerMenuHandles = parseFooterMenuHandles(
    env.PUBLIC_FOOTER_MENU_HANDLES,
  );

  // Fan out one parallel query per handle. We intentionally call the
  // single-handle `FOOTER_QUERY` N times rather than aliasing handles into a
  // single GraphQL operation: the codegen pipeline keys off the static query
  // string, so a fixed shape keeps the generated `FooterQuery` type stable
  // across shops while N varies at runtime.
  const footers: Promise<Array<FooterQuery | null>> = Promise.all(
    footerMenuHandles.map((handle) =>
      storefront
        .query(FOOTER_QUERY, {
          cache: storefront.CacheLong(),
          variables: {
            footerMenuHandle: handle,
          },
        })
        .catch((error: Error) => {
          // Log query errors, but don't throw them so the page can still render
          console.error(error);
          return null;
        }),
    ),
  );

  // Back-compat: emit a single-menu `footer` derived from the first handle so
  // existing `<PageLayout>` / `<Footer>` consumers (which still expect
  // `footer: Promise<FooterQuery | null>`) keep compiling until T3.4 migrates
  // them onto the array shape.
  const footer: Promise<FooterQuery | null> = footers.then(
    (results) => results[0] ?? null,
  );

  return {
    cart: cart.get(),
    isLoggedIn: customerAccount.isLoggedIn(),
    footer,
    footers,
  };
}

export function Layout({children}: {children?: React.ReactNode}) {
  const nonce = useNonce();

  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width,initial-scale=1" />
        <link rel="stylesheet" href={resetStyles}></link>
        <link rel="stylesheet" href={appStyles}></link>
        <Meta />
        <Links />
      </head>
      <body>
        <ResearchDisclaimer />
        {children}
        <ScrollRestoration nonce={nonce} />
        <Scripts nonce={nonce} />
      </body>
    </html>
  );
}

export default function App() {
  const data = useRouteLoaderData<RootLoader>('root');

  if (!data) {
    return <Outlet />;
  }

  return (
    <Analytics.Provider
      cart={data.cart}
      shop={data.shop}
      consent={data.consent}
    >
      <PageLayout {...data}>
        <Outlet />
      </PageLayout>
    </Analytics.Provider>
  );
}

export function ErrorBoundary() {
  const error = useRouteError();
  let errorMessage = 'Unknown error';
  let errorStatus = 500;

  if (isRouteErrorResponse(error)) {
    errorMessage = error?.data?.message ?? error.data;
    errorStatus = error.status;
  } else if (error instanceof Error) {
    errorMessage = error.message;
  }

  return (
    <div className="route-error">
      <h1>Oops</h1>
      <h2>{errorStatus}</h2>
      {errorMessage && (
        <fieldset>
          <pre>{errorMessage}</pre>
        </fieldset>
      )}
    </div>
  );
}
