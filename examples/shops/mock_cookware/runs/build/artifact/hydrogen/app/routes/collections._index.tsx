import {useLoaderData, Link} from 'react-router';
import type {Route} from './+types/collections._index';
import {Image} from '@shopify/hydrogen';
import {ProductPlaceholder} from '~/components/ProductPlaceholder';

const FIRST = 60;

type CollectionTile = {
  id: string;
  title: string;
  handle: string;
  image?: {
    id?: string | null;
    url: string;
    altText?: string | null;
    width?: number | null;
    height?: number | null;
  } | null;
};

export const meta: Route.MetaFunction = () => {
  return [{title: 'Mock Cookware | Shop All Collections'}];
};

export async function loader({context}: Route.LoaderArgs) {
  const {collections} = await context.storefront.query(COLLECTIONS_QUERY, {
    variables: {first: FIRST},
  });
  return {collections};
}

export default function Collections() {
  const {collections} = useLoaderData<typeof loader>();
  const nodes = (collections?.nodes ?? []) as CollectionTile[];

  return (
    <div className="collections-index section-container">
      <header className="collections-index-header">
        <h1 className="collections-index-title">Shop all collections</h1>
        <p className="collections-index-subtitle">
          Browse our full range of cookware, knives, bakeware, and kitchen
          essentials.
        </p>
      </header>
      <div className="collections-tile-grid">
        {nodes.map((collection, index) => (
          <Link
            key={collection.id}
            to={`/collections/${collection.handle}`}
            prefetch="intent"
            className="collection-tile"
          >
            <div className="collection-tile-media">
              {collection.image ? (
                <Image
                  data={collection.image}
                  alt={collection.image.altText || collection.title}
                  aspectRatio="4/5"
                  loading={index < 6 ? 'eager' : 'lazy'}
                  sizes="(min-width: 900px) 33vw, 50vw"
                />
              ) : (
                <ProductPlaceholder className="collection-tile-placeholder" />
              )}
              <span className="collection-tile-overlay" aria-hidden="true" />
            </div>
            <div className="collection-tile-meta">
              <h2 className="collection-tile-title">{collection.title}</h2>
              <span className="collection-tile-cta">Shop now →</span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

const COLLECTIONS_QUERY = `#graphql
  query StoreCollections(
    $country: CountryCode
    $language: LanguageCode
    $first: Int
  ) @inContext(country: $country, language: $language) {
    collections(first: $first) {
      nodes {
        id
        title
        handle
        image {
          id
          url
          altText
          width
          height
        }
      }
    }
  }
` as const;
