/**
 * Small deterministic PRNG so generators are reproducible from a seed string.
 *
 * The seed is hashed with FNV-1a and fed to mulberry32. Quality is irrelevant
 * here; stability across runs and platforms is what matters.
 */

/** Deterministic random source. */
export interface Rng {
  /** Uniform float in [0, 1). */
  next(): number;
  /** Fisher-Yates shuffle into a new array. */
  shuffle<T>(items: readonly T[]): T[];
}

function fnv1a(text: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** Create an `Rng` from any string. Equal strings give equal sequences. */
export function createRng(seed: string): Rng {
  let state = fnv1a(seed);
  const next = (): number => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  return {
    next,
    shuffle<T>(items: readonly T[]): T[] {
      const out = [...items];
      for (let i = out.length - 1; i > 0; i -= 1) {
        const j = Math.floor(next() * (i + 1));
        const a = out[i] as T;
        out[i] = out[j] as T;
        out[j] = a;
      }
      return out;
    },
  };
}
