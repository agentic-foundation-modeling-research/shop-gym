import { Form, Link, type LoaderFunctionArgs, useLoaderData, useLocation } from 'react-router';
import { ImageFrame, Price } from '~/components/storefront';
import { getAppContext } from '~/lib/context';
import { productFiltersOf, toggleFilterHref } from '~/lib/facets';
import { COLLECTION_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { CollectionDetail, Filter, ProductSummary } from '~/lib/types';

interface CollectionData { readonly collection: CollectionDetail | null }
interface CollectionLoaderData { readonly collection: CollectionDetail; readonly page: number; readonly sort: string; readonly filtered: boolean }
const SORTS = [
  ['featured', 'Featured'], ['price-asc', 'Price: Low to High'], ['price-desc', 'Price: High to Low'],
  ['reviews', 'Average Customer Review'], ['newest', 'Release Date'], ['best', 'Best Sellers'],
] as const;
export function meta({ data }: { readonly data: CollectionLoaderData | undefined }) {
  return [{ title: data?.collection?.title ?? 'Collection' }];
}
export async function loader({ context, params, request }: LoaderFunctionArgs): Promise<CollectionLoaderData> {
  if (!params.handle) throw new Response('Missing collection handle.', { status: 400 });
  const url = new URL(request.url);
  const page = Math.max(1, Math.min(625, Number.parseInt(url.searchParams.get('page') ?? '1', 10) || 1));
  const sort = SORTS.some(([key]) => key === url.searchParams.get('sort')) ? url.searchParams.get('sort')! : 'featured';
  const filters = productFiltersOf(url);
  const data = await storefrontQuery<CollectionData>(getAppContext(context), COLLECTION_QUERY, {
    handle: params.handle, filters, after: page > 1 ? btoa(`cursor:${(page - 1) * 16 - 1}`) : null,
  });
  if (!data.collection) throw new Response('Collection not found.', { status: 404 });
  return { collection: data.collection, page, sort, filtered: filters.length > 0 };
}
function urlWith(search: string, changes: Record<string, string | null>) {
  const p = new URLSearchParams(search);
  for (const [key, value] of Object.entries(changes)) value === null ? p.delete(key) : p.set(key, value);
  return `?${p.toString()}`;
}
export function FilterRail({ filters, title }: { filters: readonly Filter[]; title: string }) {
  const location = useLocation();
  const searchLocation = { pathname: '/search', search: `?q=${encodeURIComponent(title)}&${location.search.slice(1)}` };
  return <aside className="collection-rail" aria-label="Refine results">
    <details className="collection-mobile-filters"><summary>Filter & refine results</summary><div className="collection-mobile-filter-links"><a href="#collection-filter-groups">Browse all filters ↓</a><Link to={`/search?q=${encodeURIComponent(title)}`}>See results</Link></div></details>
    <div id="collection-filter-groups"><h2>Shop by category</h2>
    <Link className="collection-rail-head" to="/collections">All departments</Link>
    <Link className="collection-rail-head" to="/collections/video-games">Video Games</Link>
    {filters.filter(f => f.type !== 'PRICE_RANGE').map(filter => <section key={filter.id} className="collection-filter">
      <h3>{filter.label === 'Category' ? 'Department' : filter.label === 'Rating' ? 'Customer Reviews' : filter.label}</h3>
      <div className="collection-filter-options">
        {filter.values.slice(0, 6).map(value => <Link key={value.id} to={toggleFilterHref(searchLocation, value)} className="collection-filter-option"><span className="collection-filter-box" aria-hidden="true"/>{value.label}<span className="collection-filter-count">({value.count.toLocaleString()})</span></Link>)}
        {filter.values.length > 6 && <details><summary>See more</summary><div className="collection-filter-options">{filter.values.slice(6, 20).map(value => <Link key={value.id} to={toggleFilterHref(searchLocation, value)} className="collection-filter-option"><span className="collection-filter-box" aria-hidden="true"/>{value.label}</Link>)}</div></details>}
      </div>
    </section>)}
    {['Delivery day', 'Membership eligibility', 'Free shipping', 'Condition', 'Deals and discounts', 'Release date', 'Seller', 'Premium brands'].map(group => <section className="collection-filter" key={group}><h3>{group}</h3><Link className="collection-filter-option" to={`/search?q=${encodeURIComponent(title)}`}><span className="collection-filter-box" aria-hidden="true"/>Explore {group.toLowerCase()}</Link></section>)}
    <section className="collection-filter"><h3>Price</h3><div className="collection-price-links">{[[0,25],[25,50],[50,100],[100,200]].map(([min,max]) => <Link key={min} to={`/search?q=${encodeURIComponent(title)}&filter.price.min=${min}&filter.price.max=${max}`}>${min} to ${max}</Link>)}</div></section>
    </div>
  </aside>;
}
function ListingCard({ product }: { product: ProductSummary }) {
  return <article className="collection-listing"><Link className="collection-listing-image" to={`/products/${product.handle}`}><ImageFrame image={product.featuredImage} altFallback={product.title}/></Link><div className="collection-listing-info"><Link to={`/products/${product.handle}`} className="collection-listing-title">{product.title}</Link><p className="collection-listing-vendor">by {product.vendor}</p><p className="collection-listing-price"><Price money={product.priceRange.minVariantPrice}/></p><p className="collection-delivery">FREE delivery available</p><Link className="collection-shop-button" to={`/products/${product.handle}`}>See options</Link></div></article>;
}
export default function Collection() {
  const { collection, page, sort, filtered } = useLoaderData<typeof loader>();
  const location = useLocation();
  const items = [...collection.products.nodes];
  if (sort === 'price-asc' || sort === 'price-desc') items.sort((a,b) => (Number(a.priceRange.minVariantPrice.amount) - Number(b.priceRange.minVariantPrice.amount)) * (sort === 'price-desc' ? -1 : 1));
  if (sort === 'newest') items.reverse();
  const total = collection.products.totalCount ?? items.length;
  const last = Math.max(1, Math.ceil(total / 16));
  const browse = !filtered && page === 1 && sort === 'featured';
  return <main className="collection-page page-width">
    <nav className="collection-crumb" aria-label="Breadcrumb"><Link to="/">Home</Link> › <Link to="/collections">Departments</Link> › <span>{collection.title}</span></nav>
    <header className="collection-heading"><div><p className="collection-eyebrow">SHOP THE DEPARTMENT</p><h1>{collection.title}</h1><p>Explore great finds, new arrivals and everyday favorites.</p></div></header>
    {browse && <div className="collection-feature-links"><Link to="/collections">Shop all departments</Link><Link to="#featured-products">Featured products</Link><Link to="/account/login">Personalized recommendations</Link></div>}
    <div className="collection-layout"><FilterRail filters={collection.products.filters} title={collection.title}/><div className="collection-main" id="results">
      {browse && <section className="collection-hero"><div><span>EXPLORE MORE</span><h2>Find your next favorite</h2><p>Browse games, accessories, and more from across the department.</p><Link to="#featured-products">Shop now →</Link></div><div className="collection-hero-images">{items.slice(2,5).map(product => <Link key={product.id} to={`/products/${product.handle}`}><ImageFrame image={product.featuredImage} altFallback={product.title}/></Link>)}</div></section>}
      {browse && <section className="collection-categories"><h2>Shop by category</h2><div className="collection-category-links">{collection.products.filters.find(f => f.label === 'Category')?.values.slice(0,8).map(value => <Link key={value.id} to={toggleFilterHref({pathname:'/search',search:`?q=${encodeURIComponent(collection.title)}`},value)}>{value.label} <span>›</span></Link>)}<Link to="/collections">All categories <span>›</span></Link></div></section>}
      <section id="featured-products" className="collection-products"><div className="collection-results-head"><div><h2>{browse ? 'Featured products' : 'Results'}</h2><p>{total > 0 ? `${(page-1)*16+1}–${Math.min(page*16,total)} of ${total.toLocaleString()} results` : 'No results found'}</p></div><Form method="get" className="collection-sort" action={location.pathname}>{[...new URLSearchParams(location.search)].filter(([key]) => key !== 'sort' && key !== 'page').map(([key,value]) => <input key={key+value} type="hidden" name={key} value={value}/>)}<label htmlFor="collection-sort">Sort by:</label><select id="collection-sort" name="sort" value={sort} onChange={event => event.currentTarget.form?.requestSubmit()}>{SORTS.map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></Form></div>
      {browse ? <div className="collection-product-rail">{items.slice(0,4).map(product => <Link className="collection-rail-product" to={`/products/${product.handle}`} key={product.id}><div className="collection-rail-product-image"><ImageFrame image={product.featuredImage} altFallback={product.title}/></div><span>{product.title}</span><strong><Price money={product.priceRange.minVariantPrice}/></strong><small>FREE delivery available</small></Link>)}</div> : <div className="collection-listings">{items.map(product => <ListingCard product={product} key={product.id}/>)}</div>}
      {!items.length && <p>No products match these filters. <Link to={location.pathname}>Browse all products</Link></p>}
      <nav className="collection-pagination" aria-label="Results pages">{page > 1 ? <Link to={urlWith(location.search,{page:String(page-1)})}>‹ Previous</Link> : <span className="disabled">‹ Previous</span>}{[...new Set([1,page-1,page,page+1,last].filter(n=>n>=1 && n<=last))].sort((a,b)=>a-b).map((n,index,arr) => <span key={n}>{index > 0 && n - arr[index-1]! > 1 && <span className="page-ellipsis">…</span>}{n === page ? <span className="active" aria-current="page">{n}</span> : <Link to={urlWith(location.search,{page:String(n)})}>{n}</Link>}</span>)}{page < last ? <Link to={urlWith(location.search,{page:String(page+1)})}>Next ›</Link> : <span className="disabled">Next ›</span>}</nav>
      </section>
    </div></div>
  </main>;
}
