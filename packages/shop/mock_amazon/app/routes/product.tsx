import { Form, Link, type LoaderFunctionArgs, useLoaderData, useLocation } from 'react-router';
import { RatingBlock, ReviewsSection } from '~/components/reviews';
import { Price, ProductGrid, ProductImageGallery, variantTitle } from '~/components/storefront';
import { getAppContext } from '~/lib/context';
import { PRODUCT_QUERY, PRODUCT_RECOMMENDATIONS_QUERY } from '~/lib/queries';
import { REVIEW_PAGE_SIZE, type ReviewView, productRatingOf, reviewViewOf } from '~/lib/reviews';
import { storefrontQuery } from '~/lib/storefront';
import type { ProductDetail, ProductSummary, ProductVariant } from '~/lib/types';

interface ProductData { readonly product: ProductDetail | null }
interface RecommendationsData { readonly productRecommendations: readonly ProductSummary[] | null }
interface ProductLoaderData {
  readonly product: ProductDetail;
  readonly reviewView: ReviewView;
  readonly recommendations: readonly ProductSummary[];
}

export function meta({ data }: { readonly data: ProductLoaderData | undefined }) {
  return [{ title: data?.product?.title ?? 'Product' }];
}

export async function loader({ context, params, request }: LoaderFunctionArgs): Promise<ProductLoaderData> {
  if (!params.handle) throw new Response('Missing product handle.', { status: 400 });
  const reviewView = reviewViewOf(new URL(request.url));
  const data = await storefrontQuery<ProductData>(getAppContext(context), PRODUCT_QUERY, {
    handle: params.handle,
    reviewsFirst: REVIEW_PAGE_SIZE * reviewView.pages,
    reviewsSortKey: reviewView.sort.sortKey,
    reviewsRating: reviewView.rating,
    reviewsVerifiedBuyer: reviewView.verifiedOnly ? true : null,
  });
  if (!data.product) throw new Response('Product not found.', { status: 404 });
  const recommended = await storefrontQuery<RecommendationsData>(
    getAppContext(context), PRODUCT_RECOMMENDATIONS_QUERY, { productId: data.product.id },
  );
  return { product: data.product, reviewView, recommendations: recommended.productRecommendations ?? [] };
}

