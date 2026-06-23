/**
 * Round-trip tests for the `encodedVariant*` encoders.
 *
 * Correctness is anchored two ways:
 *   1. `v1Decoder` below is a faithful re-implementation of Shopify Hydrogen's
 *      `decodeEncodedVariant` (`@shopify/hydrogen-react`,
 *      `src/optionValueDecoder.ts`). `decodes_shopify_canonical_example` pins
 *      it to Shopify's documented example so we know the decoder is itself
 *      correct.
 *   2. Every encoder test decodes our output through that decoder and checks
 *      the combination set matches the input — proving the storefront's
 *      `getProductOptions` will read back exactly the variants we encoded.
 */

import { describe, expect, it } from 'vitest';
import { encodeVariantAvailability, encodeVariantExistence } from './encoded_variants.js';

// ── Faithful Hydrogen decoder (vendored for test anchoring) ────────────────

const V1_CONTROL_CHARS = {
  OPTION: ':',
  END_OF_PREFIX: ',',
  SEQUENCE_GAP: ' ',
  RANGE: '-',
} as const;

/** Verbatim port of Hydrogen's `decodeEncodedVariant` → `v1Decoder`. */
function decodeEncodedVariant(encodedVariantField: string): number[][] {
  if (!encodedVariantField) return [];
  if (!encodedVariantField.startsWith('v1_')) {
    throw new Error('Unsupported option value encoding');
  }
  return v1Decoder(encodedVariantField.replace(/^v1_/, ''));
}

function v1Decoder(encodedVariantField: string): number[][] {
  const tokenizer = /[ :,-]/g;
  let index = 0;
  let token: RegExpExecArray | null;
  const options: number[][] = [];
  const currentOptionValue: number[] = [];
  let depth = 0;
  let rangeStart: number | null = null;

  // biome-ignore lint/suspicious/noAssignInExpressions: verbatim port of Hydrogen's tokenizer loop.
  while ((token = tokenizer.exec(encodedVariantField))) {
    const operation = token[0];
    const optionValueIndex = Number.parseInt(encodedVariantField.slice(index, token.index)) || 0;

    if (rangeStart !== null) {
      for (; rangeStart < optionValueIndex; rangeStart++) {
        currentOptionValue[depth] = rangeStart;
        options.push([...currentOptionValue]);
      }
      rangeStart = null;
    }

    currentOptionValue[depth] = optionValueIndex;

    if (operation === V1_CONTROL_CHARS.RANGE) {
      rangeStart = optionValueIndex;
    } else if (operation === V1_CONTROL_CHARS.OPTION) {
      depth++;
    } else {
      if (
        operation === V1_CONTROL_CHARS.SEQUENCE_GAP ||
        (operation === V1_CONTROL_CHARS.END_OF_PREFIX &&
          encodedVariantField[token.index - 1] !== V1_CONTROL_CHARS.END_OF_PREFIX)
      ) {
        options.push([...currentOptionValue]);
      }
      if (operation === V1_CONTROL_CHARS.END_OF_PREFIX) {
        currentOptionValue.pop();
        depth--;
      }
    }
    index = tokenizer.lastIndex;
  }

  const encodingEndsWithIndex = encodedVariantField.match(/\d+$/g);
  if (encodingEndsWithIndex) {
    const finalValueIndex = Number.parseInt(encodingEndsWithIndex[0]);
    if (rangeStart != null) {
      for (; rangeStart <= finalValueIndex; rangeStart++) {
        currentOptionValue[depth] = rangeStart;
        options.push([...currentOptionValue]);
      }
    } else {
      options.push([finalValueIndex]);
    }
  }

  return options;
}

// ── Test fixtures + helpers ────────────────────────────────────────────────

interface OptionFixture {
  readonly name: string;
  readonly values: readonly string[];
}

interface VariantFixture {
  readonly availableForSale: boolean;
  readonly selectedOptions: readonly { readonly name: string; readonly value: string }[];
}

/** Build a variant from an option-value index tuple against the given options. */
function variantFromTuple(
  options: readonly OptionFixture[],
  tuple: readonly number[],
  availableForSale = true,
): VariantFixture {
  return {
    availableForSale,
    selectedOptions: tuple.map((valueIndex, optionIndex) => {
      const option = options[optionIndex];
      if (option === undefined) throw new Error('tuple longer than options');
      const value = option.values[valueIndex];
      if (value === undefined) throw new Error('value index out of range');
      return { name: option.name, value };
    }),
  };
}

/** Canonicalize a combination set: sort tuples lexicographically, stringify. */
function normalize(combinations: readonly number[][]): string {
  return [...combinations]
    .map((tuple) => tuple.join(':'))
    .sort()
    .join('|');
}

// ── Decoder anchor ──────────────────────────────────────────────────────────

