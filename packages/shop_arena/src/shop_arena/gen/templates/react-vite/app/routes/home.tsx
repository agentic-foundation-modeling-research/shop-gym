import {Link, useLoaderData, type LoaderFunctionArgs} from 'react-router';
import {
  CollectionGrid,
  ProductGrid,
} from '~/components/storefront';
import {getAppContext} from '~/lib/context';
import {HOME_QUERY} from '~/lib/queries';
import {storefrontQuery} from '~/lib/storefront';
import type {
  CollectionSummary,
  ProductSummary,
  Shop,
} from '~/lib/types';

interface HomeData {
  readonly shop: Shop;
  readonly collections: {
    readonly nodes: readonly CollectionSummary[];
  };
  readonly products: {
    readonly nodes: readonly ProductSummary[];
  };
}

export function meta() {
  return [{title: 'Storefront'}];
}

export async function loader({
  context,
}: LoaderFunctionArgs): Promise<HomeData> {
  return storefrontQuery<HomeData>(getAppContext(context), HOME_QUERY);
}

export default function Home() {
  const data = useLoaderData<typeof loader>();
  return (
    <div className="page-width stack">
      <section className="stack" aria-labelledby="home-heading">
        <h1 id="home-heading">{data.shop.name}</h1>
        <p>{data.shop.description}</p>
      </section>

      <section className="stack" aria-labelledby="featured-products">
        <div className="section-heading">
          <h2 id="featured-products">Featured products</h2>
          <Link to="/collections">View collections</Link>
        </div>
        <ProductGrid products={data.products.nodes} />
      </section>

      <section className="stack" aria-labelledby="featured-collections">
        <h2 id="featured-collections">Collections</h2>
        <CollectionGrid collections={data.collections.nodes} />
      </section>
    </div>
  );
}
