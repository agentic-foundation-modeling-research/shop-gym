import { type LoaderFunctionArgs, Link, useLoaderData } from 'react-router';
import { HelpCenter, HelpLayout, HelpSearch } from '~/components/info-pages';
import { getAppContext } from '~/lib/context';
import { PAGE_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { Page } from '~/lib/types';

interface PageData { readonly page: Page | null; }
interface PageLoaderData { readonly page: Page; }

export function meta({ data }: { readonly data: PageLoaderData | undefined }) {
  return [{ title: data?.page?.title ?? 'Page' }];
}

export async function loader({ context, params }: LoaderFunctionArgs): Promise<PageLoaderData> {
  if (!params.handle) throw new Response('Missing page handle.', { status: 400 });
  const data = await storefrontQuery<PageData>(getAppContext(context), PAGE_QUERY, {handle: params.handle});
  if (!data.page) throw new Response('Page not found.', { status: 404 });
  return { page: data.page };
}

const shippingGroups = [
  { title: 'Popular topics', links: [{title: 'Track your order', url: '/account/orders'}, {title: 'Start a return', url: '/account/login'}, {title: 'Shipping policy', url: '/policies/shipping-policy'}] },
  { title: 'Package tracking', links: [{title: 'Check order status', url: '/account/orders'}, {title: 'Find delivery updates', url: '/account/orders'}] },
  { title: 'Membership shipping', links: [{title: 'Membership & delivery benefits', url: '/account/login'}, {title: 'Manage your membership', url: '/account/login'}] },
  { title: 'General shipping policies', links: [{title: 'Shipping policy', url: '/policies/shipping-policy'}, {title: 'Returns and refunds', url: '/policies/refund-policy'}] },
  { title: 'Rates and times', links: [{title: 'Shipping rates', url: '/policies/shipping-policy'}, {title: 'Delivery estimates', url: '/policies/shipping-policy'}] },
  { title: 'Special shipping options', links: [{title: 'Digital items and physical deliveries', url: '/policies/shipping-policy'}, {title: 'Shipping at checkout', url: '/checkout'}] },
  { title: 'International shipping', links: [{title: 'Available destinations', url: '/policies/shipping-policy'}, {title: 'Delivery address settings', url: '/account/addresses'}] },
];

export default function PageRoute() {
  const { page } = useLoaderData<typeof loader>();
  if (page.handle === 'help-center') return <HelpCenter body={page.body} />;
  if (page.handle === 'shipping-policy') return <HelpLayout title="Shipping & delivery" handle={page.handle} intro="Find answers to your questions about shipping, delivery and order tracking."><p className="help-callout">Looking for a package? <Link to="/account/orders">Go to your orders</Link> to check its status and delivery updates.</p><div className="help-article-groups">{shippingGroups.map(group => <section key={group.title}><h2>{group.title}</h2><ul>{group.links.map(link => <li key={link.title}><Link to={link.url}>{link.title} <span aria-hidden="true">›</span></Link></li>)}</ul></section>)}</div><section className="help-dataset-article"><div className="page-body" dangerouslySetInnerHTML={{__html: page.body}} /></section><HelpSearch /></HelpLayout>;
  return <HelpLayout title={page.title} handle={page.handle}><div className="page-body" dangerouslySetInnerHTML={{__html: page.body}} /><p className="help-callout">Need more help? <Link to="/pages/help-center">Visit the Help Center</Link>.</p></HelpLayout>;
}
