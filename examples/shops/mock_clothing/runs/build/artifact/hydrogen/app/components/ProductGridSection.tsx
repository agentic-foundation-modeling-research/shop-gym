import {Suspense} from 'react';
import {Await, Link} from 'react-router';
import {ProductItem, type ProductItemRich} from '~/components/ProductItem';

type ProductGridResponse = {
  collection: {
    products: {nodes: ProductItemRich[]};
  } | null;
} | null;

interface ProductGridSectionProps {
  products: Promise<ProductGridResponse>;
  eyebrow: string;
  heading: string;
  subline?: string;
  viewAllLabel: string;
  viewAllUrl: string;
  /** Maximum number of products to render (default 4 — one row). */
  limit?: number;
}

export function ProductGridSection({
  products,
  eyebrow,
  heading,
  subline,
  viewAllLabel,
  viewAllUrl,
  limit = 4,
}: ProductGridSectionProps) {
  return (
    <section className="featured-products-section">
      <div className="featured-products-header">
        <div className="featured-products-heading-text">
          <span className="section-eyebrow">{eyebrow}</span>
          <h2 className="section-heading section-heading-serif">{heading}</h2>
          {subline ? <p className="section-subline">{subline}</p> : null}
        </div>
        <Link
          to={viewAllUrl}
          prefetch="intent"
          className="section-view-all"
        >
          {viewAllLabel} →
        </Link>
      </div>
      <Suspense fallback={<ProductGridSkeleton count={limit} />}>
        <Await resolve={products}>
          {(response) => (
            <div className="featured-products-track">
              {response?.collection?.products.nodes
                .slice(0, limit)
                .map((product) => (
                  <ProductItem key={product.id} product={product} />
                )) ?? null}
            </div>
          )}
        </Await>
      </Suspense>
    </section>
  );
}

function ProductGridSkeleton({count}: {count: number}) {
  return (
    <div className="featured-products-track">
      {Array.from({length: count}).map((_, i) => (
        <div key={i} className="product-card-skeleton">
          <div className="product-card-skeleton-image" />
          <div className="product-card-skeleton-line" />
          <div className="product-card-skeleton-line product-card-skeleton-line-short" />
        </div>
      ))}
    </div>
  );
}
