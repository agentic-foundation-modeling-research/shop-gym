import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import type { VerifierContext } from '@shop-gym/harness';
import { createSandboxServer, loadShopData } from '@shop-gym/shop-backend';
import type { GraphQLSchema } from 'graphql';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import { STOREFRONT_TEMPLATE_DIR } from '../../../templates.js';
import { defaultBackendTemplateDir } from '../seed.js';
import { freePort } from '../sidecar.js';
import {
  dataInUseVerifier,
  extractGraphqlBlocks,
  introspectSidecar,
  validateBlocks,
} from './data_in_use.js';

const FIXTURE_DIR = path.join(defaultBackendTemplateDir(), 'tests', 'fixtures', 'sandbox_shop_v0');

// The schema is obtained over HTTP exactly as in production: the backend's in-memory
// GraphQLSchema belongs to a second copy of `graphql` and fails graphql-js realm checks.
let schema: GraphQLSchema;
let server: ReturnType<typeof createSandboxServer>;
let artifactDir: string;
let appDir: string;

beforeAll(async () => {
  const port = await freePort();
  server = createSandboxServer({ data: loadShopData(FIXTURE_DIR), dataDir: FIXTURE_DIR, port });
  await server.listen();
  schema = await introspectSidecar(`http://127.0.0.1:${port}`)();
});

afterAll(() => server.close());

beforeEach(async () => {
  artifactDir = path.join(await fs.mkdtemp(path.join(os.tmpdir(), 'data-in-use-')), 'artifact');
  appDir = path.join(artifactDir, 'storefront', 'app', 'routes');
  await fs.mkdir(appDir, { recursive: true });
});

function ctx(selectedTaskId = 'gen_homepage'): VerifierContext {
  return {
    runDir: path.dirname(artifactDir),
    iterId: 'exec-0001',
    selectedTaskId,
    plan: [],
    artifactDir,
  };
}

const introspect = async () => schema;

describe('extractGraphqlBlocks', () => {
  it('finds #graphql, graphql-tagged and gql-tagged literals and drops interpolations', async () => {
    await fs.writeFile(
      path.join(appDir, 'a.tsx'),
      [
        'const A = `#graphql',
        '  query A { shop { name } }',
        '  ${SHOP_FRAGMENT}',
        '`;',
        'const B = graphql`query B { shop { name } }`;',
        'const C = gql`fragment F on Shop { name }`;',
        'const notGraphql = `select * from x`;',
        'const url = `${base}/graphql`;',
      ].join('\n'),
    );
    const blocks = await extractGraphqlBlocks(
      path.join(artifactDir, 'storefront', 'app'),
      'storefront/app',
    );
    expect(blocks.map((b) => b.path)).toEqual(Array(3).fill('storefront/app/routes/a.tsx'));
    expect(blocks[0]?.source).not.toContain('${');
  });
});

describe('validateBlocks', () => {
  it('validates every template query against the backend schema', async () => {
    const blocks = await extractGraphqlBlocks(
      path.join(STOREFRONT_TEMPLATE_DIR, 'app'),
      'storefront/app',
    );
    const { operations, problems } = validateBlocks(schema, blocks);
    expect(problems).toEqual([]);
    expect(operations).toBeGreaterThan(10);
  });

  it('reports unknown fields, unknown root fields, and syntax errors with paths', () => {
    const { problems } = validateBlocks(schema, [
      { path: 'storefront/app/routes/a.tsx', source: 'query Loyalty { loyaltyTier { name } }' },
      { path: 'storefront/app/routes/b.tsx', source: 'query Shop { shop { nope } }' },
      { path: 'storefront/app/routes/c.tsx', source: 'query { shop {' },
      {
        path: 'storefront/app/routes/d.tsx',
        source: 'query Ok { shop { ...S } }\nfragment S on Shop { name }',
      },
    ]);
    expect(problems).toEqual([
      expect.objectContaining({ path: 'storefront/app/routes/c.tsx', operation: 'document' }),
      expect.objectContaining({
        path: 'storefront/app/routes/a.tsx',
        operation: 'query Loyalty',
        message: expect.stringContaining('loyaltyTier'),
      }),
      expect.objectContaining({ path: 'storefront/app/routes/b.tsx', operation: 'query Shop' }),
    ]);
  });

  it('resolves fragments defined in other files', () => {
    const { problems } = validateBlocks(schema, [
      { path: 'storefront/app/lib/queries.ts', source: 'fragment ShopFields on Shop { name }' },
      { path: 'storefront/app/routes/home.tsx', source: 'query Home { shop { ...ShopFields } }' },
    ]);
    expect(problems).toEqual([]);
  });
});

describe('data_in_use verifier', () => {
  it('applies to every task', () => {
    const verifier = dataInUseVerifier({ introspect });
    expect(verifier.appliesTo('gen_backend')).toBe(true);
    expect(verifier.appliesTo('gen_homepage')).toBe(true);
    expect(verifier.appliesTo('visual_fix')).toBe(true);
  });

  it('passes without introspecting when the storefront has no GraphQL', async () => {
    let introspected = false;
    const verifier = dataInUseVerifier({
      introspect: async () => {
        introspected = true;
        return schema;
      },
    });
    expect((await verifier.run(ctx())).verdict).toBe('pass');
    expect(introspected).toBe(false);
  });

  it('awaits the hook, then fails with one line per problem', async () => {
    await fs.writeFile(
      path.join(appDir, 'home.tsx'),
      'const Q = `#graphql\n query Home { shop { nope } }`;',
    );
    let hooked = false;
    const verifier = dataInUseVerifier({
      introspect,
      beforeIntrospect: async () => {
        hooked = true;
      },
    });
    const result = await verifier.run(ctx());
    expect(hooked).toBe(true);
    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain(
      '- `storefront/app/routes/home.tsx`: query Home: Cannot query field "nope" on type "Shop".',
    );
  });
});
