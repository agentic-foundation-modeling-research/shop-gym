import {Suspense} from 'react';
import {Await, useLoaderData} from 'react-router';
import type {Route} from './+types/products.$handle';
import {
  getSelectedProductOptions,
  Analytics,
  useOptimisticVariant,
  getProductOptions,
  getAdjacentAndFirstAvailableVariants,
  useSelectedOptionInUrlParam,
  Money,
} from '@shopify/hydrogen';
import {ProductImage} from '~/components/ProductImage';
import {ProductForm} from '~/components/ProductForm';
import {ProductAccordion} from '~/components/ProductAccordion';
import {ProductReviews} from '~/components/ProductReviews';
import {ShopTheLook} from '~/components/ShopTheLook';
import {ProductEditorialBlocks} from '~/components/ProductEditorialBlocks';
import {PdpBreadcrumbs} from '~/components/PdpBreadcrumbs';
import {PdpStickyBar} from '~/components/PdpStickyBar';
import {FreeShippingBar} from '~/components/FreeShippingBar';
import {redirectIfHandleIsLocalized} from '~/lib/redirect';
import {formatRating} from '~/lib/productColors';

export const meta: Route.MetaFunction = ({data}) => {
  return [
    {title: `${data?.product.title ?? ''} | Mock Apparel`},
    {
      rel: 'canonical',
      href: `/products/${data?.product.handle}`,
    },
  ];
};

export async function loader(args: Route.LoaderArgs) {
  const deferredData = loadDeferredData(args);
  const criticalData = await loadCriticalData(args);
  return {...deferredData, ...criticalData};
}

async function loadCriticalData({context, params, request}: Route.LoaderArgs) {
  const {handle} = params;
  const {storefront} = context;

  if (!handle) {
    throw new Error('Expected product handle to be defined');
  }

  const [{product}] = await Promise.all([
    storefront.query(PRODUCT_QUERY, {
      variables: {handle, selectedOptions: getSelectedProductOptions(request)},
    }),
  ]);

  if (!product?.id) {
    throw new Response(null, {status: 404});
  }

  redirectIfHandleIsLocalized(request, {handle, data: product});

  return {product};
}

function loadDeferredData({context}: Route.LoaderArgs) {
  const recommendedProducts = context.storefront
    .query(SHOP_THE_LOOK_QUERY)
    .catch((error: Error) => {
      console.error(error);
      return null;
    });

  return {recommendedProducts};
}

export default function Product() {
  const {product, recommendedProducts} = useLoaderData<typeof loader>();

  const selectedVariant = useOptimisticVariant(
    product.selectedOrFirstAvailableVariant,
    getAdjacentAndFirstAvailableVariants(product),
  );

  useSelectedOptionInUrlParam(selectedVariant?.selectedOptions ?? []);

  const productOptions = getProductOptions({
    ...product,
    selectedOrFirstAvailableVariant: selectedVariant,
  });

  const {title, vendor, handle} = product;

  const price = selectedVariant?.price;
  const compareAt = selectedVariant?.compareAtPrice;
  const isOnSale =
    price && compareAt
      ? parseFloat(compareAt.amount) > parseFloat(price.amount)
      : false;
  const variablePrice = hasVariablePrice(product);
  const installmentValue = price
    ? (parseFloat(price.amount) / 3).toFixed(2)
    : null;

  const {stars, count} = formatRating(handle);

  return (
    <div className="pdp">
      <div className="pdp-container">
        <PdpBreadcrumbs productTitle={title} collections={product.collections?.nodes ?? []} />

        <div className="pdp-main">
          <div className="pdp-main-gallery">
            <ProductImage
              image={selectedVariant?.image}
              productTitle={title}
              productHandle={handle}
            />
          </div>

          <aside className="pdp-main-panel" aria-label="Product details">
            <div className="pdp-main-panel-inner">
              <h1 className="pdp-title">{title}</h1>
              {vendor ? <p className="pdp-vendor">By {vendor}</p> : null}

              <a className="pdp-rating-row" href="#reviews">
                <PdpStarRow rating={stars} />
                <span className="pdp-rating-num">{stars.toFixed(1)}</span>
                <span aria-hidden="true" className="pdp-rating-dot">
                  ·
                </span>
                <span className="pdp-rating-count">
                  {count.toLocaleString()} reviews
                </span>
              </a>

              <div className="pdp-price-block">
                {price ? (
                  <span className="pdp-price">
                    {variablePrice ? <span>From </span> : null}
                    <Money data={price} />
                  </span>
                ) : null}
                {isOnSale && compareAt ? (
                  <s className="pdp-price-compare">
                    <Money data={compareAt} />
                  </s>
                ) : null}
              </div>

              {installmentValue ? (
                <p className="pdp-installments">
                  or 3 easy payments of ${installmentValue} —{' '}
                  <button type="button" className="pdp-installments-link">
                    Learn more
                  </button>
                </p>
              ) : null}

              <ProductForm
                productOptions={productOptions}
                selectedVariant={selectedVariant}
                productHandle={handle}
                productTitle={title}
                vendor={vendor}
              />

              <ProductAccordion product={product} />
            </div>
          </aside>
        </div>

        <ProductReviews productHandle={handle} productTitle={title} />

        <Suspense fallback={<ShopTheLookSkeleton />}>
          <Await resolve={recommendedProducts}>
            {(response) => (
              <ShopTheLook
                products={response ? response.products.nodes : null}
                currentHandle={handle}
              />
            )}
          </Await>
        </Suspense>

        <ProductEditorialBlocks />
      </div>

      <PdpStickyBar productTitle={title} selectedVariant={selectedVariant} />
      <FreeShippingBar selectedVariant={selectedVariant} />

      <Analytics.ProductView
        data={{
          products: [
            {
              id: product.id,
              title: product.title,
              price: selectedVariant?.price.amount || '0',
              vendor: product.vendor,
              variantId: selectedVariant?.id || '',
              variantTitle: selectedVariant?.title || '',
              quantity: 1,
            },
          ],
        }}
      />
    </div>
  );
}

