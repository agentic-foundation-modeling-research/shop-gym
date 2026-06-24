import {useLoaderData, type LoaderFunctionArgs} from 'react-router';
import {ProductGrid} from '~/components/storefront';
import {getAppContext} from '~/lib/context';
import {COLLECTION_QUERY} from '~/lib/queries';
import {storefrontQuery} from '~/lib/storefront';
import type {CollectionDetail} from '~/lib/types';

interface CollectionData {
  readonly collection: CollectionDetail | null;
}

interface CollectionLoaderData {
  readonly collection: CollectionDetail;
}

export function meta({
  data,
}: {
  readonly data: CollectionLoaderData | undefined;
}) {
  return [{title: data?.collection?.title ?? 'Collection'}];
}

export async function loader({
  context,
  params,
}: LoaderFunctionArgs): Promise<CollectionLoaderData> {
  if (!params.handle) {
    throw new Response('Missing collection handle.', {status: 400});
  }
  const data = await storefrontQuery<CollectionData>(
    getAppContext(context),
    COLLECTION_QUERY,
    {handle: params.handle},
  );
  const collection = data.collection;
  if (!collection) {
    throw new Response('Collection not found.', {status: 404});
  }
  return {collection};
}

export default function Collection() {
  const {collection} = useLoaderData<typeof loader>();
  return (
    <div className="page-width stack">
      <section className="stack">
        <h1>{collection.title}</h1>
        <p>{collection.description}</p>
      </section>
      <ProductGrid products={collection.products.nodes} />
    </div>
  );
}
