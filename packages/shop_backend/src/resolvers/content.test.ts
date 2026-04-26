import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createYoga } from 'graphql-yoga';
import { afterAll, describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import { type SandboxSchemaResolvers, createSandboxSchema } from '../schema.js';
import { CartStore } from './cart.js';
import { contentResolvers } from './content.js';
import type { ResolverContext } from './index.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);

const BASE_URL = 'https://shop.example';

const data = loadShopData(FIXTURE_DIR);
const carts = new CartStore();

const resolvers: SandboxSchemaResolvers = {
  Query: contentResolvers.Query,
  Blog: contentResolvers.Blog,
};

const yoga = createYoga({
  schema: createSandboxSchema(resolvers),
  context: (): ResolverContext => ({ data, carts, baseUrl: BASE_URL }),
});

interface ExecutionResult {
  readonly data?: unknown;
  readonly errors?: readonly unknown[];
}

async function runOn(
  yogaInstance: ReturnType<typeof createYoga>,
  source: string,
): Promise<ExecutionResult> {
  const response = await yogaInstance.fetch(`${BASE_URL}/graphql`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ query: source }),
  });
  return (await response.json()) as ExecutionResult;
}

const run = (source: string): Promise<ExecutionResult> => runOn(yoga, source);

describe('contentResolvers — Query.page', () => {
  it('returns the page node for a known handle', async () => {
    const result = await run(/* GraphQL */ `
      {
        page(handle: "about-us") {
          id
          handle
          title
          body
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      page: {
        id: 'gid://shopify/Page/15e2c5a5',
        handle: 'about-us',
        title: 'Our Story',
        body: '<p>At Mock Pet Foods we believe in the long-term health of your pet. We focus on quality, locally-sourced products for cats, dogs, birds, small animals and fish.</p><p>Owner-operated and proud to support our community.</p>',
      },
    });
  });

  it('returns null when the handle is not in the dataset', async () => {
    const result = await run(/* GraphQL */ `
      {
        page(handle: "does-not-exist") {
          handle
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({ page: null });
  });
});

describe('contentResolvers — Query.blog(s)', () => {
  it('returns the blog node for a known handle with its articles', async () => {
    const result = await run(/* GraphQL */ `
      {
        blog(handle: "news") {
          handle
          title
          articles {
            totalCount
            nodes {
              handle
              title
              contentHtml
              publishedAt
              author {
                name
              }
              blog {
                handle
              }
            }
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      blog: {
        handle: 'news',
        title: 'Mock Pet Foods News',
        articles: {
          totalCount: 1,
          nodes: [
            {
              handle: 'welcome-post',
              title: 'Welcome to Mock Pet Foods',
              contentHtml:
                '<p>We are excited to share product news, store updates, and pet care tips here on our blog. Stay tuned for posts on nutrition, training, and seasonal care.</p>',
              publishedAt: '2024-03-01T12:00:00-05:00',
              author: { name: 'Sarah' },
              blog: { handle: 'news' },
            },
          ],
        },
      },
    });
  });

  it('returns null for an unknown blog handle', async () => {
    const result = await run(/* GraphQL */ `
      {
        blog(handle: "does-not-exist") {
          handle
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({ blog: null });
  });

  it('exposes the full blog list via Query.blogs', async () => {
    const result = await run(/* GraphQL */ `
      {
        blogs {
          nodes {
            handle
            title
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      blogs: {
        nodes: [{ handle: 'news', title: 'Mock Pet Foods News' }],
      },
    });
  });

  it('Blog.articleByHandle returns a known article and null for misses', async () => {
    const hit = await run(/* GraphQL */ `
      {
        blog(handle: "news") {
          articleByHandle(handle: "welcome-post") {
            handle
            title
          }
        }
      }
    `);
    expect(hit.errors).toBeUndefined();
    expect(hit.data).toEqual({
      blog: { articleByHandle: { handle: 'welcome-post', title: 'Welcome to Mock Pet Foods' } },
    });

    const miss = await run(/* GraphQL */ `
      {
        blog(handle: "news") {
          articleByHandle(handle: "missing") {
            handle
          }
        }
      }
    `);
    expect(miss.errors).toBeUndefined();
    expect(miss.data).toEqual({ blog: { articleByHandle: null } });
  });
});

describe('contentResolvers — missing blogs.json', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sandbox-shop-no-blogs-'));
  fs.cpSync(FIXTURE_DIR, tmpDir, { recursive: true });
  fs.rmSync(path.join(tmpDir, 'blogs.json'));

  const noBlogsData = loadShopData(tmpDir);
  const noBlogsYoga = createYoga({
    schema: createSandboxSchema(resolvers),
    context: (): ResolverContext => ({ data: noBlogsData, carts, baseUrl: BASE_URL }),
  });

  afterAll(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it('Query.blog returns null for any handle', async () => {
    const result = await runOn(
      noBlogsYoga,
      /* GraphQL */ `
        {
          blog(handle: "news") {
            handle
          }
        }
      `,
    );
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({ blog: null });
  });

  it('Query.blogs returns an empty connection', async () => {
    const result = await runOn(
      noBlogsYoga,
      /* GraphQL */ `
        {
          blogs {
            nodes {
              handle
            }
            pageInfo {
              hasNextPage
              hasPreviousPage
            }
          }
        }
      `,
    );
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      blogs: {
        nodes: [],
        pageInfo: { hasNextPage: false, hasPreviousPage: false },
      },
    });
  });
});
