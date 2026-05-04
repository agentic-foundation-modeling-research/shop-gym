import {useLoaderData, Link} from 'react-router';
import type {Route} from './+types/products.$handle';
import {
  getSelectedProductOptions,
  Analytics,
  Money,
  useOptimisticVariant,
  getProductOptions,
  getAdjacentAndFirstAvailableVariants,
  useSelectedOptionInUrlParam,
} from '@shopify/hydrogen';
import {ProductImage} from '~/components/ProductImage';
import {ProductForm} from '~/components/ProductForm';
import {TrustBadges} from '~/components/TrustBadges';
import {
  ProductAccordion,
  type AccordionSection,
} from '~/components/ProductAccordion';
import {redirectIfHandleIsLocalized} from '~/lib/redirect';

export const meta: Route.MetaFunction = ({data}) => {
  return [
    {title: `Mock Hardware | ${data?.product.title ?? ''}`},
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

function loadDeferredData(_args: Route.LoaderArgs) {
  return {};
}

const SHOP_PAY_THRESHOLD = 50;

export default function Product() {
  const {product} = useLoaderData<typeof loader>();

  const selectedVariant = useOptimisticVariant(
    product.selectedOrFirstAvailableVariant,
    getAdjacentAndFirstAvailableVariants(product),
  );

  useSelectedOptionInUrlParam(selectedVariant.selectedOptions);

  const productOptions = getProductOptions({
    ...product,
    selectedOrFirstAvailableVariant: selectedVariant,
  });

  const {title, descriptionHtml, vendor, productType, tags} = product;

  // Single-image gallery — image does not change with variant selection
  const galleryImage = product.featuredImage ?? selectedVariant?.image ?? null;

  const priceAmount = Number(selectedVariant?.price?.amount ?? '0');
  const showShopPay =
    selectedVariant?.availableForSale && priceAmount >= SHOP_PAY_THRESHOLD;

  const sections = buildAccordionSections({
    descriptionHtml,
    vendor,
    productType,
    tags,
    sku: selectedVariant?.sku,
  });

  return (
    <div className="pdp">
      <nav className="pdp-breadcrumbs" aria-label="Breadcrumb">
        <Link to="/">Home</Link>
        <span aria-hidden="true">/</span>
        <Link to="/collections">Shop</Link>
        <span aria-hidden="true">/</span>
        <span aria-current="page">{title}</span>
      </nav>

      <div className="pdp-grid">
        <ProductImage image={galleryImage} title={title} />

        <div className="pdp-main">
          {vendor ? <p className="pdp-vendor">{vendor}</p> : null}
          <h1 className="pdp-title">{title}</h1>

          <div className="pdp-price">
            {selectedVariant?.price ? <Money data={selectedVariant.price} /> : null}
            {selectedVariant?.compareAtPrice ? (
              <s>
                <Money data={selectedVariant.compareAtPrice} />
              </s>
            ) : null}
          </div>

          {showShopPay ? (
            <p className="pdp-shop-pay">
              4 interest-free payments with{' '}
              <strong>Shop Pay</strong>
            </p>
          ) : null}

          <ProductForm
            productOptions={productOptions}
            selectedVariant={selectedVariant}
          />

          <TrustBadges />

          {product.description ? (
            <p className="pdp-short-description">{product.description}</p>
          ) : null}

          <ProductAccordion sections={sections} />
        </div>
      </div>

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

function buildAccordionSections({
  descriptionHtml,
  vendor,
  productType,
  tags,
  sku,
}: {
  descriptionHtml: string;
  vendor?: string | null;
  productType?: string | null;
  tags?: string[] | null;
  sku?: string | null;
}): AccordionSection[] {
  const featuredTags = (tags ?? []).slice(0, 6);
  const featureItems: {key: string; detail: string}[] = featuredTags.map(
    (tag) => {
      const key = tag
        .replace(/[-_]/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase());
      return {key, detail: tagDetail(tag, productType ?? '')};
    },
  );

  return [
    {
      id: 'features',
      label: 'Features',
      content:
        featureItems.length > 0 ? (
          <ul className="product-accordion-features">
            {featureItems.map((item) => (
              <li key={item.key}>
                <strong>{item.key}</strong>
                {item.detail ? <span> — {item.detail}</span> : null}
              </li>
            ))}
          </ul>
        ) : (
          <div
            className="product-accordion-rich"
            dangerouslySetInnerHTML={{__html: descriptionHtml || ''}}
          />
        ),
    },
    {
      id: 'tech-specs',
      label: 'Tech Specs',
      content: (
        <dl className="product-accordion-specs">
          {productType ? (
            <>
              <dt>Category</dt>
              <dd>{productType}</dd>
            </>
          ) : null}
          {vendor ? (
            <>
              <dt>Brand</dt>
              <dd>{vendor}</dd>
            </>
          ) : null}
          {sku ? (
            <>
              <dt>SKU</dt>
              <dd>{sku}</dd>
            </>
          ) : null}
          <dt>Warranty</dt>
          <dd>1-year limited manufacturer warranty</dd>
          <dt>Power</dt>
          <dd>USB-C powered (cable included where applicable)</dd>
        </dl>
      ),
    },
    {
      id: 'compatibility',
      label: 'Compatibility',
      content: (
        <ul className="product-accordion-bullets">
          <li>Works with Shopify POS on iPad and iPhone</li>
          <li>Compatible with most major countertop POS systems</li>
          <li>USB-C and Bluetooth pairing options where supported</li>
          <li>No proprietary lock-in — open standards throughout</li>
        </ul>
      ),
    },
    {
      id: 'whats-included',
      label: "What's Included",
      content: (
        <ul className="product-accordion-bullets">
          <li>1× {productType || 'Product'} unit</li>
          <li>Quick-start guide</li>
          <li>USB-C cable (where applicable)</li>
          <li>Manufacturer warranty card</li>
        </ul>
      ),
    },
    {
      id: 'manufacturer',
      label: 'From the Manufacturer',
      content: (
        <div
          className="product-accordion-rich"
          dangerouslySetInnerHTML={{__html: descriptionHtml || ''}}
        />
      ),
    },
  ];
}

function tagDetail(tag: string, productType: string): string {
  const t = tag.toLowerCase();
  if (t.includes('wireless')) return 'Cable-free pairing for clean countertops';
  if (t.includes('usb')) return 'Plug-and-play USB-C connectivity';
  if (t.includes('bluetooth')) return 'Reliable Bluetooth pairing';
  if (t.includes('compact') || t.includes('small'))
    return 'Compact footprint that fits any counter';
  if (t.includes('countertop')) return 'Designed for retail countertop use';
  if (t.includes('barcode') || t.includes('label'))
    return 'High-contrast print quality for fast scanning';
  if (t.includes('thermal')) return 'No-ink thermal printing keeps costs low';
  if (t.includes('rechargeable') || t.includes('battery'))
    return 'Long battery life across a busy shift';
  if (t.includes('durable') || t.includes('hardware'))
    return 'Built for daily retail wear and tear';
  if (productType) return `${productType} accessory you can rely on`;
  return 'Engineered for small-business retail';
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
    productType
    tags
    handle
    descriptionHtml
    description
    featuredImage {
      __typename
      id
      url
      altText
      width
      height
    }
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
