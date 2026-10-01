import { type ReactNode, useEffect, useState } from 'react';
import {
  Links,
  type LoaderFunctionArgs,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
  isRouteErrorResponse,
  useLocation,
  useNavigate,
  useRouteError,
  useRouteLoaderData,
} from 'react-router';
import { CustomerPopups } from '~/components/popups';
import { CartDrawer, Footer, Header } from '~/components/storefront';
import { getAppContext, getCartId } from '~/lib/context';
import { loadCustomer } from '~/lib/customer';
import { CART_QUERY, ROOT_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { Cart, Customer, Menu, Policy, Shop } from '~/lib/types';
import appStyles from '~/styles/app.css?url';

interface RootQueryData {
  readonly shop: Shop;
  readonly headerMenu: Menu | null;
  readonly footerMenu: Menu | null;
}

interface CartQueryData {
  readonly cart: Cart | null;
}

export interface RootLoaderData extends RootQueryData {
  readonly cart: Cart | null;
  readonly customer: Customer | null;
  readonly policies: readonly Policy[];
}

export function links() {
  return [{ rel: 'stylesheet', href: appStyles }];
}

export async function loader({ context }: LoaderFunctionArgs): Promise<RootLoaderData> {
  const appContext = getAppContext(context);
  const rootData = await storefrontQuery<RootQueryData>(appContext, ROOT_QUERY, {
    headerMenuHandle: 'main-menu',
    footerMenuHandle: firstFooterMenuHandle(appContext.env.PUBLIC_FOOTER_MENU_HANDLES),
  });
  const cartId = getCartId(appContext);
  const [cart, customer] = await Promise.all([
    cartId === null
      ? null
      : storefrontQuery<CartQueryData>(appContext, CART_QUERY, { cartId }).then(
          (data) => data.cart,
        ),
    loadCustomer(appContext),
  ]);
  return {
    ...rootData,
    cart,
    customer,
    policies: collectPolicies(rootData.shop),
  };
}

export function Layout({ children }: { readonly children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width,initial-scale=1" />
        <Meta />
        <Links />
      </head>
      <body>
        {children}
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function App() {
  const data = useRouteLoaderData<RootLoaderData>('root');
  const location = useLocation();
  const navigate = useNavigate();
  const [isCartOpen, setCartOpen] = useState(() => hasCartOpenParam(location.search));
  const cartOpenPath = withCartOpenParam(location);

  useEffect(() => {
    setCartOpen(hasCartOpenParam(location.search));
  }, [location.search]);

  if (!data) return <Outlet />;

  function openCart() {
    setCartOpen(true);
    void navigate(cartOpenPath, { preventScrollReset: true });
  }

  function closeCart() {
    setCartOpen(false);
    void navigate(withoutCartOpenParam(location), {
      replace: true,
      preventScrollReset: true,
    });
  }

  return (
    <div className="page-shell">
      <Header
        shop={data.shop}
        menu={data.headerMenu}
        cart={data.cart}
        customer={data.customer}
        isCartOpen={isCartOpen}
        onCartOpen={openCart}
      />
      <main id="main-content">
        <Outlet />
      </main>
      <Footer menu={data.footerMenu} policies={data.policies} />
      <CustomerPopups shop={data.shop} policies={data.policies} />
      <CartDrawer
        cart={data.cart}
        isOpen={isCartOpen}
        onClose={closeCart}
        redirectTo={cartOpenPath}
      />
    </div>
  );
}

export function ErrorBoundary() {
  const error = useRouteError();
  const title = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : 'Something went wrong';
  return (
    <main className="page-width error-page">
      <h1>{title}</h1>
      <p>
        {error instanceof Error ? error.message : 'The storefront could not render this request.'}
      </p>
    </main>
  );
}

function firstFooterMenuHandle(raw: string | undefined): string {
  if (!raw) return 'footer';
  const handle = raw
    .split(',')
    .map((entry) => entry.trim())
    .find((entry) => entry.length > 0);
  return handle ?? 'footer';
}

function collectPolicies(shop: Shop): readonly Policy[] {
  return [
    shop.privacyPolicy,
    shop.shippingPolicy,
    shop.refundPolicy,
    shop.termsOfService,
    shop.subscriptionPolicy,
  ].filter((policy): policy is Policy => policy !== null && policy !== undefined);
}

function hasCartOpenParam(search: string): boolean {
  return new URLSearchParams(search).get('cart') === 'open';
}

function withCartOpenParam(location: {
  readonly pathname: string;
  readonly search: string;
  readonly hash: string;
}): string {
  const params = new URLSearchParams(location.search);
  params.set('cart', 'open');
  return formatPath(location.pathname, params, location.hash);
}

function withoutCartOpenParam(location: {
  readonly pathname: string;
  readonly search: string;
  readonly hash: string;
}): string {
  const params = new URLSearchParams(location.search);
  params.delete('cart');
  return formatPath(location.pathname, params, location.hash);
}

function formatPath(pathname: string, params: URLSearchParams, hash: string): string {
  const search = params.toString();
  return `${pathname}${search ? `?${search}` : ''}${hash}`;
}
