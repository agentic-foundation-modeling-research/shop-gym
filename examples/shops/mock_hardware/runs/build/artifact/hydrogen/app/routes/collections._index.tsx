import {useLoaderData, Link} from 'react-router';
import type {Route} from './+types/collections._index';
import {Image} from '@shopify/hydrogen';
import type {CollectionFragment} from 'storefrontapi.generated';

const STORE_LABEL = 'MOCK HARDWARE';

export const meta: Route.MetaFunction = () => {
  return [{title: 'Mock Hardware | All Collections'}];
};

export async function loader({context}: Route.LoaderArgs) {
  const [{collections}] = await Promise.all([
    context.storefront.query(COLLECTIONS_QUERY, {variables: {first: 100}}),
  ]);
  return {collections};
}

export default function Collections() {
  const {collections} = useLoaderData<typeof loader>();
  const nodes = collections.nodes as CollectionFragment[];

  return (
    <div className="collections-page">
      <header className="collection-page-header">
        <p className="collection-page-eyebrow">{STORE_LABEL}</p>
        <h1 className="collection-page-title">All collections</h1>
        <p className="collection-page-description">
          Browse every category of point-of-sale hardware we sell — from card
          readers and slip printers to till trays and service plans.
        </p>
      </header>
      <div className="collections-grid">
        {nodes.map((collection, index) => (
          <CollectionTile
            key={collection.id}
            collection={collection}
            index={index}
          />
        ))}
      </div>
    </div>
  );
}

function CollectionTile({
  collection,
  index,
}: {
  collection: CollectionFragment;
  index: number;
}) {
  return (
    <Link
      className="collection-tile"
      to={`/collections/${collection.handle}`}
      prefetch="intent"
    >
      <div className="collection-tile-media">
        {collection?.image ? (
          <Image
            alt={collection.image.altText || collection.title}
            aspectRatio="1/1"
            data={collection.image}
            loading={index < 6 ? 'eager' : undefined}
            sizes="(min-width: 60em) 380px, 50vw"
          />
        ) : (
          <CollectionTilePlaceholder label={collection.title} />
        )}
      </div>
      <h3 className="collection-tile-title">{collection.title}</h3>
    </Link>
  );
}

function CollectionTilePlaceholder({label}: {label: string}) {
  const initials = label
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w.charAt(0).toUpperCase())
    .join('');
  return (
    <div className="collection-tile-placeholder" aria-hidden="true">
      <span>{initials}</span>
    </div>
  );
}

const COLLECTIONS_QUERY = `#graphql
  fragment Collection on Collection {
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
  query StoreCollections(
    $country: CountryCode
    $language: LanguageCode
    $first: Int
  ) @inContext(country: $country, language: $language) {
    collections(first: $first) {
      nodes {
        ...Collection
      }
    }
  }
` as const;
