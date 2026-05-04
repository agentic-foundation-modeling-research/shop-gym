import {useLoaderData} from 'react-router';
import type {Route} from './+types/_index';
import {MockShopNotice} from '~/components/MockShopNotice';
import {HeroCarousel} from '~/components/HeroCarousel';
import {ShippingDeadlineStrip} from '~/components/ShippingDeadlineStrip';
import {ProductGridSection} from '~/components/ProductGridSection';
import {PromoBanner} from '~/components/PromoBanner';
import {CategoryMasonryGrid} from '~/components/CategoryMasonryGrid';
import {ActivityGrid} from '~/components/ActivityGrid';
import {DualPromoBanners} from '~/components/DualPromoBanners';
import {OnboardingBanner} from '~/components/OnboardingBanner';
import {HomepageOverlays} from '~/components/HomepageOverlays';

export const meta: Route.MetaFunction = () => {
  return [{title: 'Mock Apparel | Comfort-forward activewear & loungewear'}];
};

export async function loader(args: Route.LoaderArgs) {
  const deferredData = loadDeferredData(args);
  const criticalData = await loadCriticalData(args);
  return {...deferredData, ...criticalData};
}

async function loadCriticalData({context}: Route.LoaderArgs) {
  return {
    isShopLinked: Boolean(context.env.PUBLIC_STORE_DOMAIN),
  };
}

function loadDeferredData({context}: Route.LoaderArgs) {
  const fetchCollection = (handle: string) =>
    context.storefront
      .query(HOMEPAGE_COLLECTION_QUERY, {variables: {handle}})
      .catch((error: Error) => {
        console.error(error);
        return null;
      });

  return {
    newArrivals: fetchCollection('fresh-drops'),
    bestSellers: fetchCollection('fan-favorites'),
    loungewear: fetchCollection('lounge-collection'),
  };
}

export default function Homepage() {
  const data = useLoaderData<typeof loader>();
  return (
    <>
      <main className="homepage">
        {data.isShopLinked ? null : (
          <div className="homepage-mock-notice">
            <MockShopNotice />
          </div>
        )}

        <HeroCarousel />

        <ShippingDeadlineStrip />

        <ProductGridSection
          products={data.newArrivals}
          eyebrow="Just Landed"
          heading="New Arrivals"
          viewAllLabel="View All"
          viewAllUrl="/collections/fresh-drops"
        />

        <PromoBanner
          eyebrow="Editorial Drop"
          headline="Best Sellers, Reimagined"
          subline="The pieces our community wears on repeat — refreshed in this season's signature palette."
          ctaLabel="Shop Best Sellers"
          ctaUrl="/collections/fan-favorites"
          align="lower-left"
          background={{
            primary: '#a07e6c',
            secondary: '#3e2c22',
            accent: '#efd8be',
          }}
        />

        <ProductGridSection
          products={data.bestSellers}
          eyebrow="Most Loved"
          heading="Best Sellers"
          viewAllLabel="View All"
          viewAllUrl="/collections/fan-favorites"
        />

        <CategoryMasonryGrid />

        <ActivityGrid />

        <DualPromoBanners />

        <ProductGridSection
          products={data.loungewear}
          eyebrow="At Home Comfort"
          heading="Loungewear"
          subline="Cloud-soft staples for slow mornings and slower evenings — available in up to fourteen colors."
          viewAllLabel="View All"
          viewAllUrl="/collections/lounge-collection"
        />

        <OnboardingBanner />
      </main>

      <HomepageOverlays />
    </>
  );
}

const HOMEPAGE_COLLECTION_QUERY = `#graphql
  query HomepageCollection(
    $handle: String!
    $country: CountryCode
    $language: LanguageCode
  ) @inContext(country: $country, language: $language) {
    collection(handle: $handle) {
      id
      handle
      title
      products(first: 12) {
        nodes {
          id
          handle
          title
          productType
          tags
          featuredImage {
            id
            altText
            url
            width
            height
          }
          priceRange {
            minVariantPrice { amount currencyCode }
            maxVariantPrice { amount currencyCode }
          }
          compareAtPriceRange {
            minVariantPrice { amount currencyCode }
            maxVariantPrice { amount currencyCode }
          }
          options {
            name
            values
          }
        }
      }
    }
  }
` as const;
