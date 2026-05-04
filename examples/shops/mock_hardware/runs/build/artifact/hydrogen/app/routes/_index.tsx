import {useLoaderData} from 'react-router';
import type {Route} from './+types/_index';
import {MockShopNotice} from '~/components/MockShopNotice';
import {HeroBanner} from '~/components/HeroBanner';
import {FeatureCard} from '~/components/FeatureCard';
import {FeaturesGrid} from '~/components/FeaturesGrid';
import {Testimonials} from '~/components/Testimonials';

export const meta: Route.MetaFunction = () => {
  return [
    {title: 'Mock Hardware | POS hardware for small retailers'},
    {
      name: 'description',
      content:
        'Card readers, slip printers, scanners, and countertop bundles built for small and mid-sized retailers.',
    },
  ];
};

export async function loader({context}: Route.LoaderArgs) {
  const homepage = await context.storefront
    .query(HOMEPAGE_QUERY)
    .catch((error: Error) => {
      console.error(error);
      return null;
    });

  return {
    isShopLinked: Boolean(context.env.PUBLIC_STORE_DOMAIN),
    hero: homepage?.hero ?? null,
    bundle: homepage?.bundle ?? null,
    posHub: homepage?.posHub ?? null,
    tapToPay: homepage?.tapToPay ?? null,
  };
}

export default function Homepage() {
  const data = useLoaderData<typeof loader>();
  return (
    <div className="homepage">
      {data.isShopLinked ? null : <MockShopNotice />}
      <HeroBanner product={data.hero} />
      <FeatureCard
        eyebrow="Bundle & save"
        headline="Build a countertop kit, save together"
        body="Pair a card reader, slip printer, scanner, and till tray in one bundle and pay less than buying piece by piece. Configure a kit that fits your counter."
        ctaLabel="Build your bundle"
        ctaUrl="/collections/aislearena-counter-bundles"
        product={data.bundle}
        variant="light"
      />
      <FeatureCard
        eyebrow="POS Hub"
        headline="The hub that anchors your counter"
        body="A purpose-built retail hub that powers and connects every peripheral on your counter — printers, readers, scanners, and displays — through a single dock."
        ctaLabel="Meet the POS Hub"
        ctaUrl="/collections/retail-hub-companions"
        product={data.posHub}
        variant="dark"
        reverse
      />
      <FeatureCard
        eyebrow="Tap to Pay"
        headline="Take payments with just a phone"
        body="Turn an iPhone or Android device into a contactless payment terminal — no extra hardware required for chip and tap. When the day picks up, pair a portable reader and keep the line moving."
        ctaLabel="See compatible readers"
        ctaUrl="/collections/tap-terminals"
        product={data.tapToPay}
        variant="light"
      />
      <FeaturesGrid />
      <Testimonials />
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
  }
` as const;

const HOMEPAGE_QUERY = `#graphql
  ${HOMEPAGE_PRODUCT_FRAGMENT}
  query Homepage($country: CountryCode, $language: LanguageCode)
    @inContext(country: $country, language: $language) {
    hero: product(handle: "agoracage-pro-wireless-code-scanner-with-dock") {
      ...HomepageProduct
    }
    bundle: product(handle: "aislearena-reader-bundle") {
      ...HomepageProduct
    }
    posHub: product(handle: "aisleum-counter-hub") {
      ...HomepageProduct
    }
    tapToPay: product(handle: "aislearena-portable-card-reader") {
      ...HomepageProduct
    }
  }
` as const;
