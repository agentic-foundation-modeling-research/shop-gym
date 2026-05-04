import {Link} from 'react-router';
import {Image, Money} from '@shopify/hydrogen';
import {AddToCartButton} from '~/components/AddToCartButton';
import {ProductPlaceholder} from '~/components/ProductPlaceholder';
import {useAside} from '~/components/Aside';
import type {CurrencyCode} from '@shopify/hydrogen/storefront-api-types';

type Money = {amount: string; currencyCode: CurrencyCode};

export type RecommendedProduct = {
  id: string;
  title: string;
  handle: string;
  featuredImage?: {
    id?: string | null;
    url: string;
    altText?: string | null;
    width?: number | null;
    height?: number | null;
  } | null;
  priceRange: {
    minVariantPrice: Money;
  };
  variants?: {
    nodes: Array<{
      id: string;
      availableForSale?: boolean | null;
    }>;
  } | null;
};

export function ProductRecommendations({
  title,
  products,
}: {
  title: string;
  products: RecommendedProduct[];
}) {
  if (!products.length) return null;
  return (
    <section className="pdp-recs section-container" aria-label={title}>
      <div className="pdp-recs-header">
        <h2 className="pdp-recs-title">{title}</h2>
      </div>
      <div className="pdp-recs-grid">
        {products.slice(0, 6).map((product) => (
          <Link
            key={product.id}
            to={`/products/${product.handle}`}
            className="pdp-recs-card"
            prefetch="intent"
          >
            <div className="pdp-recs-media">
              {product.featuredImage ? (
                <Image
                  data={product.featuredImage}
                  alt={product.featuredImage.altText || product.title}
                  aspectRatio="4/5"
                  sizes="(min-width: 900px) 220px, 50vw"
                />
              ) : (
                <ProductPlaceholder className="pdp-recs-placeholder" />
              )}
            </div>
            <div className="pdp-recs-meta">
              <h3 className="pdp-recs-product-title">{product.title}</h3>
              <div className="pdp-recs-price">
                <Money data={product.priceRange.minVariantPrice} />
              </div>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

export function FrequentlyBoughtTogether({
  primary,
  companions,
}: {
  primary: RecommendedProduct;
  companions: RecommendedProduct[];
}) {
  const {open} = useAside();
  const trio = [primary, ...companions].slice(0, 3);
  if (trio.length < 2) return null;

  const total = trio.reduce(
    (sum, item) => sum + parseFloat(item.priceRange.minVariantPrice.amount),
    0,
  );

  const lines = trio
    .map((product) => product.variants?.nodes?.[0]?.id)
    .filter((id): id is string => Boolean(id))
    .map((id) => ({merchandiseId: id, quantity: 1}));

  return (
    <section className="pdp-fbt section-container" aria-label="Frequently bought together">
      <h2 className="pdp-fbt-title">Frequently Bought Together</h2>
      <div className="pdp-fbt-row">
        {trio.map((product, index) => (
          <FBTItem key={product.id} product={product} showPlus={index < trio.length - 1} />
        ))}
      </div>
      <div className="pdp-fbt-summary">
        <span className="pdp-fbt-total">
          Total:{' '}
          <strong>
            <Money
              data={{
                amount: total.toFixed(2),
                currencyCode: primary.priceRange.minVariantPrice.currencyCode,
              }}
            />
          </strong>
        </span>
        {lines.length ? (
          <AddToCartButton
            className="pdp-fbt-cta"
            disabled={!lines.length}
            lines={lines}
            onClick={() => open('cart')}
          >
            Add all {trio.length} to cart
          </AddToCartButton>
        ) : null}
      </div>
    </section>
  );
}

function FBTItem({product, showPlus}: {product: RecommendedProduct; showPlus: boolean}) {
  return (
    <>
      <Link to={`/products/${product.handle}`} className="pdp-fbt-card" prefetch="intent">
        <div className="pdp-fbt-media">
          {product.featuredImage ? (
            <Image
              data={product.featuredImage}
              alt={product.featuredImage.altText || product.title}
              aspectRatio="1/1"
              sizes="160px"
            />
          ) : (
            <ProductPlaceholder className="pdp-fbt-placeholder" />
          )}
        </div>
        <div className="pdp-fbt-meta">
          <span className="pdp-fbt-name">{product.title}</span>
          <span className="pdp-fbt-price">
            <Money data={product.priceRange.minVariantPrice} />
          </span>
        </div>
      </Link>
      {showPlus ? (
        <span className="pdp-fbt-plus" aria-hidden="true">
          +
        </span>
      ) : null}
    </>
  );
}