describe('v1 decoder anchor', () => {
  it('decodes the Shopify canonical example', () => {
    const canonical = 'v1_0:0:0,1:0-1,,1:0:0-1,1:1,,2:0:1,1:0,,';
    expect(normalize(decodeEncodedVariant(canonical))).toBe(
      normalize([
        [0, 0, 0],
        [0, 1, 0],
        [0, 1, 1],
        [1, 0, 0],
        [1, 0, 1],
        [1, 1, 1],
        [2, 0, 1],
        [2, 1, 0],
      ]),
    );
  });

  it('returns empty for an empty field', () => {
    expect(decodeEncodedVariant('')).toEqual([]);
  });
});

// ── Round-trip: existence ───────────────────────────────────────────────────

describe('encodeVariantExistence', () => {
  it('returns empty string when the product has no options', () => {
    expect(encodeVariantExistence([], [])).toBe('');
  });

  it('round-trips a single-option product', () => {
    const options: OptionFixture[] = [{ name: 'Size', values: ['S', 'M', 'L'] }];
    const tuples = [[0], [1], [2]];
    const variants = tuples.map((t) => variantFromTuple(options, t));

    const encoded = encodeVariantExistence(options, variants);
    expect(encoded.startsWith('v1_')).toBe(true);
    expect(normalize(decodeEncodedVariant(encoded))).toBe(normalize(tuples));
  });

  it('round-trips a two-option product with a sparse matrix', () => {
    const options: OptionFixture[] = [
      { name: 'Color', values: ['Red', 'Blue'] },
      { name: 'Size', values: ['S', 'M', 'L'] },
    ];
    // Sparse: not every Color×Size pair has a variant.
    const tuples = [
      [0, 0],
      [0, 2],
      [1, 1],
    ];
    const variants = tuples.map((t) => variantFromTuple(options, t));

    const encoded = encodeVariantExistence(options, variants);
    expect(normalize(decodeEncodedVariant(encoded))).toBe(normalize(tuples));
  });

  it('round-trips a three-option product', () => {
    const options: OptionFixture[] = [
      { name: 'Color', values: ['Red', 'Green', 'Blue'] },
      { name: 'Size', values: ['S', 'M'] },
      { name: 'Material', values: ['Cotton', 'Wool'] },
    ];
    const tuples = [
      [0, 0, 0],
      [0, 1, 0],
      [1, 0, 1],
      [2, 1, 1],
    ];
    const variants = tuples.map((t) => variantFromTuple(options, t));

    const encoded = encodeVariantExistence(options, variants);
    expect(normalize(decodeEncodedVariant(encoded))).toBe(normalize(tuples));
  });

  it('de-duplicates variants that map to the same combination', () => {
    const options: OptionFixture[] = [{ name: 'Size', values: ['S', 'M'] }];
    const variants = [
      variantFromTuple(options, [0]),
      variantFromTuple(options, [0]),
      variantFromTuple(options, [1]),
    ];

    const encoded = encodeVariantExistence(options, variants);
    expect(normalize(decodeEncodedVariant(encoded))).toBe(normalize([[0], [1]]));
  });

  it('skips variants whose selected value is absent from the option list', () => {
    const options: OptionFixture[] = [{ name: 'Size', values: ['S', 'M'] }];
    const variants: VariantFixture[] = [
      variantFromTuple(options, [0]),
      { availableForSale: true, selectedOptions: [{ name: 'Size', value: 'XL' }] },
    ];

    const encoded = encodeVariantExistence(options, variants);
    expect(normalize(decodeEncodedVariant(encoded))).toBe(normalize([[0]]));
  });
});

// ── Round-trip: availability ────────────────────────────────────────────────

describe('encodeVariantAvailability', () => {
  it('encodes only the available subset', () => {
    const options: OptionFixture[] = [
      { name: 'Color', values: ['Red', 'Blue'] },
      { name: 'Size', values: ['S', 'M'] },
    ];
    const variants = [
      variantFromTuple(options, [0, 0], true),
      variantFromTuple(options, [0, 1], false),
      variantFromTuple(options, [1, 0], true),
      variantFromTuple(options, [1, 1], false),
    ];

    const existence = encodeVariantExistence(options, variants);
    const availability = encodeVariantAvailability(options, variants);

    expect(normalize(decodeEncodedVariant(existence))).toBe(
      normalize([
        [0, 0],
        [0, 1],
        [1, 0],
        [1, 1],
      ]),
    );
    expect(normalize(decodeEncodedVariant(availability))).toBe(
      normalize([
        [0, 0],
        [1, 0],
      ]),
    );
  });

  it('returns empty string when no variant is available', () => {
    const options: OptionFixture[] = [{ name: 'Size', values: ['S', 'M'] }];
    const variants = [variantFromTuple(options, [0], false), variantFromTuple(options, [1], false)];

    expect(encodeVariantAvailability(options, variants)).toBe('');
  });
});
