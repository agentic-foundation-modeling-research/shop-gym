import {
  Form,
  useLoaderData,
  useLocation,
  type LoaderFunctionArgs,
} from 'react-router';
import {
  Price,
  ProductImageGallery,
  VariantChoices,
} from '~/components/storefront';
import {getAppContext} from '~/lib/context';
import {PRODUCT_QUERY} from '~/lib/queries';
import {storefrontQuery} from '~/lib/storefront';
import type {ProductDetail} from '~/lib/types';

interface ProductData {
  readonly product: ProductDetail | null;
}

interface ProductLoaderData {
  readonly product: ProductDetail;
}

export function meta({
  data,
}: {
  readonly data: ProductLoaderData | undefined;
}) {
  return [{title: data?.product?.title ?? 'Product'}];
}

export async function loader({
  context,
  params,
}: LoaderFunctionArgs): Promise<ProductLoaderData> {
  if (!params.handle) {
    throw new Response('Missing product handle.', {status: 400});
  }
  const data = await storefrontQuery<ProductData>(
    getAppContext(context),
    PRODUCT_QUERY,
    {handle: params.handle},
  );
  const product = data.product;
  if (!product) {
    throw new Response('Product not found.', {status: 404});
  }
  return {product};
}

export default function Product() {
  const {product} = useLoaderData<typeof loader>();
  const location = useLocation();
  const selectedVariant = product.selectedOrFirstAvailableVariant;
  const redirectTo = withCartOpenParam(location);
  return (
    <div className="page-width product-layout">
      <ProductImageGallery
        images={product.images.nodes}
        fallbackImage={selectedVariant?.image ?? product.featuredImage}
        title={product.title}
      />
      <section className="stack" aria-labelledby="product-heading">
        <h1 id="product-heading">{product.title}</h1>
        <p className="muted">{product.vendor}</p>
        <p>
          <Price
            money={
              selectedVariant?.price ?? product.priceRange.minVariantPrice
            }
          />
        </p>
        <Form method="post" action="/cart" className="product-form" reloadDocument>
          <input type="hidden" name="redirectTo" value={redirectTo} />
          <input type="hidden" name="intent" value="add" />
          <VariantChoices variants={product.variants.nodes} />
          <label>
            Quantity
            <input
              type="number"
              name="quantity"
              min="1"
              defaultValue="1"
              required
            />
          </label>
          <button type="submit" disabled={!selectedVariant?.availableForSale}>
            Add to cart
          </button>
        </Form>
        <section className="product-description">
          <h2>Description</h2>
          <div dangerouslySetInnerHTML={{__html: product.descriptionHtml}} />
        </section>
      </section>
    </div>
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
