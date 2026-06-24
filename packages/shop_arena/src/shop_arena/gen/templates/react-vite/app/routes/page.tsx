import {useLoaderData, type LoaderFunctionArgs} from 'react-router';
import {getAppContext} from '~/lib/context';
import {PAGE_QUERY} from '~/lib/queries';
import {storefrontQuery} from '~/lib/storefront';
import type {Page} from '~/lib/types';

interface PageData {
  readonly page: Page | null;
}

interface PageLoaderData {
  readonly page: Page;
}

export function meta({data}: {readonly data: PageLoaderData | undefined}) {
  return [{title: data?.page?.title ?? 'Page'}];
}

export async function loader({
  context,
  params,
}: LoaderFunctionArgs): Promise<PageLoaderData> {
  if (!params.handle) {
    throw new Response('Missing page handle.', {status: 400});
  }
  const data = await storefrontQuery<PageData>(
    getAppContext(context),
    PAGE_QUERY,
    {handle: params.handle},
  );
  const page = data.page;
  if (!page) {
    throw new Response('Page not found.', {status: 404});
  }
  return {page};
}

export default function PageRoute() {
  const {page} = useLoaderData<typeof loader>();
  return (
    <article className="page-width stack">
      <h1>{page.title}</h1>
      <div className="page-body" dangerouslySetInnerHTML={{__html: page.body}} />
    </article>
  );
}