function ShopTheLookSkeleton() {
  return (
    <section className="pdp-shop-look pdp-shop-look-skeleton" aria-hidden="true">
      <div className="pdp-section-head">
        <p className="pdp-section-eyebrow">Curated by Stylists</p>
        <h2 className="pdp-section-heading">Shop the Look</h2>
      </div>
      <div className="pdp-shop-look-track">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="pdp-shop-look-card">
            <div
              className="pdp-shop-look-card-frame"
              style={{background: 'linear-gradient(135deg, #efe6d6 0%, #c5a47e 100%)'}}
            />
            <div className="pdp-shop-look-card-body">
              <div className="skeleton-line skeleton-line-title" />
              <div className="skeleton-line skeleton-line-price" />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function hasVariablePrice(product: {
  adjacentVariants?: Array<{price: {amount: string}}>;
  selectedOrFirstAvailableVariant?: {price: {amount: string}} | null;
}): boolean {
  const prices = new Set<string>();
  const sel = product.selectedOrFirstAvailableVariant?.price.amount;
  if (sel) prices.add(sel);
  for (const v of product.adjacentVariants ?? []) {
    if (v?.price?.amount) prices.add(v.price.amount);
  }
  return prices.size > 1;
}

function PdpStarRow({rating}: {rating: number}) {
  const fullStars = Math.floor(rating);
  const half = rating - fullStars >= 0.5 ? 1 : 0;
  const empty = 5 - fullStars - half;
  return (
    <span className="pdp-rating-stars" aria-hidden="true">
      {Array.from({length: fullStars}).map((_, i) => (
        <PdpStar key={`f-${i}`} fill="currentColor" />
      ))}
      {half ? <PdpStar key="h" fill="currentColor" half /> : null}
      {Array.from({length: empty}).map((_, i) => (
        <PdpStar key={`e-${i}`} fill="none" />
      ))}
    </span>
  );
}

function PdpStar({fill, half}: {fill: string; half?: boolean}) {
  if (half) {
    return (
      <svg width="16" height="16" viewBox="0 0 14 14" aria-hidden="true">
        <defs>
          <linearGradient id="pdp-half-grad">
            <stop offset="50%" stopColor="currentColor" />
            <stop offset="50%" stopColor="transparent" />
          </linearGradient>
        </defs>
        <path
          d="M7 1l1.9 3.9 4.3.6-3.1 3 .7 4.3L7 10.7 3.2 12.8l.7-4.3-3.1-3 4.3-.6L7 1z"
          fill="url(#pdp-half-grad)"
          stroke="currentColor"
          strokeWidth="0.6"
        />
      </svg>
    );
  }
  return (
    <svg width="16" height="16" viewBox="0 0 14 14" aria-hidden="true">
      <path
        d="M7 1l1.9 3.9 4.3.6-3.1 3 .7 4.3L7 10.7 3.2 12.8l.7-4.3-3.1-3 4.3-.6L7 1z"
        fill={fill}
        stroke="currentColor"
        strokeWidth="0.6"
      />
    </svg>
  );
}

const PRODUCT_VARIANT_FRAGMENT = `#graphql
  fragment ProductVariant on ProductVariant {
    availableForSale
    compareAtPrice {
      amount
      currencyCode
    }
    id
    image {
      __typename
      id
      url
      altText
      width
      height
    }
    price {
      amount
      currencyCode
    }
    product {
      title
      handle
    }
    selectedOptions {
      name
      value
    }
    sku
    title
    unitPrice {
      amount
      currencyCode
    }
  }
` as const;

const PRODUCT_FRAGMENT = `#graphql
  fragment Product on Product {
    id
    title
    vendor
    handle
    descriptionHtml
    description
    options {
      name
      optionValues {
        name
        firstSelectableVariant {
          ...ProductVariant
        }
        swatch {
          color
          image {
            previewImage {
              url
            }
          }
        }
      }
    }
    selectedOrFirstAvailableVariant(selectedOptions: $selectedOptions, ignoreUnknownOptions: true, caseInsensitiveMatch: true) {
      ...ProductVariant
    }
  }
  ${PRODUCT_VARIANT_FRAGMENT}
` as const;

const PRODUCT_QUERY = `#graphql
  query Product(
    $country: CountryCode
    $handle: String!
    $language: LanguageCode
    $selectedOptions: [SelectedOptionInput!]!
  ) @inContext(country: $country, language: $language) {
    product(handle: $handle) {
      ...Product
    }
  }
  ${PRODUCT_FRAGMENT}
` as const;

const SHOP_THE_LOOK_QUERY = `#graphql
  fragment RecommendedProduct on Product {
    id
    title
    handle
    priceRange {
      minVariantPrice {
        amount
        currencyCode
      }
    }
    featuredImage {
      id
      url
      altText
      width
      height
    }
  }
  query ShopTheLookProducts ($country: CountryCode, $language: LanguageCode)
    @inContext(country: $country, language: $language) {
    products(first: 6, sortKey: UPDATED_AT, reverse: true) {
      nodes {
        ...RecommendedProduct
      }
    }
  }
` as const;
