import {Await, useLoaderData} from 'react-router';
import {Suspense} from 'react';
import type {Route} from './+types/_index';
import {MockShopNotice} from '~/components/MockShopNotice';
import {HeroBanner} from '~/components/HeroBanner';
import {CategoryChips} from '~/components/CategoryChips';
import {FeaturedPromo} from '~/components/FeaturedPromo';
import {FeatureGrid} from '~/components/FeatureGrid';
import {ChefEndorsement} from '~/components/ChefEndorsement';
import {ProductCarousel} from '~/components/ProductCarousel';
import {ImageTextSplit} from '~/components/ImageTextSplit';
import {Testimonials} from '~/components/Testimonials';
import {RecipeCarousel, ArticleCarousel} from '~/components/EditorialCarousels';
import {NewsletterSignup} from '~/components/NewsletterSignup';
import {AccessibilityToolbar} from '~/components/AccessibilityToolbar';

export const meta: Route.MetaFunction = () => {
  return [
    {title: 'Mock Cookware | Heirloom-grade Pots, Pans, and Knives'},
    {
      name: 'description',
      content:
        'Premium cookware, knives, and bakeware tested by chefs and built for daily home cooking.',
    },
  ];
};

export async function loader(args: Route.LoaderArgs) {
  const {context} = args;
  const homepage = context.storefront
    .query(HOMEPAGE_QUERY)
    .catch((error: Error) => {
      console.error(error);
      return null;
    });
  return {
    isShopLinked: Boolean(context.env.PUBLIC_STORE_DOMAIN),
    homepage,
  };
}

export default function Homepage() {
  const data = useLoaderData<typeof loader>();
  return (
    <div className="homepage">
      {data.isShopLinked ? null : <MockShopNotice />}
      <HeroBanner />
      <CategoryChips />
      <Suspense fallback={<HomepageSectionFallback />}>
        <Await resolve={data.homepage} errorElement={null}>
          {(resolved) => (
            <FeaturedPromo
              products={resolved?.salePicks?.products?.nodes ?? []}
            />
          )}
        </Await>
      </Suspense>
      <FeatureGrid />
      <ChefEndorsement />
      <Suspense fallback={<HomepageSectionFallback />}>
        <Await resolve={data.homepage} errorElement={null}>
          {(resolved) => (
            <ProductCarousel
              title="Best Sellers"
              subtitle="The pans and knives our customers reach for most"
              cta={{label: 'Shop Best Sellers', url: '/collections/best-sellers'}}
              products={resolved?.bestSellers?.products?.nodes ?? []}
            />
          )}
        </Await>
      </Suspense>
      <ImageTextSplit />
      <Testimonials />
      <RecipeCarousel />
      <ArticleCarousel />
      <NewsletterSignup />
      <AccessibilityToolbar />
    </div>
  );
}

function HomepageSectionFallback() {
  return (
    <div className="homepage-section-fallback" aria-hidden="true">
      <div className="section-container">
        <div className="homepage-section-fallback-bar" />
        <div className="homepage-section-fallback-grid">
          <div className="homepage-section-fallback-card" />
          <div className="homepage-section-fallback-card" />
          <div className="homepage-section-fallback-card" />
        </div>
      </div>
    </div>
  );
}

const HOMEPAGE_PRODUCT_FRAGMENT = `#graphql
  fragment HomepageProduct on Product {
    id
    title
    handle
    featuredImage {
      id
      url
      altText
      width
      height
    }
    priceRange {
      minVariantPrice {
        amount
        currencyCode
      }
    }
  }
` as const;

const HOMEPAGE_QUERY = `#graphql
  ${HOMEPAGE_PRODUCT_FRAGMENT}
  query Homepage($country: CountryCode, $language: LanguageCode)
    @inContext(country: $country, language: $language) {
    bestSellers: collection(handle: "best-sellers") {
      id
      products(first: 12) {
        nodes {
          ...HomepageProduct
        }
      }
    }
    salePicks: collection(handle: "sale") {
      id
      products(first: 3) {
        nodes {
          ...HomepageProduct
        }
      }
    }
  }
` as const;
