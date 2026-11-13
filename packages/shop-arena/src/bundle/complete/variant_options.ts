/**
 * Variant options of the complete step. A product with more than one
 * variant needs an option name and one value of it for each variant. When
 * the product does not have them, an LLM infers one option from the
 * title, the description, the bullets and the attributes. The option and
 * the values are marked `synthetic`. The values go to the variants in
 * their bundle order.
 */

import { fileURLToPath } from 'node:url';

import type { BundleProduct } from '@shop-gym/core';
import { z } from 'zod';

import { mapLimit } from '../../gen/io.js';
import { type LlmCall, loadPrompt } from '../../gen/llm.js';
import { cachedStructured } from './llm_cache.js';
import { marked } from './rules.js';

const PROMPTS_DIR = fileURLToPath(new URL('./prompts/', import.meta.url));
/** Longest description, in characters, that the prompt shows. */
const MAX_DESCRIPTION_CHARS = 2000;
const MAX_BULLETS = 10;
const MAX_NAME_CHARS = 40;
const MAX_VALUE_CHARS = 60;

const optionReplySchema = z.strictObject({
  name: z.string().trim().min(1),
  values: z.array(z.string().trim().min(1)).min(2),
});

type OptionReply = z.infer<typeof optionReplySchema>;

export interface VariantOptionsDeps {
  readonly call: LlmCall;
  readonly cacheDir: string;
  readonly concurrency: number;
  readonly log: (line: string) => void;
}

/**
 * Give each product with more than one variant an option and a value of it
 * on each variant, where the product does not have them yet.
 *
 * @returns The products in the input order, and the number that the LLM named.
 * @throws SynthError when a reply is still not valid after one repair call.
 */
export async function nameVariants(
  products: readonly BundleProduct[],
  deps: VariantOptionsDeps,
): Promise<{ readonly products: BundleProduct[]; readonly named: number }> {
  const todo = products.filter((product) => !hasOptionValues(product));
  let cached = 0;
  const replies = await mapLimit(todo, deps.concurrency, async (product) => {
    const reply = await cachedStructured(
      deps.cacheDir,
      deps.call,
      optionsPrompt(product),
      optionReplySchema,
      (value) => checkReply(value, product.variants.length),
    );
    if (reply.cached) cached += 1;
    return [product.product_id, reply.value] as const;
  });
  deps.log(`[complete] variant options: ${todo.length} products (${cached} from the cache)`);
  const byId = new Map<string, OptionReply>(replies);
  const named = products.map((product) => {
    const reply = byId.get(product.product_id);
    return reply === undefined ? product : withOption(product, reply);
  });
  return { products: named, named: todo.length };
}

/** True when the product has one variant, or names its options and each variant has a value. */
function hasOptionValues(product: BundleProduct): boolean {
  if (product.variants.length < 2) return true;
  const names = (product.options ?? []).map((option) => option.name);
  return (
    names.length > 0 &&
    product.variants.every((variant) =>
      names.every((name) => variant.option_values?.[name] !== undefined),
    )
  );
}

function optionsPrompt(product: BundleProduct): string {
  const facts = {
    title: product.title,
    ...(product.category_path !== undefined ? { category_path: product.category_path } : {}),
    ...(product.brand !== undefined ? { brand: product.brand } : {}),
    ...(product.description !== undefined
      ? { description: product.description.slice(0, MAX_DESCRIPTION_CHARS) }
      : {}),
    ...(product.bullets !== undefined ? { bullets: product.bullets.slice(0, MAX_BULLETS) } : {}),
    ...(product.attributes !== undefined ? { attributes: product.attributes } : {}),
    variant_count: product.variants.length,
  };
  return loadPrompt(PROMPTS_DIR, 'variant_options', {
    product: JSON.stringify(facts, null, 2),
    variant_count: String(product.variants.length),
  });
}

function checkReply(reply: OptionReply, variantCount: number): string | undefined {
  if (reply.name.length > MAX_NAME_CHARS) {
    return `name must be at most ${MAX_NAME_CHARS} characters`;
  }
  if (reply.values.length !== variantCount) {
    return `values must have exactly ${variantCount} entries, got ${reply.values.length}`;
  }
  const long = reply.values.find((value) => value.length > MAX_VALUE_CHARS);
  if (long !== undefined) {
    return `value ${JSON.stringify(long)} is longer than ${MAX_VALUE_CHARS} characters`;
  }
  const seen = new Set<string>();
  for (const value of reply.values) {
    const key = value.toLowerCase();
    if (seen.has(key)) return `values must be distinct; ${JSON.stringify(value)} repeats`;
    seen.add(key);
  }
  return undefined;
}

function withOption(product: BundleProduct, reply: OptionReply): BundleProduct {
  return marked(
    {
      ...product,
      options: [{ name: reply.name, values: reply.values }],
      variants: product.variants.map((variant, index) => ({
        ...variant,
        // `checkReply` makes `values` exactly as long as `variants`.
        option_values: { [reply.name]: reply.values[index] ?? '' },
      })),
    },
    { options: 'synthetic', 'variants[].option_values': 'synthetic' },
  );
}
