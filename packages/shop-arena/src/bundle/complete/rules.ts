/**
 * Rule fills of the complete step: the catalog fields that Shop generation
 * needs and that a rule can derive. Each filled field gets a provenance
 * mark: `inferred` when the value comes from other source values, and
 * `synthetic` when it is made up.
 *
 * - `category_path`: the most common top category of the catalog (inferred).
 * - `brand`: the seller (inferred), else `Generic` (synthetic).
 * - `description`: the bullets, one per line, else the title (inferred).
 * - `variants[].price`: the price of another variant of the product, else
 *   the median price of the products that share the longest category path
 *   prefix with it, else of the whole catalog (inferred).
 * - `variants[].inventory`: a seeded whole number from 1 to 50 (synthetic).
 */

import type { BundleProduct, BundleVariant, Price, ProvenanceKind } from '@shop-gym/core';

import { stableId } from '../../gen/data_synth/ids.js';
import { compareStrings } from '../sample.js';

/** The brand of a product that has no brand and no seller. */
export const GENERIC_BRAND = 'Generic';
const MAX_INVENTORY = 50;
const PATH_SEPARATOR = '\u001f';

/** The number of products (or variants, for inventory) that each rule filled. */
export interface RuleFillCounts {
  readonly categories_inferred: number;
  readonly brands_from_seller: number;
  readonly brands_synthetic: number;
  readonly descriptions_inferred: number;
  readonly prices_inferred: number;
  readonly inventories_synthetic: number;
}

export interface RuleFills {
  /** In the input order. */
  readonly products: readonly BundleProduct[];
  readonly counts: RuleFillCounts;
}

/** Fill the gaps of `products` by rules; `seed` makes the inventory repeatable. */
export function fillByRules(products: readonly BundleProduct[], seed: string): RuleFills {
  const counts = {
    categories_inferred: 0,
    brands_from_seller: 0,
    brands_synthetic: 0,
    descriptions_inferred: 0,
    prices_inferred: 0,
    inventories_synthetic: 0,
  };
  const topCategory = mostCommonTopCategory(products);
  const withText = products.map((product) => {
    const marks: Record<string, ProvenanceKind> = {};
    let { category_path, brand, description } = product;
    if (category_path === undefined && topCategory !== undefined) {
      category_path = [topCategory];
      marks.category_path = 'inferred';
      counts.categories_inferred += 1;
    }
    if (brand === undefined) {
      brand = product.seller ?? GENERIC_BRAND;
      marks.brand = product.seller !== undefined ? 'inferred' : 'synthetic';
      if (product.seller !== undefined) counts.brands_from_seller += 1;
      else counts.brands_synthetic += 1;
    }
    if (description === undefined) {
      description = product.bullets?.join('\n') ?? product.title;
      marks.description = 'inferred';
      counts.descriptions_inferred += 1;
    }
    return marked(
      {
        ...product,
        ...(category_path !== undefined ? { category_path } : {}),
        brand,
        description,
      },
      marks,
    );
  });

  const medians = new CategoryPrices(withText);
  const filled = withText.map((product) => {
    const marks: Record<string, ProvenanceKind> = {};
    const fallback =
      product.variants.find((variant) => variant.price !== undefined)?.price ??
      medians.priceFor(product.category_path ?? []);
    const variants = product.variants.map((variant): BundleVariant => {
      let { price, inventory } = variant;
      if (price === undefined && fallback !== undefined) {
        price = fallback;
        marks['variants[].price'] = 'inferred';
      }
      if (inventory === undefined) {
        inventory = (stableId(`inventory\0${seed}`, variant.variant_id) % MAX_INVENTORY) + 1;
        marks['variants[].inventory'] = 'synthetic';
        counts.inventories_synthetic += 1;
      }
      return {
        ...variant,
        ...(price !== undefined ? { price } : {}),
        inventory,
      };
    });
    if (marks['variants[].price'] !== undefined) counts.prices_inferred += 1;
    return marked({ ...product, variants }, marks);
  });
  return { products: filled, counts };
}

/** Add provenance marks to a product, after the marks that it has. */
export function marked(
  product: BundleProduct,
  marks: Readonly<Record<string, ProvenanceKind>>,
): BundleProduct {
  if (Object.keys(marks).length === 0) return product;
  return { ...product, provenance: { ...product.provenance, ...marks } };
}

function mostCommonTopCategory(products: readonly BundleProduct[]): string | undefined {
  const counts = new Map<string, number>();
  for (const product of products) {
    const top = product.category_path?.[0];
    if (top !== undefined) counts.set(top, (counts.get(top) ?? 0) + 1);
  }
  return [...counts].sort((a, b) => b[1] - a[1] || compareStrings(a[0], b[0]))[0]?.[0];
}

/** Median prices by category path prefix, from one price per priced product. */
class CategoryPrices {
  private readonly byPrefix = new Map<string, number[]>();
  private readonly all: number[] = [];
  private readonly currency: string | undefined;

  constructor(products: readonly BundleProduct[]) {
    let currency: string | undefined;
    for (const product of products) {
      const price = product.variants.find((variant) => variant.price !== undefined)?.price;
      if (price === undefined) continue;
      currency = price.currency;
      this.all.push(price.amount);
      const categoryPath = product.category_path ?? [];
      for (let depth = 1; depth <= categoryPath.length; depth += 1) {
        const key = categoryPath.slice(0, depth).join(PATH_SEPARATOR);
        const amounts = this.byPrefix.get(key);
        if (amounts === undefined) this.byPrefix.set(key, [price.amount]);
        else amounts.push(price.amount);
      }
    }
    this.currency = currency;
  }

  /** The median of the longest prefix of `categoryPath` that has prices, else of all prices. */
  priceFor(categoryPath: readonly string[]): Price | undefined {
    if (this.currency === undefined) return undefined;
    for (let depth = categoryPath.length; depth >= 1; depth -= 1) {
      const amounts = this.byPrefix.get(categoryPath.slice(0, depth).join(PATH_SEPARATOR));
      if (amounts !== undefined) return { amount: median(amounts), currency: this.currency };
    }
    return { amount: median(this.all), currency: this.currency };
  }
}

/** The median, rounded to cents; `amounts` is not empty. */
function median(amounts: readonly number[]): number {
  const sorted = [...amounts].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  const value =
    sorted.length % 2 === 1
      ? (sorted[middle] ?? 0)
      : ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2;
  return Math.round(value * 100) / 100;
}
