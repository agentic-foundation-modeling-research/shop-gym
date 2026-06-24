import {useLoaderData, type LoaderFunctionArgs} from 'react-router';
import {getAppContext} from '~/lib/context';
import {POLICIES_QUERY} from '~/lib/queries';
import {storefrontQuery} from '~/lib/storefront';
import type {Policy} from '~/lib/types';

interface PoliciesData {
  readonly shop: {
    readonly privacyPolicy: Policy | null;
    readonly shippingPolicy: Policy | null;
    readonly termsOfService: Policy | null;
    readonly refundPolicy: Policy | null;
    readonly subscriptionPolicy: Policy | null;
  };
}

interface PolicyLoaderData {
  readonly policy: Policy;
}

const POLICY_FIELDS = [
  'privacyPolicy',
  'shippingPolicy',
  'termsOfService',
  'refundPolicy',
  'subscriptionPolicy',
] as const;

export function meta({
  data,
}: {
  readonly data: PolicyLoaderData | undefined;
}) {
  return [{title: data?.policy.title ?? 'Policy'}];
}

export async function loader({
  context,
  params,
}: LoaderFunctionArgs): Promise<PolicyLoaderData> {
  if (!params.handle) {
    throw new Response('Missing policy handle.', {status: 400});
  }
  const data = await storefrontQuery<PoliciesData>(
    getAppContext(context),
    POLICIES_QUERY,
  );
  const policy = findPolicy(data, params.handle);
  if (!policy) {
    throw new Response('Policy not found.', {status: 404});
  }
  return {policy};
}

export default function PolicyRoute() {
  const {policy} = useLoaderData<typeof loader>();
  return (
    <article className="page-width stack">
      <h1>{policy.title}</h1>
      <div className="policy-body" dangerouslySetInnerHTML={{__html: policy.body}} />
    </article>
  );
}

function findPolicy(data: PoliciesData, handle: string): Policy | null {
  for (const field of POLICY_FIELDS) {
    const policy = data.shop[field];
    if (policy?.handle === handle) return policy;
  }
  return null;
}
