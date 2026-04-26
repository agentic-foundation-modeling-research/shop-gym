import { describe, expect, it } from 'vitest';

import {
  type Connection,
  InvalidCursorError,
  decodeCursor,
  encodeCursor,
  paginate,
} from './pagination.js';

const ALPHABET: readonly string[] = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];

function cursorAt(index: number): string {
  return encodeCursor(index);
}

function nodes<T>(connection: Connection<T>): readonly T[] {
  return connection.nodes;
}

describe('encodeCursor / decodeCursor', () => {
  it('round-trips a non-negative index', () => {
    for (const idx of [0, 1, 7, 42, 1234]) {
      expect(decodeCursor(encodeCursor(idx))).toBe(idx);
    }
  });

  it('throws InvalidCursorError on a non-base64 string', () => {
    expect(() => decodeCursor('!!!not-base64!!!')).toThrow(InvalidCursorError);
  });

  it('throws InvalidCursorError on a base64 string with the wrong shape', () => {
    const garbage = Buffer.from('hello:world').toString('base64');
    expect(() => decodeCursor(garbage)).toThrow(InvalidCursorError);
  });
});

describe('paginate', () => {
  it('returns the full list when no args are provided', () => {
    const result = paginate(ALPHABET, {});

    expect(nodes(result)).toEqual(ALPHABET);
    expect(result.edges).toHaveLength(ALPHABET.length);
    expect(result.edges[0]?.cursor).toBe(cursorAt(0));
    expect(result.edges[ALPHABET.length - 1]?.cursor).toBe(cursorAt(ALPHABET.length - 1));
    expect(result.pageInfo).toEqual({
      hasNextPage: false,
      hasPreviousPage: false,
      startCursor: cursorAt(0),
      endCursor: cursorAt(ALPHABET.length - 1),
    });
  });

  it('returns an empty connection for empty input', () => {
    const result = paginate([], { first: 5 });

    expect(result.nodes).toEqual([]);
    expect(result.edges).toEqual([]);
    expect(result.pageInfo).toEqual({
      hasNextPage: false,
      hasPreviousPage: false,
      startCursor: null,
      endCursor: null,
    });
  });

  it('honors first to take from the front', () => {
    const result = paginate(ALPHABET, { first: 3 });

    expect(nodes(result)).toEqual(['a', 'b', 'c']);
    expect(result.pageInfo.hasPreviousPage).toBe(false);
    expect(result.pageInfo.hasNextPage).toBe(true);
    expect(result.pageInfo.startCursor).toBe(cursorAt(0));
    expect(result.pageInfo.endCursor).toBe(cursorAt(2));
  });

  it('honors first + after to advance past a cursor', () => {
    const result = paginate(ALPHABET, { first: 2, after: cursorAt(2) });

    expect(nodes(result)).toEqual(['d', 'e']);
    expect(result.pageInfo.hasPreviousPage).toBe(true);
    expect(result.pageInfo.hasNextPage).toBe(true);
    expect(result.pageInfo.startCursor).toBe(cursorAt(3));
    expect(result.pageInfo.endCursor).toBe(cursorAt(4));
  });

  it('honors last to take from the back', () => {
    const result = paginate(ALPHABET, { last: 3 });

    expect(nodes(result)).toEqual(['f', 'g', 'h']);
    expect(result.pageInfo.hasPreviousPage).toBe(true);
    expect(result.pageInfo.hasNextPage).toBe(false);
    expect(result.pageInfo.startCursor).toBe(cursorAt(5));
    expect(result.pageInfo.endCursor).toBe(cursorAt(7));
  });

  it('honors last + before to back up before a cursor', () => {
    const result = paginate(ALPHABET, { last: 2, before: cursorAt(5) });

    expect(nodes(result)).toEqual(['d', 'e']);
    expect(result.pageInfo.hasPreviousPage).toBe(true);
    expect(result.pageInfo.hasNextPage).toBe(true);
    expect(result.pageInfo.startCursor).toBe(cursorAt(3));
    expect(result.pageInfo.endCursor).toBe(cursorAt(4));
  });

  it('combines after and before to bound a sub-range', () => {
    const result = paginate(ALPHABET, { after: cursorAt(1), before: cursorAt(6) });

    expect(nodes(result)).toEqual(['c', 'd', 'e', 'f']);
    expect(result.pageInfo.hasPreviousPage).toBe(true);
    expect(result.pageInfo.hasNextPage).toBe(true);
    expect(result.pageInfo.startCursor).toBe(cursorAt(2));
    expect(result.pageInfo.endCursor).toBe(cursorAt(5));
  });

  it('clamps first beyond the available range', () => {
    const result = paginate(ALPHABET, { first: 100 });

    expect(nodes(result)).toEqual(ALPHABET);
    expect(result.pageInfo.hasNextPage).toBe(false);
    expect(result.pageInfo.hasPreviousPage).toBe(false);
  });

  it('returns an empty page when after points past the last item', () => {
    const result = paginate(ALPHABET, { first: 3, after: cursorAt(ALPHABET.length - 1) });

    expect(result.nodes).toEqual([]);
    expect(result.edges).toEqual([]);
    expect(result.pageInfo.hasNextPage).toBe(false);
    expect(result.pageInfo.hasPreviousPage).toBe(true);
    expect(result.pageInfo.startCursor).toBeNull();
    expect(result.pageInfo.endCursor).toBeNull();
  });

  it('preserves cursor stability across pages (round-trip)', () => {
    const firstPage = paginate(ALPHABET, { first: 3 });
    const endCursor = firstPage.pageInfo.endCursor;
    expect(endCursor).not.toBeNull();

    const secondPage = paginate(ALPHABET, { first: 3, after: endCursor ?? '' });
    expect(nodes(secondPage)).toEqual(['d', 'e', 'f']);
    expect(secondPage.pageInfo.startCursor).toBe(cursorAt(3));
    expect(secondPage.pageInfo.endCursor).toBe(cursorAt(5));
  });

  it('throws InvalidCursorError on a malformed after cursor', () => {
    expect(() => paginate(ALPHABET, { first: 1, after: 'not-a-cursor!' })).toThrow(
      InvalidCursorError,
    );
  });

  it('throws RangeError on a negative first', () => {
    expect(() => paginate(ALPHABET, { first: -1 })).toThrow(RangeError);
  });
});
