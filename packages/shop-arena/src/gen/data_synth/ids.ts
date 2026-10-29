/** Deterministic numeric ids and random numbers shared by assembly. */

import { createHash } from 'node:crypto';

/** First 48 bits of sha256(`<scope>\0<key>`) as a safe integer. */
export function stableId(scope: string, key: string): number {
  return Number.parseInt(
    createHash('sha256').update(`${scope}\0${key}`).digest('hex').slice(0, 12),
    16,
  );
}

/** Deterministic 32-bit generator (mulberry32) seeded from a string. */
export function seededRandom(seed: string): () => number {
  let state = Number.parseInt(createHash('sha256').update(seed).digest('hex').slice(0, 8), 16);
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
