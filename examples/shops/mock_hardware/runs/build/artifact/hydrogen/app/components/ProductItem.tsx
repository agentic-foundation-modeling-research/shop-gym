import {Link} from 'react-router';
import {Image, Money} from '@shopify/hydrogen';
import type {
  ProductItemFragment,
  CollectionItemFragment,
} from 'storefrontapi.generated';
import {useVariantUrl} from '~/lib/variants';

type ProductItemProps = {
  product: CollectionItemFragment | ProductItemFragment;
  loading?: 'eager' | 'lazy';
};

export function ProductItem({product, loading}: ProductItemProps) {
  const variantUrl = useVariantUrl(product.handle);
  const image = product.featuredImage;
  const available =
    'availableForSale' in product ? product.availableForSale : true;
  const description = 'description' in product ? product.description : null;
  const subtitle = description ? truncateOneLine(description, 90) : null;

  return (
    <Link
      className="product-item"
      key={product.id}
      prefetch="intent"
      to={variantUrl}
    >
      <div className="product-item-media">
        {image ? (
          <Image
            alt={image.altText || product.title}
            aspectRatio="1/1"
            data={image}
            loading={loading}
            sizes="(min-width: 60em) 380px, (min-width: 45em) 50vw, 100vw"
            className="product-item-image"
          />
        ) : (
          <ProductItemPlaceholder />
        )}
        <span
          className={
            'product-item-badge ' +
            (available ? 'product-item-badge-instock' : 'product-item-badge-oos')
          }
        >
          {available ? 'In stock' : 'Sold out'}
        </span>
      </div>
      <div className="product-item-body">
        <h3 className="product-item-title">{product.title}</h3>
        {subtitle ? <p className="product-item-subtitle">{subtitle}</p> : null}
        <div className="product-item-price">
          <Money data={product.priceRange.minVariantPrice} />
        </div>
      </div>
    </Link>
  );
}

function truncateOneLine(text: string, maxChars: number): string {
  const single = text.replace(/\s+/g, ' ').trim();
  if (single.length <= maxChars) return single;
  return single.slice(0, maxChars - 1).trimEnd() + '…';
}

function ProductItemPlaceholder() {
  return (
    <div className="product-item-placeholder" aria-hidden="true">
      <svg width="56" height="56" viewBox="0 0 48 48" fill="none">
        <rect width="48" height="48" rx="4" fill="#f0ede8" />
        <path d="M17 31l5-7 4 5 6-8 7 10H9l8-10z" fill="#d4cfc7" />
        <circle cx="18" cy="19" r="3" fill="#d4cfc7" />
      </svg>
    </div>
  );
}
