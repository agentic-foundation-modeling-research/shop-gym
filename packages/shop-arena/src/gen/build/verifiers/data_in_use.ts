/**
 * `data_in_use` verifier: every GraphQL document the storefront ships must
 * validate against the backend schema the sidecar is serving.
 *
 * Documents are `#graphql`, `graphql\`...\`` or `gql\`...\`` template
 * literals under `artifact/storefront/app/`. Fragment interpolations such as
 * `${PRODUCT_FRAGMENT}` are dropped and the fragments are re-attached by
 * name from the fragment definitions found across all scanned files, so a
 * document validates the same way the storefront client sends it. The
 * schema comes from introspecting the running sidecar.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { Verifier, VerifierContext, VerifierResult } from '@shop-gym/harness';
import {
  type DefinitionNode,
  type DocumentNode,
  type FragmentDefinitionNode,
  type GraphQLSchema,
  Kind,
  buildClientSchema,
  getIntrospectionQuery,
  parse,
  validate,
  visit,
} from 'graphql';

export const DATA_IN_USE_NAME = 'data_in_use';
export const STOREFRONT_APP_DIR = path.join('storefront', 'app');
const SCAN_EXTENSIONS = new Set(['.ts', '.tsx']);
// A tag must be a standalone identifier so that `.../graphql` inside a URL literal does not match.
const BLOCK_RE = /(?<![\w/.$-])(?:graphql|gql)`([^`]*)`|`(\s*#graphql\b[^`]*)`/g;
const INTERPOLATION_RE = /\$\{[^}]*\}/g;
const HASH_MARKER_RE = /^\s*#graphql[^\n]*(?:\n|$)/;

export type SchemaIntrospector = () => Promise<GraphQLSchema>;

export interface OperationProblem {
  /** Path relative to `artifact/`, POSIX separators. */
  readonly path: string;
  /** `query Home`, `mutation <anonymous>`, or `document` for syntax errors. */
  readonly operation: string;
  readonly message: string;
}

interface ExtractedBlock {
  readonly path: string;
  readonly source: string;
}

/** Introspect the GraphQL endpoint at `${baseUrl}/graphql`. */
export function introspectSidecar(baseUrl: string): SchemaIntrospector {
  return async () => {
    const response = await fetch(`${baseUrl}/graphql`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query: getIntrospectionQuery() }),
    });
    if (!response.ok) {
      throw new Error(`introspection failed: HTTP ${response.status}`);
    }
    const payload = (await response.json()) as {
      data?: Parameters<typeof buildClientSchema>[0];
      errors?: readonly { message: string }[];
    };
    if (payload.data === undefined) {
      const reason = payload.errors?.map((e) => e.message).join('; ') ?? 'no data';
      throw new Error(`introspection failed: ${reason}`);
    }
    return buildClientSchema(payload.data);
  };
}

/** All GraphQL template literals under `appDir`, with interpolations removed. */
export async function extractGraphqlBlocks(
  appDir: string,
  pathPrefix: string,
): Promise<ExtractedBlock[]> {
  const blocks: ExtractedBlock[] = [];
  async function walk(dir: string, rel: string): Promise<void> {
    let entries: import('node:fs').Dirent[];
    try {
      entries = await fs.readdir(dir, { withFileTypes: true });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
        return;
      }
      throw error;
    }
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
      const entryRel = rel === '' ? entry.name : `${rel}/${entry.name}`;
      if (entry.isDirectory()) {
        if (entry.name !== 'node_modules') {
          await walk(path.join(dir, entry.name), entryRel);
        }
        continue;
      }
      if (!entry.isFile() || !SCAN_EXTENSIONS.has(path.extname(entry.name))) {
        continue;
      }
      const text = await fs.readFile(path.join(dir, entry.name), 'utf-8');
      for (const match of text.matchAll(BLOCK_RE)) {
        const body = match[1] ?? match[2] ?? '';
        const source = body.replace(HASH_MARKER_RE, '').replace(INTERPOLATION_RE, '');
        if (source.trim() !== '') {
          blocks.push({ path: `${pathPrefix}/${entryRel}`, source });
        }
      }
    }
  }
  await walk(appDir, '');
  return blocks;
}

