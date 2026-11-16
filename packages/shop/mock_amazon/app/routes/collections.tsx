import { Form, Link, type LoaderFunctionArgs, useLoaderData } from 'react-router';
import { ImageFrame, Price } from '~/components/storefront';
import { FilterRail } from './collection';
import { getAppContext } from '~/lib/context';
import { COLLECTION_QUERY, COLLECTIONS_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { CollectionDetail, CollectionSummary } from '~/lib/types';

interface CollectionsData { readonly collections: { readonly nodes: readonly CollectionSummary[] } }
interface DetailData { readonly collection: CollectionDetail | null }
export function meta() { return [{ title: 'Shop departments' }]; }
export async function loader({ context }: LoaderFunctionArgs) {
  const app = getAppContext(context);
  const [directory, detail] = await Promise.all([
    storefrontQuery<CollectionsData>(app, COLLECTIONS_QUERY),
    storefrontQuery<DetailData>(app, COLLECTION_QUERY, { handle: 'video-games', filters: [], after: null }),
  ]);
  return { directory, detail };
}
export default function Collections() {
  const { directory, detail } = useLoaderData<typeof loader>();
  const collection = detail.collection;
  const categories = directory.collections.nodes.filter(c => c.handle !== 'video-games').slice(0, 12);
  const products = collection?.products.nodes ?? [];
  return <main className="collections-directory page-width">
    <nav className="collection-crumb" aria-label="Breadcrumb"><Link to="/">Home</Link> › <span>Video Games</span></nav>
    <header className="directory-heading"><p className="collection-eyebrow">EXPLORE THE DEPARTMENT</p><h1>Video Games &amp; more</h1><p>Shop games, consoles, accessories and more from across the collection.</p></header>
    <div className="collection-feature-links"><Link to="/collections/video-games">Shop all Video Games</Link><Link to="#browse-platforms">Shop by platform</Link><Link to="#featured-products">Featured products</Link></div>
    <div className="collection-layout">
      {collection && <FilterRail filters={collection.products.filters} title={collection.title}/>}
      <div className="collection-main">
        <section className="collection-hero directory-browse-hero"><div><span>FEATURED DEPARTMENT</span><h2>Discover your next adventure</h2><p>Find new favorites and everyday essentials for every player.</p><Link className="directory-feature-cta" to="/collections/video-games">Explore Video Games →</Link></div><div className="collection-hero-images">{products.slice(0,3).map(product => <Link key={product.id} to={`/products/${product.handle}`}><ImageFrame image={product.featuredImage} altFallback={product.title}/></Link>)}</div></section>
        <section className="directory-browse-module" id="browse-platforms"><div className="directory-section-head"><h2>Shop by category</h2><Link to="/collections/video-games">See all ›</Link></div><div className="directory-browse-categories">{categories.slice(0,6).map(item => <Link className="directory-browse-category" key={item.id} to={`/collections/${item.handle}`}><span className="directory-browse-category-media">{item.image ? <ImageFrame image={item.image} altFallback={item.title}/> : <span aria-hidden="true">✦</span>}</span><strong>{item.title}</strong></Link>)}</div></section>
        <section className="directory-browse-module" id="featured-products"><div className="directory-section-head"><h2>Featured in Video Games</h2><Link to="/collections/video-games">Shop all ›</Link></div><div className="directory-results-bar"><span>1–16 of {collection?.products.totalCount?.toLocaleString() ?? products.length} results</span><Form method="get" action="/collections/video-games" className="collection-sort"><label htmlFor="directory-sort">Sort by:</label><select id="directory-sort" name="sort" defaultValue="featured" onChange={event => event.currentTarget.form?.requestSubmit()}><option value="featured">Featured</option><option value="price-asc">Price: Low to High</option><option value="price-desc">Price: High to Low</option><option value="reviews">Average Customer Review</option><option value="newest">Release Date</option><option value="best">Best Sellers</option></select></Form></div><div className="directory-browse-products">{products.slice(0,4).map(item => <Link className="directory-browse-product" key={item.id} to={`/products/${item.handle}`}><div className="directory-browse-product-media"><ImageFrame image={item.featuredImage} altFallback={item.title}/></div><span>{item.title}</span><strong><Price money={item.priceRange.minVariantPrice}/></strong><small>FREE delivery available</small></Link>)}</div><nav className="directory-page-links" aria-label="Browse product pages"><span aria-current="page">1</span><Link to="/collections/video-games?page=2">2</Link><Link to="/collections/video-games?page=2">Next ›</Link></nav></section>
        <section className="directory-browse-module directory-more"><div className="directory-section-head"><h2>Explore more ways to play</h2><Link to="/collections/video-games">Browse department ›</Link></div><div className="directory-category-grid">{categories.slice(6,10).map(item => <Link key={item.id} className="directory-category-card" to={`/collections/${item.handle}`}>{item.title}<span aria-hidden="true">→</span></Link>)}</div></section>
        <section className="directory-browse-module directory-all"><h2>More ways to shop</h2><div className="directory-all-links">{directory.collections.nodes.slice(10,30).map(item => <Link key={item.id} to={`/collections/${item.handle}`}>{item.title} <span>›</span></Link>)}</div></section>
      </div>
    </div>
  </main>;
}
