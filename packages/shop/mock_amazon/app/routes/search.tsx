import { Form, Link, type LoaderFunctionArgs, useLoaderData, useLocation } from 'react-router';
import { ImageFrame, Price } from '~/components/storefront';
import { getAppContext } from '~/lib/context';
import { productFiltersOf, toggleFilterHref } from '~/lib/facets';
import { SEARCH_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { Filter, Page, ProductSummary } from '~/lib/types';

interface ArticleResult { readonly __typename: 'Article'; readonly id: string; readonly handle: string; readonly title: string; readonly contentHtml: string; readonly blog: { readonly handle: string } }
interface ProductResult extends ProductSummary { readonly __typename: 'Product' }
interface PageResult extends Page { readonly __typename: 'Page' }
type SearchNode = ProductResult | PageResult | ArticleResult;
interface SearchData { readonly search: { readonly totalCount: number; readonly productFilters: readonly Filter[]; readonly nodes: readonly SearchNode[] } }
interface SearchLoaderData extends SearchData { readonly query: string; readonly sort: string; readonly page: number }
const SORTS = [['featured','Featured'],['price-asc','Price: Low to High'],['price-desc','Price: High to Low'],['reviews','Average Customer Review'],['newest','Release Date'],['best','Best Sellers']] as const;
export function meta({ data }: { readonly data: SearchLoaderData | undefined }) { return [{ title: data?.query ? `Results for ${data.query}` : 'Search products' }]; }
export async function loader({ context, request }: LoaderFunctionArgs): Promise<SearchLoaderData> {
  const url = new URL(request.url);
  const query = url.searchParams.get('q') ?? '';
  const page = Math.max(1, Math.min(3, Number(url.searchParams.get('page')) || 1));
  const sort = SORTS.some(([key]) => key === url.searchParams.get('sort')) ? url.searchParams.get('sort')! : 'featured';
  const data = await storefrontQuery<SearchData>(getAppContext(context), SEARCH_QUERY, { query, productFilters: productFiltersOf(url) });
  return { ...data, query, sort, page };
}
function withParams(search: string, changes: Record<string,string|null>) { const params = new URLSearchParams(search); for (const [k,v] of Object.entries(changes)) v === null ? params.delete(k) : params.set(k,v); return `?${params}`; }
export default function Search() {
  const {search,query,sort,page} = useLoaderData<typeof loader>();
  const location = useLocation();
  const products = search.nodes.filter((n): n is ProductResult => n.__typename === 'Product');
  const sorted = [...products];
  if (sort === 'price-asc' || sort === 'price-desc') sorted.sort((a,b) => (Number(a.priceRange.minVariantPrice.amount) - Number(b.priceRange.minVariantPrice.amount)) * (sort === 'price-desc' ? -1 : 1));
  if (sort === 'newest') sorted.reverse();
  const results = sorted.slice((page-1)*16,page*16);
  const total = search.totalCount;
  const last = Math.max(1, Math.min(3,Math.ceil(total/16)));
  return <div className="market-search">
    <div className="search-summary-bar"><div className="page-width"><span>{total ? `${(page-1)*16+1}–${Math.min(page*16,total)} of ${total.toLocaleString()} results` : 'No matching results'} for <strong>“{query}”</strong></span>{total > 0 && <Form method="get" className="collection-sort">{[...new URLSearchParams(location.search)].filter(([k]) => k !== 'sort' && k !== 'page').map(([k,v]) => <input type="hidden" name={k} value={v} key={k+v}/>)}<label htmlFor="search-sort">Sort by:</label><select id="search-sort" name="sort" value={sort} onChange={e=>e.currentTarget.form?.requestSubmit()}>{SORTS.map(([k,label])=><option key={k} value={k}>{label}</option>)}</select></Form>}</div></div>
    <div className="page-width search-page-layout">
      {total > 0 && <aside className="search-filter-rail" aria-label="Search filters"><details className="search-mobile-filters"><summary>Filter & refine results</summary></details><div className="search-filter-groups"><h2>Refine results</h2>{search.productFilters.map(filter => <section className="search-filter-group" key={filter.id}><h3>{filter.label}</h3>{filter.values.slice(0,9).map(value => <Link key={value.id} className="search-filter-value" to={toggleFilterHref(location,value)}><span className="collection-filter-box" aria-hidden="true"/>{value.label}</Link>)}</section>)}{['Free shipping','Delivery day','Deals and discounts','Customer reviews','Release date','Genre','Condition','Seller','Digital or physical format','Content age rating','Premium brands','Department'].filter(label => !search.productFilters.some(f=>f.label.toLowerCase()===label.toLowerCase())).map(label => <section className="search-filter-group" key={label}><h3>{label}</h3><Link to="/collections/video-games" className="search-filter-value">Browse {label.toLowerCase()}</Link></section>)}</div></aside>}
      <div className="search-list-column"><h1>{total ? 'Results' : 'Explore more products'}</h1><p className="search-hint">See product pages for more buying options and details.</p>
        {total ? <><div className="search-result-list">{results.map(product => <article className="search-result" key={product.id}><Link className="search-result-image" to={`/products/${product.handle}`}><ImageFrame image={product.featuredImage} altFallback={product.title}/></Link><div className="search-result-body"><Link className="search-result-title" to={`/products/${product.handle}`}>{product.title}</Link><p className="search-result-vendor">by {product.vendor}</p><p className="search-result-rating">★★★★☆ <span>Shopper favorites</span></p><p className="search-result-price"><Price money={product.priceRange.minVariantPrice}/></p><p className="search-result-delivery">FREE delivery available</p><Link className="collection-shop-button" to={`/products/${product.handle}`}>See options</Link></div></article>)}</div><nav className="collection-pagination" aria-label="Results pages">{page > 1 ? <Link to={withParams(location.search,{page:String(page-1)})}>‹ Previous</Link> : <span className="disabled">‹ Previous</span>}{Array.from({length:last},(_,i)=>i+1).map(n => n===page ? <span className="active" key={n} aria-current="page">{n}</span> : <Link key={n} to={withParams(location.search,{page:String(n)})}>{n}</Link>)}{page<last ? <Link to={withParams(location.search,{page:String(page+1)})}>Next ›</Link> : <span className="disabled">Next ›</span>}</nav></> : <div className="search-no-match"><p>We couldn't find an exact match. Discover more from our departments instead.</p><Link className="button-link" to="/collections">Browse all departments</Link></div>}
        <section className="search-bottom"><p>Need help? <Link to="/pages/help-center">Visit our help center</Link></p><h2>Recommended for you</h2><p>Sign in for personalized recommendations.</p><Link className="button-link" to="/account/login">Sign in</Link><p>New customer? <Link to="/account/register">Create an account</Link></p></section>
      </div>
    </div>
  </div>;
}
