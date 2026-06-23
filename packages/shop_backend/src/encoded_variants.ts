/**
 * Encoders for the Storefront API `Product.encodedVariantExistence` and
 * `Product.encodedVariantAvailability` fields.
 *
 * Shopify encodes the n-dimensional option-value matrix of a product as a
 * compact `v1_`-prefixed trie string. Hydrogen's `getProductOptions`
 * (`@shopify/hydrogen`) decodes it via `decodeEncodedVariant` and uses it to
 * mark which option-value combinations *exist* and are *available for sale*.
 * The non-null `String!` schema fields have no default value, so a product
 * query that omits these resolvers raises `INTERNAL_SERVER_ERROR` and every
 * `/products/<handle>` route 404s in the generated storefront.
 *
 * The encoding (V1) is a depth-first serialization of the option-value index
 * matrix. A combination `[i0, i1, …]` lists, for each product option in
 * declaration order, the zero-based index of its selected value within that
 * option's value list. The control characters are:
 *
 *   - `:` descend to the next option,
 *   - `,` end a combination (and pop one option level; consecutive commas pop
 *     multiple levels),
 *   - ` ` separate sibling values at the final option level,
 *   - `-` a contiguous value range at the final option level.
 *
 * This module emits a **fully expanded** form (no prefix sharing, no ranges):
 * every combination is spelled out and terminated with the commas needed to
 * pop back to the root. That form is intentionally simple — it decodes to the
 * exact same combination set as Shopify's compact form, which is all
 * `decodeEncodedVariant` / `isOptionValueCombinationInEncodedVariant` require.
 * The round-trip is locked down in `encoded_variants.test.ts` against a
 * faithful re-implementation of Shopify's decoder.
 *
 * Pure module: no I/O, no side effects at import.
 */

const V1_PREFIX = 'v1_';

/** Minimal option shape needed for index resolution (a `ProductOptionNode`). */
interface OptionLike {
  readonly name: string;
  readonly values: readonly string[];
}

/** Minimal variant shape needed for index resolution (a `ProductVariantNode`). */
interface VariantLike {
  readonly availableForSale: boolean;
  readonly selectedOptions: readonly { readonly name: string; readonly value: string }[];
}

/**
 * Encode the set of option-value combinations that have a backing variant.
 *
 * @param options Product options in declaration order.
 * @param variants Product variants.
 * @returns The `v1_`-prefixed existence string, or `''` when the product has
 *   no options (nothing to encode; Hydrogen treats an empty field as "no
 *   matrix").
 */
export function encodeVariantExistence(
  options: readonly OptionLike[],
  variants: readonly VariantLike[],
): string {
  return encodeCombinations(variantCombinations(options, variants));
}

/**
 * Encode the set of option-value combinations whose backing variant is
 * available for sale.
 *
 * @param options Product options in declaration order.
 * @param variants Product variants.
 * @returns The `v1_`-prefixed availability string, or `''` when the product
 *   has no options or no available variant.
 */
export function encodeVariantAvailability(
  options: readonly OptionLike[],
  variants: readonly VariantLike[],
): string {
  return encodeCombinations(
    variantCombinations(
      options,
      variants.filter((variant) => variant.availableForSale),
    ),
  );
}

/**
 * Map each variant to its option-value index tuple `[i0, i1, …]`.
 *
 * A variant is skipped when it lacks a selected value for an option or when a
 * selected value is not present in that option's value list — both indicate a
 * malformed dataset rather than a real combination to encode.
 */
function variantCombinations(
  options: readonly OptionLike[],
  variants: readonly VariantLike[],
): number[][] {
  if (options.length === 0) return [];
  const combinations: number[][] = [];
  for (const variant of variants) {
    const tuple: number[] = [];
    let placeable = true;
    for (const option of options) {
      const selected = variant.selectedOptions.find((sel) => sel.name === option.name);
      if (selected === undefined) {
        placeable = false;
        break;
      }
      const index = option.values.indexOf(selected.value);
      if (index < 0) {
        placeable = false;
        break;
      }
      tuple.push(index);
    }
    if (placeable) combinations.push(tuple);
  }
  return combinations;
}

/**
 * Serialize index tuples into a `v1_` encoded string.
 *
 * Tuples are de-duplicated and sorted lexicographically so the output is
 * deterministic. Returns `''` for an empty set.
 */
function encodeCombinations(combinations: readonly number[][]): string {
  if (combinations.length === 0) return '';

  const seen = new Set<string>();
  const unique: number[][] = [];
  for (const combination of combinations) {
    const key = combination.join(',');
    if (!seen.has(key)) {
      seen.add(key);
      unique.push([...combination]);
    }
  }
  unique.sort(compareTuples);

  const depth = unique[0]?.length ?? 0;
  // Single-option products have no `:` descent; sibling leaf values are space
  // separated and the final value is recovered by the decoder's trailing-digit
  // handling.
  if (depth === 1) {
    return V1_PREFIX + unique.map((tuple) => tuple[0]).join(' ');
  }
  // Multi-option products: spell out each combination and terminate it with the
  // `depth - 1` commas needed to pop from the leaf level back to the root.
  const terminator = ','.repeat(depth - 1);
  return V1_PREFIX + unique.map((tuple) => tuple.join(':')).join(terminator) + terminator;
}

/** Lexicographic comparison of equal-length numeric tuples. */
function compareTuples(a: readonly number[], b: readonly number[]): number {
  const length = Math.min(a.length, b.length);
  for (let i = 0; i < length; i++) {
    const left = a[i] ?? 0;
    const right = b[i] ?? 0;
    if (left !== right) return left - right;
  }
  return a.length - b.length;
}
