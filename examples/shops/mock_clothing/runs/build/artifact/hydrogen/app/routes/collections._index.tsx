import {Link, useLoaderData} from 'react-router';
import type {Route} from './+types/collections._index';
import {Image} from '@shopify/hydrogen';

export const meta: Route.MetaFunction = () => {
  return [{title: 'Mock Apparel | All Collections'}];
};

type CollectionTileNode = {
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

type CollectionsResponse = {
  collections: {nodes: CollectionTileNode[]};
};

export async function loader({context}: Route.LoaderArgs) {
  const data = (await context.storefront.query(
    COLLECTIONS_QUERY,
  )) as CollectionsResponse;
  return {collections: data.collections};
}

export default function CollectionsIndex() {
  const {collections} = useLoaderData<typeof loader>();
  const nodes = collections?.nodes ?? [];

  return (
    <div className="collections-index">
      <header className="collection-header collection-header-index">
        <nav className="collection-breadcrumb" aria-label="Breadcrumb">
          <ol>
            <li>
              <Link to="/" prefetch="intent">
                Home
              </Link>
            </li>
            <li>
              <span className="collection-breadcrumb-sep">›</span>
              <span className="collection-breadcrumb-current">Collections</span>
            </li>
          </ol>
        </nav>
        <h1 className="collection-title">Shop all collections</h1>
        <p className="collection-description">
          Explore every edit — from activewear-adjacent essentials to fine
          jewellery and personalised gifts. Curated for the way you live.
        </p>
        <p className="collection-count">
          {nodes.length} {nodes.length === 1 ? 'collection' : 'collections'}
        </p>
      </header>

      <div className="collections-index-grid">
        {nodes.map((collection, index) => (
          <CollectionTile
            key={collection.id}
            handle={collection.handle}
            title={collection.title}
            image={collection.image}
            index={index}
          />
        ))}
      </div>
    </div>
  );
}

type CollectionTileImage = {
  id?: string | null;
  url: string;
  altText?: string | null;
  width?: number | null;
  height?: number | null;
} | null;

function CollectionTile({
  handle,
  title,
  image,
  index,
}: {
  handle: string;
  title: string;
  image?: CollectionTileImage;
  index: number;
}) {
  const accent = TILE_ACCENTS[index % TILE_ACCENTS.length];
  return (
    <Link
      to={`/collections/${handle}`}
      prefetch="intent"
      className="collections-index-tile"
    >
      <div className="collections-index-tile-image">
        {image ? (
          <Image
            data={image}
            aspectRatio="1/1"
            sizes="(min-width: 1024px) 25vw, (min-width: 600px) 50vw, 100vw"
            loading={index < 4 ? 'eager' : 'lazy'}
          />
        ) : (
          <div
            className="collections-index-tile-placeholder"
            style={{background: accent}}
            aria-hidden="true"
          >
            <span>{title.charAt(0)}</span>
          </div>
        )}
        <div className="collections-index-tile-veil" aria-hidden="true" />
      </div>
      <div className="collections-index-tile-body">
        <h2>{title}</h2>
        <span className="collections-index-tile-cta">Shop now →</span>
      </div>
    </Link>
  );
}

const TILE_ACCENTS = [
  'linear-gradient(135deg, #efe6d6 0%, #c5a47e 100%)',
  'linear-gradient(135deg, #d8c4a8 0%, #a48560 100%)',
  'linear-gradient(135deg, #2a201c 0%, #6e553f 100%)',
  'linear-gradient(135deg, #c5a47e 0%, #6e553f 100%)',
  'linear-gradient(135deg, #e9d5c2 0%, #c5a87a 100%)',
  'linear-gradient(135deg, #cbb89a 0%, #8a7e75 100%)',
  'linear-gradient(135deg, #b89a78 0%, #2a201c 100%)',
  'linear-gradient(135deg, #d4b78b 0%, #9a8367 100%)',
];

const COLLECTIONS_QUERY = `#graphql
  query StoreCollections(
    $country: CountryCode
    $language: LanguageCode
  ) @inContext(country: $country, language: $language) {
    collections(first: 50) {
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
