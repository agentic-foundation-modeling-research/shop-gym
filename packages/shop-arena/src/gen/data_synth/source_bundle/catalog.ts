/**
 * The shop catalog of a Source bundle: products, collections, inventory,
 * the department menu and the product images.
 *
 * Products are sorted by bundle product id and numbered from 1, and so
 * are their variants and images, across the whole catalog. A handle is
 * the slug of the title, made unique in the same order. Each node of a
 * category path is one collection that lists every product under it; the
 * main menu links each top-level node (a department) and the nodes one
 * level below it. Images come from the local image files of the bundle;
 * a product with none gets one placeholder image.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { BUNDLE_FILES } from '@shop-gym/core';
import type {
  Collection,
  InventoryFile,
  Product,
  ProductImage,
  ProductVariant,
} from '@shop-gym/shop-backend';

import { writeBytes } from '../../io.js';
import { SynthError } from '../../llm.js';
import { type Catalog, TIMESTAMP } from '../assemble.js';
import type { SynthContext } from '../context.js';
import { renderPlaceholder } from '../images/placeholder.js';
import { IMAGES_DIR, IMAGE_SIZE, imageFileName } from '../images/step.js';
import type { NavigationItem } from '../schemas.js';
import { firstSeen } from './clock.js';
import { imageInfo } from './image_size.js';
import type { CompleteProduct, SourceBundle } from './read.js';

/** Longest handle made from a title, before a `-2` suffix that makes it unique. */
const MAX_HANDLE_LENGTH = 60;
/** A shop product has at most three options. */
const MAX_OPTIONS = 3;
const DEFAULT_OPTION = { name: 'Title', value: 'Default Title' } as const;

export interface BundleCatalog extends Catalog {
  readonly inventory: InventoryFile;
  /** The department menu: each department with the categories one level below it. */
  readonly mainMenu: readonly NavigationItem[];
  /** The shop product of each bundle product id. */
  readonly productOf: ReadonlyMap<string, Product>;
  /** The shop product and variant of each bundle variant id. */
  readonly variantOf: ReadonlyMap<string, { product: Product; variant: ProductVariant }>;
}

