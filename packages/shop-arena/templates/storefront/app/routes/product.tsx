import { Form, type LoaderFunctionArgs, useLoaderData, useLocation } from 'react-router';
import { RatingBlock, ReviewsSection } from '~/components/reviews';
import { Price, ProductImageGallery, VariantChoices } from '~/components/storefront';
import { getAppContext } from '~/lib/context';
import { PRODUCT_QUERY } from '~/lib/queries';
import { REVIEW_PAGE_SIZE, type ReviewView, productRatingOf, reviewViewOf } from '~/lib/reviews';
import { storefrontQuery } from '~/lib/storefront';
import type { ProductDetail } from '~/lib/types';

interface ProductData {
  readonly product: ProductDetail | null;
}

interface ProductLoaderData {
  readonly product: ProductDetail;
  readonly reviewView: ReviewView;
}

export function meta({
  data,
}: {
  readonly data: ProductLoaderData | undefined;
}) {
  return [{ title: data?.product?.title ?? 'Product' }];
}

export async function loader({
  context,
  params,
  request,
}: LoaderFunctionArgs): Promise<ProductLoaderData> {
  if (!params.handle) {
    throw new Response('Missing product handle.', { status: 400 });
  }
  const reviewView = reviewViewOf(new URL(request.url));
  const data = await storefrontQuery<ProductData>(getAppContext(context), PRODUCT_QUERY, {
    handle: params.handle,
    reviewsFirst: REVIEW_PAGE_SIZE * reviewView.pages,
    reviewsSortKey: reviewView.sort.sortKey,
  });
  const product = data.product;
  if (!product) {
    throw new Response('Product not found.', { status: 404 });
  }
  return { product, reviewView };
}

export default function Product() {
  const { product, reviewView } = useLoaderData<typeof loader>();
  const location = useLocation();
  const selectedVariant = product.selectedOrFirstAvailableVariant;
  const redirectTo = withCartOpenParam(location);
  const rating = productRatingOf(product);
  return (
    <>
      <div className="page-width product-layout">
        <ProductImageGallery
          images={product.images.nodes}
          fallbackImage={selectedVariant?.image ?? product.featuredImage}
          title={product.title}
        />
        <section className="stack" aria-labelledby="product-heading">
          <h1 id="product-heading">{product.title}</h1>
          {rating ? <RatingBlock rating={rating} /> : null}
          <p className="muted">{product.vendor}</p>
          <p>
            <Price money={selectedVariant?.price ?? product.priceRange.minVariantPrice} />
          </p>
          <Form method="post" action="/cart" className="product-form" reloadDocument>
            <input type="hidden" name="redirectTo" value={redirectTo} />
            <input type="hidden" name="intent" value="add" />
            <VariantChoices variants={product.variants.nodes} />
            <label>
              Quantity
              <input type="number" name="quantity" min="1" defaultValue="1" required />
            </label>
            <button type="submit" disabled={!selectedVariant?.availableForSale}>
              Add to cart
            </button>
          </Form>
          <section className="product-description">
            <h2>Description</h2>
            <div
              // biome-ignore lint/security/noDangerouslySetInnerHtml: description is trusted dataset HTML
              dangerouslySetInnerHTML={{ __html: product.descriptionHtml }}
            />
          </section>
        </section>
      </div>
      <ReviewsSection
        productPath={location.pathname}
        reviews={product.reviews.nodes}
        hasNextPage={product.reviews.pageInfo.hasNextPage}
        rating={rating}
        view={reviewView}
      />
    </>
  );
}

function withCartOpenParam(location: {
  readonly pathname: string;
  readonly search: string;
  readonly hash: string;
}): string {
  const params = new URLSearchParams(location.search);
  params.set('cart', 'open');
  const search = params.toString();
  return `${location.pathname}${search ? `?${search}` : ''}${location.hash}`;
}
