import {useLoaderData, Link} from 'react-router';
import type {Route} from './+types/policies._index';
import type {PoliciesQuery, PolicyItemFragment} from 'storefrontapi.generated';
import {InfoPageFooter} from '~/components/InfoPageFooter';

export async function loader({context}: Route.LoaderArgs) {
  const data: PoliciesQuery = await context.storefront.query(POLICIES_QUERY);

  const shopPolicies = data.shop;
  const policies: PolicyItemFragment[] = [
    shopPolicies?.privacyPolicy,
    shopPolicies?.shippingPolicy,
    shopPolicies?.termsOfService,
    shopPolicies?.refundPolicy,
    shopPolicies?.subscriptionPolicy,
  ].filter((policy): policy is PolicyItemFragment => policy != null);

  if (!policies.length) {
    throw new Response('No policies found', {status: 404});
  }

  return {policies};
}

export default function Policies() {
  const {policies} = useLoaderData<typeof loader>();

  return (
    <article className="info-page">
      <header className="info-page-header">
        <h1 className="info-page-title">Policies</h1>
        <p className="info-page-intro">
          Illustrative store policies for this research-only mock storefront.
        </p>
      </header>
      <section className="info-page-section info-page-section-narrow">
        <ul className="policy-index-list">
          {policies.map((policy) => (
            <li key={policy.id} className="policy-index-item">
              <Link
                to={`/policies/${policy.handle}`}
                prefetch="intent"
                className="policy-index-link"
              >
                <span className="policy-index-title">{policy.title}</span>
                <span aria-hidden="true" className="policy-index-arrow">
                  →
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
      <InfoPageFooter />
    </article>
  );
}

const POLICIES_QUERY = `#graphql
  fragment PolicyItem on ShopPolicy {
    id
    title
    handle
  }
  query Policies ($country: CountryCode, $language: LanguageCode)
    @inContext(country: $country, language: $language) {
    shop {
      privacyPolicy {
        ...PolicyItem
      }
      shippingPolicy {
        ...PolicyItem
      }
      termsOfService {
        ...PolicyItem
      }
      refundPolicy {
        ...PolicyItem
      }
      subscriptionPolicy {
        id
        title
        handle
      }
    }
  }
` as const;