/** Code-unit order, so that the order does not depend on the locale. */
export function compareIds(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * A lowercase handle of letters, digits and dashes. A long slug is cut at
 * the last dash within the limit, so that no word is split.
 */
function slugify(text: string, fallback: string): string {
  const slug = text
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  if (slug.length <= MAX_HANDLE_LENGTH) return slug === '' ? fallback : slug;
  const cut = slug.slice(0, MAX_HANDLE_LENGTH + 1);
  const dash = cut.lastIndexOf('-');
  return dash > 0 ? cut.slice(0, dash) : cut.slice(0, MAX_HANDLE_LENGTH);
}

/** The slugs of `texts`, in order, with `-2`, `-3`, ... added to repeats. */
function uniqueHandles(texts: readonly string[], fallback: string): string[] {
  const used = new Set<string>();
  return texts.map((text) => {
    const base = slugify(text, fallback);
    let handle = base;
    for (let n = 2; used.has(handle); n += 1) handle = `${base}-${n}`;
    used.add(handle);
    return handle;
  });
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"]/g, (char) => `&#${char.charCodeAt(0)};`);
}

/** Description paragraphs, then the bullets as a list. */
function descriptionHtml(product: CompleteProduct): string {
  const paragraphs = product.description
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter((p) => p !== '')
    .map((p) => `<p>${escapeHtml(p)}</p>`);
  const bullets =
    product.bullets === undefined
      ? []
      : [`<ul>${product.bullets.map((b) => `<li>${escapeHtml(b)}</li>`).join('')}</ul>`];
  return [...paragraphs, ...bullets].join('');
}

/** The options of `product` and the option values of each variant, in option order. */
function optionTable(product: CompleteProduct): {
  options: Product['options'];
  values: string[][];
} {
  const named = product.options ?? [];
  if (named.length > MAX_OPTIONS) {
    throw new SynthError(
      `bundle product ${product.product_id} has ${named.length} options; a shop product has at most ${MAX_OPTIONS}`,
    );
  }
  if (named.length === 0) {
    return {
      options: [{ name: DEFAULT_OPTION.name, position: 1, values: [DEFAULT_OPTION.value] }],
      values: product.variants.map(() => [DEFAULT_OPTION.value]),
    };
  }
  const values = product.variants.map((variant) =>
    named.map((option) => variant.option_values?.[option.name] ?? option.values[0] ?? ''),
  );
  return {
    options: named.map((option, i) => ({
      name: option.name,
      position: i + 1,
      values: [...new Set([...option.values, ...values.map((v) => v[i] ?? '')])],
    })),
    values,
  };
}

interface Counters {
  variant: number;
  image: number;
  copied: number;
  placeholders: number;
  skipped: number;
}

/** Copies the local images of `product` into `data/images/`, or renders one placeholder. */
async function productImages(
  sc: SynthContext,
  bundle: SourceBundle,
  product: CompleteProduct,
  handle: string,
  productType: string,
  counters: Counters,
): Promise<ProductImage[]> {
  const catalogDir = path.join(bundle.dir, path.dirname(BUNDLE_FILES.products));
  const images: ProductImage[] = [];
  for (const image of product.images ?? []) {
    if (image.path === undefined) continue;
    const bytes = await fs.readFile(path.join(catalogDir, image.path));
    const info = imageInfo(bytes);
    if (info === undefined) {
      counters.skipped += 1;
      sc.log(`[data_synth] bundle image ${image.path}: not a PNG or JPEG file, left out`);
      continue;
    }
    const src = imageFileName(handle, images.length, info.extension);
    await writeBytes(path.join(sc.dataDir, IMAGES_DIR, src), bytes);
    counters.image += 1;
    counters.copied += 1;
    images.push({
      id: counters.image,
      src,
      alt: image.alt ?? null,
      width: info.width,
      height: info.height,
      position: images.length + 1,
    });
  }
  if (images.length > 0) return images;
  const src = imageFileName(handle, 0, '.png');
  const bytes = renderPlaceholder({
    handle,
    index: 0,
    title: product.title,
    category: productType,
    width: IMAGE_SIZE,
    height: IMAGE_SIZE,
  });
  await writeBytes(path.join(sc.dataDir, IMAGES_DIR, src), bytes);
  counters.image += 1;
  counters.placeholders += 1;
  return [
    {
      id: counters.image,
      src,
      alt: product.title,
      width: IMAGE_SIZE,
      height: IMAGE_SIZE,
      position: 1,
    },
  ];
}

function shopProduct(
  product: CompleteProduct,
  id: number,
  handle: string,
  handleOf: ReadonlyMap<string, string>,
  createdAt: string,
  images: ProductImage[],
  counters: Counters,
): Product {
  const { options, values } = optionTable(product);
  const productType = product.category_path.at(-1) ?? '';
  const handles = (ids: readonly string[] | undefined): string[] =>
    (ids ?? []).flatMap((relatedId) => handleOf.get(relatedId) ?? []);
  return {
    id,
    title: product.title,
    handle,
    description_html: descriptionHtml(product),
    vendor: product.seller ?? product.brand,
    product_type: productType,
    tags: [...product.category_path],
    published_at: createdAt,
    created_at: createdAt,
    updated_at: createdAt,
    options,
    variants: product.variants.map((variant, j) => {
      counters.variant += 1;
      const optionValues = values[j] ?? [];
      return {
        id: counters.variant,
        title: optionValues.join(' / '),
        sku: variant.variant_id,
        price: variant.price.amount.toFixed(2),
        compare_at_price: null,
        available: variant.inventory > 0,
        option1: optionValues[0] ?? null,
        option2: optionValues[1] ?? null,
        option3: optionValues[2] ?? null,
        position: j + 1,
        requires_shipping: true,
      };
    }),
    images,
    brand: product.brand,
    category_path: [...product.category_path],
    ...(product.attributes !== undefined ? { attributes: product.attributes } : {}),
    ...(product.related !== undefined
      ? {
          related: {
            bought_together: handles(product.related.bought_together),
            also_bought: handles(product.related.also_bought),
          },
        }
      : {}),
    ...(product.source !== undefined ? { source: product.source } : {}),
    ...(product.provenance !== undefined ? { provenance: product.provenance } : {}),
  };
}

/** One collection per category node, in path order, and the department menu. */
function categoryCollections(products: readonly (readonly [CompleteProduct, Product])[]): {
  collections: Collection[];
  mainMenu: NavigationItem[];
} {
  const members = new Map<string, { path: readonly string[]; handles: string[] }>();
  for (const [source, product] of products) {
    source.category_path.forEach((_, depth) => {
      const nodePath = source.category_path.slice(0, depth + 1);
      const key = nodePath.join('\0');
      const node = members.get(key) ?? { path: nodePath, handles: [] };
      node.handles.push(product.handle);
      members.set(key, node);
    });
  }
  const nodes = [...members.entries()].sort(([a], [b]) => compareIds(a, b)).map(([, node]) => node);
  const handles = uniqueHandles(
    nodes.map((node) => node.path.join(' ')),
    'collection',
  );
  const collections = nodes.map((node, i) => {
    const description = node.path.join(' > ');
    return {
      id: i + 1,
      title: node.path.at(-1) ?? '',
      handle: handles[i] ?? '',
      description,
      description_html: `<p>${escapeHtml(description)}</p>`,
      image: null,
      published_at: TIMESTAMP,
      updated_at: TIMESTAMP,
      sort_order: 'manual',
      product_handles: node.handles,
    };
  });
  const item = (c: Collection) => ({
    title: c.title,
    url: `/collections/${c.handle}`,
    type: 'COLLECTION' as const,
  });
  const mainMenu = nodes.flatMap((department, i) => {
    const collection = collections[i];
    if (department.path.length !== 1 || collection === undefined) return [];
    const children = nodes.flatMap((node, j) => {
      const child = collections[j];
      return node.path.length === 2 && node.path[0] === department.path[0] && child !== undefined
        ? [{ ...item(child), children: [] }]
        : [];
    });
    return [{ ...item(collection), children }];
  });
  return { collections, mainMenu };
}

/**
 * Maps the products of `bundle` into shop products and collections, and
 * writes their images under `data/images/`.
 *
 * @throws SynthError when a product has more than three options.
 */
export async function mapBundleCatalog(
  sc: SynthContext,
  bundle: SourceBundle,
): Promise<BundleCatalog> {
  const sorted = [...bundle.products].sort((a, b) => compareIds(a.product_id, b.product_id));
  const handles = uniqueHandles(
    sorted.map((p) => p.title),
    'product',
  );
  const handleOf = new Map(sorted.map((p, i) => [p.product_id, handles[i] ?? '']));
  const createdAt = firstSeen(bundle, 'product_id');
  const counters: Counters = { variant: 0, image: 0, copied: 0, placeholders: 0, skipped: 0 };
  const pairs: (readonly [CompleteProduct, Product])[] = [];
  for (const [i, source] of sorted.entries()) {
    const handle = handles[i] ?? '';
    const productType = source.category_path.at(-1) ?? '';
    const images = await productImages(sc, bundle, source, handle, productType, counters);
    pairs.push([
      source,
      shopProduct(source, i + 1, handle, handleOf, createdAt(source.product_id), images, counters),
    ]);
  }
  sc.log(
    `[data_synth] bundle images: ${counters.copied} copied, ${counters.placeholders} placeholders, ${counters.skipped} left out`,
  );
  const products = pairs.map(([, product]) => product);
  const inventory: Record<string, { quantity_available: number }> = {};
  const variantOf = new Map<string, { product: Product; variant: ProductVariant }>();
  for (const [source, product] of pairs) {
    source.variants.forEach((variant, j) => {
      const shopVariant = product.variants[j];
      if (shopVariant === undefined) return;
      inventory[String(shopVariant.id)] = { quantity_available: variant.inventory };
      variantOf.set(variant.variant_id, { product, variant: shopVariant });
    });
  }
  return {
    products,
    ...categoryCollections(pairs),
    inventory,
    productOf: new Map(pairs.map(([source, product]) => [source.product_id, product])),
    variantOf,
  };
}
