import {
  Form,
  Link,
  useLoaderData,
  type LoaderFunctionArgs,
} from 'react-router';
import {ProductCard} from '~/components/storefront';
import {getAppContext} from '~/lib/context';
import {SEARCH_QUERY} from '~/lib/queries';
import {storefrontQuery} from '~/lib/storefront';
import type {Page, ProductSummary} from '~/lib/types';

interface ArticleResult {
  readonly __typename: 'Article';
  readonly id: string;
  readonly handle: string;
  readonly title: string;
  readonly contentHtml: string;
  readonly blog: {
    readonly handle: string;
  };
}

interface ProductResult extends ProductSummary {
  readonly __typename: 'Product';
}

interface PageResult extends Page {
  readonly __typename: 'Page';
}

type SearchNode = ProductResult | PageResult | ArticleResult;

interface SearchData {
  readonly search: {
    readonly totalCount: number;
    readonly nodes: readonly SearchNode[];
  };
}

interface SearchLoaderData extends SearchData {
  readonly query: string;
}

export function meta() {
  return [{title: 'Search'}];
}

export async function loader({
  context,
  request,
}: LoaderFunctionArgs): Promise<SearchLoaderData> {
  const url = new URL(request.url);
  const query = url.searchParams.get('q') ?? '';
  const data = await storefrontQuery<SearchData>(
    getAppContext(context),
    SEARCH_QUERY,
    {query},
  );
  return {...data, query};
}

export default function Search() {
  const data = useLoaderData<typeof loader>();
  return (
    <div className="page-width stack">
      <h1>Search</h1>
      <Form method="get" className="search-form" role="search">
        <label>
          Search query
          <input type="search" name="q" defaultValue={data.query} />
        </label>
        <button type="submit">Search</button>
      </Form>
      <p className="muted">{data.search.totalCount} result(s)</p>
      <ul className="search-results">
        {data.search.nodes.map((node) => (
          <li key={node.id}>{renderSearchResult(node)}</li>
        ))}
      </ul>
    </div>
  );
}

function renderSearchResult(node: SearchNode) {
  switch (node.__typename) {
    case 'Product':
      return <ProductCard product={node} />;
    case 'Page':
      return (
        <article>
          <h3>
            <Link to={`/pages/${node.handle}`}>{node.title}</Link>
          </h3>
        </article>
      );
    case 'Article':
      return (
        <article>
          <h3>{node.title}</h3>
          <p className="muted">Article from {node.blog.handle}</p>
        </article>
      );
  }
}