export default function Product() {
  const { product, reviewView, recommendations } = useLoaderData<typeof loader>();
  const location = useLocation();
  const variants = product.variants.nodes;
  const variantParam = new URLSearchParams(location.search).get('variant');
  const selectedVariant = variants.find(v => v.id === variantParam) ?? product.selectedOrFirstAvailableVariant ?? variants[0];
  const rating = productRatingOf(product);
  const gallery = selectedVariant?.image && !product.images.nodes.some(image => image?.url === selectedVariant.image?.url)
    ? [selectedVariant.image, ...product.images.nodes] : product.images.nodes;
  const cartParams = new URLSearchParams(location.search);
  cartParams.set('cart', 'open');
  const redirectTo = `${location.pathname}?${cartParams.toString()}`;
  const excerpt = product.description.trim().replace(/&#(?:34|x22);/gi, '"').replace(/&#(?:38|x26);/gi, '&').replace(/\s+/g, ' ').slice(0, 340);
  return (
    <>
      <div className="product-sponsored">Explore more in <Link to="/collections/video-games">Video Games</Link> · Discover great finds across the store</div>
      <div className="page-width product-page">
        <nav className="product-breadcrumb" aria-label="Breadcrumb"><Link to="/collections">Departments</Link><span>›</span><Link to="/collections/video-games">Video Games</Link><span>›</span><Link to="/collections/video-games">{product.productType || 'Products'}</Link></nav>
        <div className="product-layout">
          <div className="product-gallery-column">
            <ProductImageGallery key={selectedVariant?.id ?? product.id} images={gallery} fallbackImage={selectedVariant?.image ?? product.featuredImage} title={product.title} />
            {gallery.filter(Boolean).length > 1 ? <p className="gallery-hint">Click a thumbnail to view another image</p> : null}
          </div>
          <section className="product-details" aria-labelledby="product-heading">
            <p className="product-brand">Visit the {product.vendor} store</p>
            <h1 id="product-heading">{product.title}</h1>
            <p className="product-type">{product.productType || 'Product'}</p>
            {rating ? <div className="product-rating"><RatingBlock rating={rating} histogram={product.ratingHistogram} productPath={location.pathname} view={reviewView} /><a href="#reviews">See customer reviews ↓</a></div> : null}
            <div className="product-summary-price"><span className="product-price"><Price money={selectedVariant?.price ?? product.priceRange.minVariantPrice} /></span>{selectedVariant?.compareAtPrice && Number(selectedVariant.compareAtPrice.amount) > Number(selectedVariant.price.amount) ? <span className="product-list-price">List price: <s><Price money={selectedVariant.compareAtPrice} /></s></span> : null}<p>FREE Returns · Shop with confidence</p></div>
            {variants.length > 1 ? <VariantSelector variants={variants} selected={selectedVariant} pathname={location.pathname} /> : null}
            <div className="product-bullets" id="item-bullets"><h2>About this item</h2><p>{excerpt}{product.description.length > 340 ? '…' : ''}</p><a href="#product-information">See more product details ↓</a></div>
          </section>
          <aside className="product-buy-column" id="buying-options" aria-label="Buying options">
            <div className="product-buy-box">
              <div className="buy-box-price"><Price money={selectedVariant?.price ?? product.priceRange.minVariantPrice} /></div>
              <p className="buy-delivery">FREE delivery available at checkout</p>
              <p>Delivering to <strong>United States</strong></p>
              <p className={selectedVariant?.availableForSale ? 'buy-stock' : 'buy-unavailable'}>{selectedVariant?.availableForSale ? 'In Stock' : 'Currently unavailable'}</p>
              <Form method="post" action="/cart" className="product-form" reloadDocument>
                <input type="hidden" name="redirectTo" value={redirectTo} />
                <input type="hidden" name="intent" value="add" />
                <input type="hidden" name="merchandiseId" value={selectedVariant?.id ?? ''} />
                <label htmlFor="buy-quantity">Quantity</label>
                <select id="buy-quantity" name="quantity" defaultValue="1">{Array.from({length: Math.min(10, Math.max(1, selectedVariant?.quantityAvailable ?? 10))}, (_, i) => <option key={i} value={i+1}>{i+1}</option>)}</select>
                <button className="product-add-button" type="submit" disabled={!selectedVariant?.availableForSale}>Add to cart</button>
              </Form>
              <Form method="post" action="/cart" reloadDocument><input type="hidden" name="intent" value="add" /><input type="hidden" name="merchandiseId" value={selectedVariant?.id ?? ''} /><input type="hidden" name="quantity" value="1" /><input type="hidden" name="redirectTo" value="/checkout" /><button className="product-buy-now" type="submit" disabled={!selectedVariant?.availableForSale}>Buy now</button></Form>
              <div className="buy-fulfillment"><span>Ships from</span><strong>Store</strong><span>Sold by</span><strong>{product.vendor}</strong><span>Returns</span><strong>Eligible at checkout</strong></div>
              <Link className="product-list-link" to="/account/login">Add to List</Link>
            </div>
            <Link className="product-other-sellers" to="/collections/video-games">Explore more buying options <span>›</span></Link>
          </aside>
        </div>
        <section className="product-information" id="product-information"><h2>Product information</h2><div className="product-facts"><div><strong>Product type</strong><span>{product.productType || 'General merchandise'}</span></div><div><strong>Brand</strong><span>{product.vendor}</span></div>{selectedVariant && variantTitle(selectedVariant.title) ? <div><strong>Style</strong><span>{selectedVariant.title}</span></div> : null}</div></section>
        <section className="product-description" id="product-description"><h2>Product description</h2><div dangerouslySetInnerHTML={{__html: product.descriptionHtml}} /></section>
        {recommendations.length > 0 ? <section className="product-related" aria-labelledby="related-products-heading"><h2 id="related-products-heading">You may also like</h2><ProductGrid products={recommendations} /></section> : null}
      </div>
      <ReviewsSection productPath={location.pathname} reviews={product.reviews} rating={rating} view={reviewView} />
    </>
  );
}

function VariantSelector({ variants, selected, pathname }: { readonly variants: readonly ProductVariant[]; readonly selected: ProductVariant | undefined; readonly pathname: string }) {
  const axes = [...new Set(variants.flatMap(v => v.selectedOptions.map(option => option.name)))].filter(name => name !== 'Title');
  return <div className="product-variant-picker" aria-label="Choose a variant">
    {axes.length > 0 ? axes.map(axis => {
      const choices = [...new Set(variants.map(v => v.selectedOptions.find(option => option.name === axis)?.value).filter((value): value is string => Boolean(value)))];
      return <div className="variant-axis" key={axis}><h2>{axis}: <strong>{selected?.selectedOptions.find(option => option.name === axis)?.value}</strong></h2><div className="variant-tiles">{choices.map(choice => {
        const match = variants.find(v => v.selectedOptions.some(option => option.name === axis && option.value === choice) && v.selectedOptions.every(option => option.name === axis || selected?.selectedOptions.find(s => s.name === option.name)?.value === option.value)) ?? variants.find(v => v.selectedOptions.some(option => option.name === axis && option.value === choice));
        return match ? <Link className={`variant-tile${match.id === selected?.id ? ' is-selected' : ''}${!match.availableForSale ? ' is-unavailable' : ''}`} aria-current={match.id === selected?.id ? 'true' : undefined} to={`${pathname}?variant=${encodeURIComponent(match.id)}`} key={choice}>{choice}</Link> : null;
      })}</div></div>;
    }) : <div className="variant-axis"><h2>Style: <strong>{variantTitle(selected?.title ?? '')}</strong></h2><div className="variant-tiles">{variants.map(v => <Link key={v.id} className={`variant-tile${v.id === selected?.id ? ' is-selected' : ''}`} to={`${pathname}?variant=${encodeURIComponent(v.id)}`}>{variantTitle(v.title) ?? 'Standard'}</Link>)}</div></div>}
  </div>;
}