/**
 * Validate every operation in `blocks` against `schema`.
 *
 * Fragment definitions are pooled across blocks; each operation document is
 * completed with the fragments it (transitively) spreads before validation.
 */
export function validateBlocks(schema: GraphQLSchema, blocks: readonly ExtractedBlock[]) {
  const problems: OperationProblem[] = [];
  const fragments = new Map<string, FragmentDefinitionNode>();
  const parsed: { path: string; doc: DocumentNode }[] = [];
  for (const block of blocks) {
    try {
      const doc = parse(block.source);
      parsed.push({ path: block.path, doc });
      for (const def of doc.definitions) {
        if (def.kind === Kind.FRAGMENT_DEFINITION) {
          fragments.set(def.name.value, def);
        }
      }
    } catch (error) {
      problems.push({
        path: block.path,
        operation: 'document',
        message: error instanceof Error ? error.message : String(error),
      });
    }
  }
  let operations = 0;
  for (const { path: blockPath, doc } of parsed) {
    for (const def of doc.definitions) {
      if (def.kind !== Kind.OPERATION_DEFINITION) {
        continue;
      }
      operations += 1;
      const label = `${def.operation} ${def.name?.value ?? '<anonymous>'}`;
      const complete: DocumentNode = {
        kind: Kind.DOCUMENT,
        definitions: [def, ...collectFragments(def, fragments)],
      };
      for (const error of validate(schema, complete)) {
        problems.push({ path: blockPath, operation: label, message: error.message });
      }
    }
  }
  return { operations, problems };
}

function collectFragments(
  root: DefinitionNode,
  pool: ReadonlyMap<string, FragmentDefinitionNode>,
): FragmentDefinitionNode[] {
  const seen = new Map<string, FragmentDefinitionNode>();
  const pending: DefinitionNode[] = [root];
  while (pending.length > 0) {
    const node = pending.pop() as DefinitionNode;
    visit(node, {
      FragmentSpread(spread) {
        const name = spread.name.value;
        const fragment = pool.get(name);
        if (fragment !== undefined && !seen.has(name)) {
          seen.set(name, fragment);
          pending.push(fragment);
        }
      },
    });
  }
  return [...seen.values()];
}

export interface DataInUseOptions {
  readonly introspect: SchemaIntrospector;
  /** Awaited before introspection, e.g. `sidecar.restartIfChanged`. */
  readonly beforeIntrospect?: () => Promise<unknown>;
}

export function dataInUseVerifier(options: DataInUseOptions): Verifier {
  return {
    name: DATA_IN_USE_NAME,
    appliesTo: (_taskId: string) => true,
    async run(ctx: VerifierContext): Promise<VerifierResult> {
      const appDir = path.join(ctx.artifactDir, STOREFRONT_APP_DIR);
      const blocks = await extractGraphqlBlocks(appDir, 'storefront/app');
      if (blocks.length === 0) {
        return { verdict: 'pass', details: { operations: 0, problems: [] } };
      }
      await options.beforeIntrospect?.();
      const schema = await options.introspect();
      const { operations, problems } = validateBlocks(schema, blocks);
      const details = { operations, problems };
      if (problems.length === 0) {
        return { verdict: 'pass', details };
      }
      return { verdict: 'fail', feedback: renderProblems(operations, problems), details };
    },
  };
}

function renderProblems(operations: number, problems: readonly OperationProblem[]): string {
  return [
    `\`data_in_use\`: ${problems.length} problem(s) across ${operations} storefront GraphQL operation(s) against the live backend schema.`,
    '',
    'Use only fields and arguments the schema exposes (introspect the sidecar to check).',
    '',
    ...problems.map((p) => `- \`${p.path}\`: ${p.operation}: ${p.message}`),
  ].join('\n');
}
