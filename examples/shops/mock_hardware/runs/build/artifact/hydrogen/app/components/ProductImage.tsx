import {Image} from '@shopify/hydrogen';
import type {ProductVariantFragment} from 'storefrontapi.generated';

export function ProductImage({
  image,
  title,
}: {
  image: ProductVariantFragment['image'];
  title: string;
}) {
  if (!image) {
    return (
      <div className="product-gallery">
        <div className="product-gallery-placeholder" aria-hidden="true">
          <svg width="64" height="64" viewBox="0 0 48 48" fill="none">
            <rect width="48" height="48" rx="4" fill="#f0ede8" />
            <path d="M17 31l5-7 4 5 6-8 7 10H9l8-10z" fill="#d4cfc7" />
            <circle cx="18" cy="19" r="3" fill="#d4cfc7" />
          </svg>
          <span>{title}</span>
        </div>
      </div>
    );
  }
  return (
    <div className="product-gallery">
      <div className="product-gallery-frame">
        <Image
          alt={image.altText || title}
          aspectRatio="1/1"
          data={image}
          key={image.id}
          sizes="(min-width: 45em) 50vw, 100vw"
        />
      </div>
    </div>
  );
}
