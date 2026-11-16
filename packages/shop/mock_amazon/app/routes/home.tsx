import { useRef } from 'react';
import { Link, type LoaderFunctionArgs, useLoaderData } from 'react-router';
import { ImageFrame, Price } from '~/components/storefront';
import { getAppContext } from '~/lib/context';
import { HOME_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { CollectionSummary, ProductSummary, Shop } from '~/lib/types';

interface HomeData {
  readonly shop: Shop;
  readonly collections: { readonly nodes: readonly CollectionSummary[] };
  readonly products: { readonly nodes: readonly ProductSummary[] };
  readonly devices: { readonly nodes: readonly ProductSummary[] };
}

export function meta() { return [{ title: 'Discover more | Storefront' }]; }

export async function loader({ context }: LoaderFunctionArgs): Promise<HomeData> {
  return storefrontQuery<HomeData>(getAppContext(context), HOME_QUERY);
}

const themes = [
  'Find something for everyone', 'Fresh finds for your collection',
  'Make playtime memorable', 'Stories worth sharing',
  'Explore premium picks', 'Gear up for the next adventure',
  'More to discover', 'Great finds at every price',
];
const tileWords = ['Explore more', 'See the selection', 'Shop the edit', 'Find your favorite'];
const promoLines = [
  ['A little more to love', 'Discover something new today'],
  ['Make room for fun', 'Find your next favorite'],
  ['Your next great find', 'Everyday discoveries await'],
  ['Ready for anything', 'Explore more ways to play'],
  ['A fresh perspective', 'See what’s new in store'],
  ['The gift of discovery', 'Find something just right'],
];
const deviceLines = [
  ['Big adventures ahead', 'Explore a world of play'],
  ['Take fun along', 'Discover entertainment anywhere'],
  ['Make every moment count', 'Find your new favorite'],
  ['More ways to play', 'Explore the collection'],
  ['All together now', 'Something for everyone'],
  ['Discover what’s next', 'Browse the complete selection'],
];
const colors = ['plum', 'teal', 'coral', 'lime', 'blue', 'orange'];

function Rail({ children, className, label }: { children: React.ReactNode; className: string; label: string }) {
  const rail = useRef<HTMLDivElement>(null);
  return <div className={`home-rail-wrap ${className}`}>
    <div className="home-rail" ref={rail} aria-label={label}>{children}</div>
    <button type="button" className="home-rail-next" aria-label={`Next ${label}`} onClick={() => rail.current?.scrollBy({ left: rail.current.clientWidth * .78, behavior: 'smooth' })}>›</button>
  </div>;
}

export default function Home() {
  const { shop, products, devices, collections } = useLoaderData<typeof loader>();
  const all = products.nodes.filter(p => p.featuredImage);
  const consolePicks = devices.nodes.filter(p => p.featuredImage);
  const promoted = [all[0], all[7], all[15], all[23], all[30], all[35]].filter((p): p is ProductSummary => !!p);
  const devicePicks = [consolePicks[4], consolePicks[5], consolePicks[6], consolePicks[8], consolePicks[10], consolePicks[11]].filter((p): p is ProductSummary => !!p);
  const collection = (i: number) => collections.nodes[i % collections.nodes.length];
  return <div className="homepage">
    <h1 className="visually-hidden">Welcome to {shop.name}</h1>
    <div className="home-content">
      <Rail className="hero-rail" label="featured promotions">
        {promoted.map((product, i) => <Link key={product.id} to={`/products/${product.handle}`} className={`home-promo tone-${colors[i]}`} aria-label={`${promoLines[i]?.[0]}: ${product.title}`}>
          <div className="promo-copy"><span className="promo-eyebrow">Find more to enjoy</span><strong>{promoLines[i]?.[0]}</strong><span>{promoLines[i]?.[1]}</span></div>
          <div className="promo-photo"><ImageFrame image={product.featuredImage} altFallback={product.title} /></div>
          <span className="promo-bottom">Shop now <span aria-hidden="true">↗</span></span>
        </Link>)}
      </Rail>
      <div className="home-quad-grid">
        {themes.map((heading, i) => {
          const featured = all.slice(i * 4, i * 4 + 4);
          const category = collection(i);
          return <section className="home-quad" key={heading}>
            <h2><Link to={category ? `/collections/${category.handle}` : '/collections'}>{heading}<span aria-hidden="true"> ›</span></Link></h2>
            <div className="quad-tiles">{featured.map((product, j) => <Link key={product.id} to={`/products/${product.handle}`} className="quad-tile">
              <span className="quad-image"><ImageFrame image={product.featuredImage} altFallback={product.title} /></span>
              <span>{j === 0 ? 'Top picks' : tileWords[j]}</span>
            </Link>)}</div>
            <Link className="quad-more" to={category ? `/collections/${category.handle}` : '/collections'}>Explore the collection</Link>
          </section>;
        })}
      </div>
      <section className="home-device-section">
        <div className="home-section-head"><h2>Discover more ways to play</h2><Link to="/collections/video-games">Shop all ›</Link></div>
        <Rail className="device-rail" label="featured devices">
          {devicePicks.map((product, i) => <Link key={product.id} to={`/products/${product.handle}`} className={`home-promo tone-${colors[(i + 2) % colors.length]}`}>
            <div className="promo-copy"><span className="promo-eyebrow">Explore the collection</span><strong>{deviceLines[i]?.[0]}</strong><span>{deviceLines[i]?.[1]}</span></div>
            <div className="promo-photo"><ImageFrame image={product.featuredImage} altFallback={product.title} /></div>
            <span className="promo-bottom">Discover more <span aria-hidden="true">↗</span></span>
          </Link>)}
        </Rail>
      </section>
    </div>
    <section className="home-recommendations" aria-labelledby="recommendation-heading">
      <div className="home-section-head"><h2 id="recommendation-heading">Inspired by your browsing history</h2><div className="home-recommendation-actions"><Link to="/collections/video-games">Explore more ›</Link><Link to="/cart">View cart ›</Link></div></div>
      <div className="recommendation-row">{(consolePicks.length ? consolePicks : all).slice(0, 6).map(product => <article className="recommendation-card" key={product.id}>
        <Link to={`/products/${product.handle}`} className="recommendation-image"><ImageFrame image={product.featuredImage} altFallback={product.title} /></Link>
        <Link className="recommendation-title" to={`/products/${product.handle}`}>{product.title}</Link>
        <span className="muted">{product.vendor}</span>
        <Link className="recommendation-price" to={`/products/${product.handle}`}><Price money={product.priceRange.minVariantPrice} /></Link>
        <span className="recommendation-delivery">See delivery options at checkout</span>
      </article>)}</div>
      <div className="home-signin"><h2>See personalized recommendations</h2><Link className="button-link" to="/account/login">Sign in</Link><p>New customer? <Link to="/account/register">Start here.</Link></p></div>
    </section>
  </div>;
}
