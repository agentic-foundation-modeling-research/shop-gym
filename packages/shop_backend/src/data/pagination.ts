/**
 * Relay-style pagination helper used by every connection-returning resolver.
 *
 * Behavior mirrors the Storefront API spec
 * (`docs/specs/shop_backend/storefront_api.md` §5.3): cursors are
 * `base64("cursor:<index>")`, `first`/`after` and `last`/`before` are honored,
 * and the returned shape carries `nodes`, `edges`, and a `pageInfo` with both
 * `startCursor`/`endCursor` and the `hasNextPage`/`hasPreviousPage` flags
 * computed against the original input range.
 */

import { Buffer } from 'node:buffer';

const CURSOR_PATTERN = /^cursor:(\d+)$/;

/** Connection-style pagination arguments. */
export interface PaginationArgs {
  readonly first?: number | null;
  readonly last?: number | null;
  readonly after?: string | null;
  readonly before?: string | null;
}

/** Relay-style page info on a connection. */
export interface PageInfo {
  readonly hasNextPage: boolean;
  readonly hasPreviousPage: boolean;
  readonly startCursor: string | null;
  readonly endCursor: string | null;
}

/** A single edge in a Relay-style connection. */
export interface ConnectionEdge<T> {
  readonly node: T;
  readonly cursor: string;
}

/** Output shape of `paginate`: nodes, edges, and pageInfo. */
export interface Connection<T> {
  readonly nodes: readonly T[];
  readonly edges: readonly ConnectionEdge<T>[];
  readonly pageInfo: PageInfo;
}

/** Thrown when an opaque cursor cannot be decoded back to an index. */
export class InvalidCursorError extends Error {
  readonly cursor: string;

  constructor(cursor: string) {
    super(`Invalid pagination cursor: '${cursor}'`);
    this.name = 'InvalidCursorError';
    this.cursor = cursor;
  }
}

/** Encode a 0-indexed position into the opaque cursor string. */
export function encodeCursor(index: number): string {
  return Buffer.from(`cursor:${index}`).toString('base64');
}

/**
 * Decode an opaque cursor back to its 0-indexed position.
 *
 * @throws {InvalidCursorError} The cursor is not the expected format.
 */
export function decodeCursor(cursor: string): number {
  const decoded = Buffer.from(cursor, 'base64').toString('utf-8');
  const match = CURSOR_PATTERN.exec(decoded);
  if (match === null || match[1] === undefined) {
    throw new InvalidCursorError(cursor);
  }
  return Number.parseInt(match[1], 10);
}

/**
 * Slice `items` into a Relay-style connection per the supplied arguments.
 *
 * `after`/`before` define an inclusive sub-range over the original list; then
 * `first` (front) or `last` (back) trims the sub-range. `hasNextPage` /
 * `hasPreviousPage` reflect whether the returned slice has neighbors in the
 * full list, regardless of the cursor bounds.
 *
 * @throws {InvalidCursorError} `after` or `before` is not a valid cursor.
 */
export function paginate<T>(items: readonly T[], args: PaginationArgs): Connection<T> {
  const { first, last, after, before } = args;

  let startIdx = 0;
  let endIdx = items.length;

  if (after !== undefined && after !== null) {
    startIdx = decodeCursor(after) + 1;
  }
  if (before !== undefined && before !== null) {
    endIdx = decodeCursor(before);
  }

  startIdx = clamp(startIdx, 0, items.length);
  endIdx = clamp(endIdx, startIdx, items.length);

  let sliceStart = startIdx;
  let sliceEnd = endIdx;

  if (first !== undefined && first !== null) {
    if (first < 0) {
      throw new RangeError(`'first' must be non-negative, got ${first}`);
    }
    sliceEnd = Math.min(sliceStart + first, sliceEnd);
  } else if (last !== undefined && last !== null) {
    if (last < 0) {
      throw new RangeError(`'last' must be non-negative, got ${last}`);
    }
    sliceStart = Math.max(sliceEnd - last, sliceStart);
  }

  const slice = items.slice(sliceStart, sliceEnd);
  const edges: ConnectionEdge<T>[] = slice.map((node, i) => ({
    node,
    cursor: encodeCursor(sliceStart + i),
  }));

  const firstEdge = edges[0];
  const lastEdge = edges[edges.length - 1];

  return {
    nodes: slice,
    edges,
    pageInfo: {
      hasPreviousPage: sliceStart > 0,
      hasNextPage: sliceEnd < items.length,
      startCursor: firstEdge?.cursor ?? null,
      endCursor: lastEdge?.cursor ?? null,
    },
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
