import { type LoaderFunctionArgs, Link, useLoaderData } from 'react-router';
import { HelpLayout } from '~/components/info-pages';
import { getAppContext } from '~/lib/context';
import { POLICIES_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { Policy } from '~/lib/types';

interface PoliciesData { readonly shop: { readonly privacyPolicy: Policy | null; readonly shippingPolicy: Policy | null; readonly termsOfService: Policy | null; readonly refundPolicy: Policy | null; readonly subscriptionPolicy: Policy | null; }; }
interface PolicyLoaderData { readonly policy: Policy; readonly policies: Policy[]; }
const POLICY_FIELDS = ['privacyPolicy', 'shippingPolicy', 'termsOfService', 'refundPolicy', 'subscriptionPolicy'] as const;
export function meta({ data }: { readonly data: PolicyLoaderData | undefined }) { return [{ title: data?.policy.title ?? 'Policy' }]; }
export async function loader({ context, params }: LoaderFunctionArgs): Promise<PolicyLoaderData> {
  if (!params.handle) throw new Response('Missing policy handle.', { status: 400 });
  const data = await storefrontQuery<PoliciesData>(getAppContext(context), POLICIES_QUERY);
  const policies = POLICY_FIELDS.map(field => data.shop[field]).filter((policy): policy is Policy => !!policy);
  const policy = policies.find(item => item.handle === params.handle);
  if (!policy) throw new Response('Policy not found.', { status: 404 });
  return { policy, policies };
}
export default function PolicyRoute() {
  const {policy, policies} = useLoaderData<typeof loader>();
  return <HelpLayout title={policy.title} handle={policy.handle} policies={policies}><div className="policy-body" dangerouslySetInnerHTML={{__html: policy.body}} /><div className="help-policy-related"><h2>Related help</h2><Link to="/pages/shipping-policy">Shipping & delivery</Link><Link to="/pages/help-center">Customer service</Link><Link to="/account/login">Your account</Link></div></HelpLayout>;
}
