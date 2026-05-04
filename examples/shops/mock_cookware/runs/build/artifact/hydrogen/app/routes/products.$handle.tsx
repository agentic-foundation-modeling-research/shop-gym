import {Suspense, useMemo, useState} from 'react';
import {Await, Link, useLoaderData} from 'react-router';
import type {Route} from './+types/products.$handle';
import {
  Analytics,
  getAdjacentAndFirstAvailableVariants,
  getProductOptions,
  getSelectedProductOptions,
  Money,
  useOptimisticVariant,
  useSelectedOptionInUrlParam,
} from '@shopify/hydrogen';
import {ProductPrice} from '~/components/ProductPrice';
import {ProductImage, type GalleryImage} from '~/components/ProductImage';
import {ProductForm} from '~/components/ProductForm';
import {
  ProductAccordion,
  type AccordionSection,
} from '~/components/ProductAccordion';
import {ProductReviews} from '~/components/ProductReviews';
import {
  FrequentlyBoughtTogether,
  ProductRecommendations,
  type RecommendedProduct,
} from '~/components/ProductRecommendations';
import {TrustBadges} from '~/components/TrustBadges';
import {AttributeStrip} from '~/components/AttributeStrip';
import {SizeGuideModal} from '~/components/SizeGuideModal';
import {FinancingModal} from '~/components/FinancingModal';
import {redirectIfHandleIsLocalized} from '~/lib/redirect';

