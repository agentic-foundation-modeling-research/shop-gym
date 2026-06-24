import {useLoaderData, type LoaderFunctionArgs} from 'react-router';
import {CollectionGrid} from '~/components/storefront';
import {getAppContext} from '~/lib/context';
import {COLLECTIONS_QUERY} from '~/lib/queries';
import {storefrontQuery} from '~/lib/storefront';
import type {CollectionSummary} from '~/lib/types';

interface CollectionsData {
  readonly collections: {
    readonly nodes: readonly CollectionSummary[];
  };
}

export function meta() {
  return [{title: 'Collections'}];
}

export async function loader({
  context,
}: LoaderFunctionArgs): Promise<CollectionsData> {
  return storefrontQuery<CollectionsData>(
    getAppContext(context),
    COLLECTIONS_QUERY,
  );
}

export default function Collections() {
  const data = useLoaderData<typeof loader>();
  return (
    <div className="page-width stack">
      <h1>Collections</h1>
      <CollectionGrid collections={data.collections.nodes} />
    </div>
  );
}