export const meta: Route.MetaFunction = ({data}) => {
  return [
    {title: `Mock Cookware | ${data?.product.title ?? 'Product'}`},
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

  const [{product}, collectionsResult] = await Promise.all([
    storefront.query(PRODUCT_QUERY, {
      variables: {handle, selectedOptions: getSelectedProductOptions(request)},
    }),
    storefront.query(COLLECTION_HANDLES_QUERY),
  ]);

  if (!product?.id) {
    throw new Response(null, {status: 404});
  }

  redirectIfHandleIsLocalized(request, {handle, data: product});

  const collectionHandles =
    collectionsResult?.collections?.nodes?.map(
      (c: {handle: string}) => c.handle,
    ) ?? [];

  return {product, collectionHandles};
}

function loadDeferredData({context}: Route.LoaderArgs) {
  const recommended = context.storefront
    .query(RECOMMENDATIONS_QUERY)
    .catch((error: Error) => {
      console.error('Failed to load recommendations', error);
      return null;
    });
  return {recommended};
}

export default function Product() {
  const {product, recommended, collectionHandles} =
    useLoaderData<typeof loader>();

  const selectedVariant = useOptimisticVariant(
    product.selectedOrFirstAvailableVariant,
    getAdjacentAndFirstAvailableVariants(product),
  );

  useSelectedOptionInUrlParam(selectedVariant.selectedOptions);

  const productOptions = getProductOptions({
    ...product,
    selectedOrFirstAvailableVariant: selectedVariant,
  });

  const [sizeGuideOpen, setSizeGuideOpen] = useState(false);
  const [financingOpen, setFinancingOpen] = useState(false);

  const galleryImages = useMemo<GalleryImage[]>(() => {
    const seen = new Set<string>();
    const images: GalleryImage[] = [];
    const push = (image?: GalleryImage | null) => {
      if (!image || !image.url) return;
      const key = image.id || image.url;
      if (seen.has(key)) return;
      seen.add(key);
      images.push(image);
    };
    push(selectedVariant?.image);
    product.images?.nodes?.forEach((image: GalleryImage) => push(image));
    product.options?.forEach((option: {optionValues?: Array<{firstSelectableVariant?: {image?: GalleryImage | null} | null}>}) => {
      option.optionValues?.forEach((value) => {
        const variantImage = value.firstSelectableVariant?.image;
        push(variantImage as GalleryImage | undefined);
      });
    });
    return images;
  }, [product.images, product.options, selectedVariant?.image]);

  const productType = product.productType ?? '';
  const tags = product.tags ?? [];
  const isApparel = /^Apparel/i.test(productType);
  const isCookware = /^(Cookware|Bakeware)/i.test(productType);
  const hasNonstickTag = tags.some((t: string) => /nonstick/i.test(t));
  const hasInductionTag = tags.some((t: string) => /induction/i.test(t));
  const isMultiPiece = /Sets?$/i.test(productType);
  const breadcrumb = parseBreadcrumb(productType, collectionHandles);

  const accordionSections = buildAccordionSections({
    descriptionHtml: product.descriptionHtml,
    productType,
    isMultiPiece,
    title: product.title,
    hasNonstickTag,
    hasInductionTag,
  });

  const featureCallouts = buildFeatureCallouts({
    isApparel,
    isCookware,
    hasNonstickTag,
    hasInductionTag,
  });

  const attributeFlags = {
    warranty: true,
    utensilSafe: hasNonstickTag,
    nonstick: hasNonstickTag,
    ovenSafe: isCookware,
    dishwasherSafe: !isApparel,
    inductionReady: hasInductionTag || isCookware,
    stayCoolHandle: isCookware,
  };

  const recommendationsTitle = isApparel
    ? 'You may also like'
    : 'Customers also love';

  return (
    <div className="pdp">
      <div className="pdp-breadcrumbs section-container">
        <nav aria-label="Breadcrumb">
          <ol>
            <li>
              <Link to="/">Home</Link>
            </li>
            {breadcrumb.map((crumb) => (
              <li key={crumb.url}>
                <Link to={crumb.url}>{crumb.label}</Link>
              </li>
            ))}
            <li aria-current="page">{product.title}</li>
          </ol>
        </nav>
      </div>

      <div className="pdp-hero section-container">
        <ProductImage images={galleryImages} productTitle={product.title} />

        <div className="pdp-info">
          {product.vendor ? (
            <p className="pdp-vendor">{product.vendor}</p>
          ) : null}
          <h1 className="pdp-title">{product.title}</h1>
          <RatingSummary handle={product.handle} />

          <div className="pdp-price-block">
            <ProductPrice
              price={selectedVariant?.price}
              compareAtPrice={selectedVariant?.compareAtPrice}
            />
            {selectedVariant?.price ? (
              <div className="pdp-financing-line">
                <span>
                  4 payments of{' '}
                  <strong>
                    <Money
                      data={{
                        amount: (
                          parseFloat(selectedVariant.price.amount) / 4
                        ).toFixed(2),
                        currencyCode: selectedVariant.price.currencyCode,
                      }}
                    />
                  </strong>{' '}
                  with installments
                </span>
                <button
                  type="button"
                  className="pdp-financing-link"
                  onClick={() => setFinancingOpen(true)}
                >
                  Check purchase power
                </button>
              </div>
            ) : null}
          </div>

          <TrustBadges hasLifetimeWarranty={isCookware || /knives/i.test(productType)} />

          <ProductForm
            productOptions={productOptions}
            selectedVariant={selectedVariant}
            onOpenSizeGuide={isApparel ? () => setSizeGuideOpen(true) : undefined}
          />

          {featureCallouts.length > 0 && (
            <ul className="pdp-feature-callouts">
              {featureCallouts.map((feature) => (
                <li key={feature.term}>
                  <strong>{feature.term}.</strong> {feature.body}
                </li>
              ))}
            </ul>
          )}

          <ProductAccordion sections={accordionSections} />

          <AttributeStrip active={attributeFlags} />
        </div>
      </div>

      <ProductReviews
        productHandle={product.handle}
        productTitle={product.title}
      />

      <Suspense fallback={null}>
        <Await resolve={recommended} errorElement={null}>
          {(resolved) => {
            const products = collectProducts(resolved, product.handle);
            if (!products.length) return null;
            return (
              <>
                {products.length >= 2 ? (
                  <FrequentlyBoughtTogether
                    primary={toRecommended(product, selectedVariant)}
                    companions={products.slice(0, 2)}
                  />
                ) : null}
                <ProductRecommendations
                  title={recommendationsTitle}
                  products={products}
                />
              </>
            );
          }}
        </Await>
      </Suspense>

      <SizeGuideModal
        open={sizeGuideOpen}
        onClose={() => setSizeGuideOpen(false)}
      />
      <FinancingModal
        open={financingOpen}
        onClose={() => setFinancingOpen(false)}
        price={selectedVariant?.price}
      />

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

function RatingSummary({handle}: {handle: string}) {
  const hash = useMemo(() => {
    let h = 0;
    for (let i = 0; i < handle.length; i++) {
      h = (h << 5) - h + handle.charCodeAt(i);
      h |= 0;
    }
    return Math.abs(h);
  }, [handle]);

  const rating = Math.round((4.2 + (hash % 70) / 100) * 10) / 10;
  const count = 36 + (hash % 740);
  const full = Math.floor(rating);
  const half = rating - full >= 0.5;

  return (
    <a href="#reviews" className="pdp-rating">
      <span className="pdp-rating-stars" aria-hidden="true">
        {Array.from({length: 5}).map((_, idx) => {
          let cls = 'pdp-rating-star';
          if (idx < full) cls += ' is-full';
          else if (idx === full && half) cls += ' is-half';
          return (
            <span key={idx} className={cls}>
              ★
            </span>
          );
        })}
      </span>
      <span className="pdp-rating-text">
        {rating.toFixed(1)} · {count.toLocaleString()} reviews
      </span>
    </a>
  );
}

function parseBreadcrumb(
  productType: string,
  collectionHandles: string[],
): Array<{label: string; url: string}> {
  if (!productType) return [];
  const knownHandles = new Set(collectionHandles);
  const crumbs: Array<{label: string; url: string}> = [];
  for (const segment of productType.split(':')) {
    const handle = slug(segment);
    if (!handle || !knownHandles.has(handle)) continue;
    crumbs.push({label: humanize(segment), url: `/collections/${handle}`});
  }
  return crumbs;
}

function slug(value: string): string {
  return value
    .replace(/([a-z])([A-Z])/g, '$1-$2')
    .replace(/[^a-zA-Z0-9-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .toLowerCase();
}

function humanize(value: string): string {
  return value
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .trim();
}

function buildAccordionSections({
  descriptionHtml,
  productType,
  isMultiPiece,
  title,
  hasNonstickTag,
  hasInductionTag,
}: {
  descriptionHtml: string;
  productType: string;
  isMultiPiece: boolean;
  title: string;
  hasNonstickTag: boolean;
  hasInductionTag: boolean;
}): AccordionSection[] {
  const details = [
    hasNonstickTag
      ? 'Coating: triple-layer reinforced nonstick, PFOA-free'
      : 'Surface: hard-anodized exterior with polished interior',
    'Material: heavy-gauge aluminum core for even heat distribution',
    'Handle: stay-cool stainless handle with riveted attachment',
    'Lid: tempered glass lid included for select sizes',
    'Base: encapsulated stainless base for warp resistance',
    'Finish: matte ceramic exterior, fingerprint-resistant',
    'Care: dishwasher-safe; hand-wash recommended for longevity',
    'Oven-safe to 500°F (260°C)',
    hasInductionTag
      ? 'Stovetop: induction, gas, electric, ceramic, halogen'
      : 'Stovetop: gas, electric, ceramic, halogen',
    'Made for daily use across burners',
  ];

  const sections: AccordionSection[] = [
    {
      id: 'description',
      label: 'Description',
      type: 'html',
      html:
        descriptionHtml && descriptionHtml.trim().length
          ? descriptionHtml
          : `<p>${title} is built for daily home cooking with materials that hold up over years of use.</p>`,
    },
    {id: 'details', label: 'Details', type: 'list', items: details},
  ];

  if (isMultiPiece || /set/i.test(productType)) {
    sections.push({
      id: 'components',
      label: 'Set Includes',
      type: 'list',
      items: [
        '10-inch frypan',
        '12-inch frypan',
        '2-quart saucepan with lid',
        '4-quart saucepan with lid',
        '6-quart stockpot with lid',
        'Tempered glass lids (3)',
      ],
    });
  }

  return sections;
}

function buildFeatureCallouts({
  isApparel,
  isCookware,
  hasNonstickTag,
  hasInductionTag,
}: {
  isApparel: boolean;
  isCookware: boolean;
  hasNonstickTag: boolean;
  hasInductionTag: boolean;
}): Array<{term: string; body: string}> {
  if (isApparel) {
    return [
      {term: 'Heavyweight cotton', body: 'Holds its shape through hundreds of washes.'},
      {term: 'Crossback ties', body: 'Distribute weight off the neck for long sessions.'},
      {term: 'Deep front pocket', body: 'Built for thermometers, towels, and tongs.'},
      {term: 'Reinforced stitching', body: 'Box-stitched stress points refuse to fray.'},
      {term: 'Adjustable fit', body: 'Sized from XS to XXL with a forgiving cut.'},
      {term: 'Designed in-house', body: 'Tested in pro kitchens before it ships to yours.'},
    ];
  }
  if (!isCookware) return [];
  return [
    {
      term: 'Even-heat core',
      body: hasNonstickTag
        ? 'Aluminum core sandwiched in stainless eliminates hot spots.'
        : 'Three-ply construction holds steady heat from edge to edge.',
    },
    {
      term: hasNonstickTag ? 'Triple nonstick' : 'Slick stainless',
      body: hasNonstickTag
        ? 'Reinforced nonstick releases food cleanly without oil.'
        : 'A polished interior browns without sticking when properly heated.',
    },
    {
      term: 'Stay-cool handle',
      body: 'Engineered to remain comfortable through long simmers.',
    },
    {
      term: 'Oven-safe to 500°F',
      body: 'Move from stovetop to oven without swapping vessels.',
    },
    {
      term: hasInductionTag ? 'Induction-ready' : 'Versatile base',
      body: hasInductionTag
        ? 'Magnetic base works on every modern cooktop.'
        : 'Compatible with gas, electric, ceramic, and halogen.',
    },
    {
      term: 'Lifetime warranty',
      body: 'Covered for the life of the product when used as directed.',
    },
  ];
}

function collectProducts(
  resolved: RecommendationsQuery | null,
  excludeHandle: string,
): RecommendedProduct[] {
  if (!resolved) return [];
  const seen = new Set<string>();
  const list: RecommendedProduct[] = [];
  const sources = [
    resolved.alsoLove?.products?.nodes ?? [],
    resolved.bestSellers?.products?.nodes ?? [],
  ];
  for (const source of sources) {
    for (const node of source) {
      if (!node || node.handle === excludeHandle || seen.has(node.handle)) continue;
      seen.add(node.handle);
      list.push(node);
      if (list.length >= 8) return list;
    }
  }
  return list;
}

function toRecommended(
  product: ProductLoaderData['product'],
  variant: ProductLoaderData['product']['selectedOrFirstAvailableVariant'],
): RecommendedProduct {
  const minPrice = variant?.price ?? {amount: '0', currencyCode: 'USD'};
  return {
    id: product.id,
    title: product.title,
    handle: product.handle,
    featuredImage: variant?.image
      ? {
          id: variant.image.id,
          url: variant.image.url,
          altText: variant.image.altText,
          width: variant.image.width,
          height: variant.image.height,
        }
      : null,
    priceRange: {minVariantPrice: minPrice},
    variants: variant
      ? {
          nodes: [
            {
              id: variant.id,
              availableForSale: variant.availableForSale,
            },
          ],
        }
      : null,
  };
}

type ProductLoaderData = Awaited<ReturnType<typeof loadCriticalData>>;

type RecommendationsQuery = {
  alsoLove?: {
    products?: {nodes: RecommendedProduct[]};
  } | null;
  bestSellers?: {
    products?: {nodes: RecommendedProduct[]};
  } | null;
};

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
    productType
    tags
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

const COLLECTION_HANDLES_QUERY = `#graphql
  query CollectionHandles {
    collections(first: 250) {
      nodes {
        handle
      }
    }
  }
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

const RECOMMENDATIONS_PRODUCT_FRAGMENT = `#graphql
  fragment RecommendationProduct on Product {
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

const RECOMMENDATIONS_QUERY = `#graphql
  ${RECOMMENDATIONS_PRODUCT_FRAGMENT}
  query Recommendations($country: CountryCode, $language: LanguageCode)
    @inContext(country: $country, language: $language) {
    alsoLove: collection(handle: "best-sellers") {
      id
      products(first: 8) {
        nodes {
          ...RecommendationProduct
        }
      }
    }
    bestSellers: collection(handle: "new-arrivals") {
      id
      products(first: 8) {
        nodes {
          ...RecommendationProduct
        }
      }
    }
  }
` as const;
