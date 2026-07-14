import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { loadShopData } from '../data/loader.js';
import {
  buildCollectionNode,
  buildImageNode,
  buildMenuItemNode,
  buildMoneyV2,
  buildPolicyNode,
  buildProductNode,
  buildProductVariantNode,
  gid,
  matchesSearch,
  stripHtml,
} from './builders.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);

const BASE_URL = 'https://shop.example';

const data = loadShopData(FIXTURE_DIR);

function productByHandle(handle: string) {
  const product = data.productsByHandle.get(handle);
  if (product === undefined) throw new Error(`fixture missing product '${handle}'`);
  return product;
}

describe('gid', () => {
  it('formats numeric ids verbatim', () => {
    expect(gid('Product', 9061637816494)).toBe('gid://shopify/Product/9061637816494');
    expect(gid('ProductVariant', 47642512195758)).toBe(
      'gid://shopify/ProductVariant/47642512195758',
    );
  });

  it('hashes string keys deterministically', () => {
    const first = gid('Menu', 'main-menu');
    const second = gid('Menu', 'main-menu');
    expect(first).toBe(second);
    expect(first).toMatch(/^gid:\/\/shopify\/Menu\/[0-9a-f]{8}$/);
  });

  it('produces distinct hashes for distinct keys', () => {
    expect(gid('Menu', 'main-menu')).not.toBe(gid('Menu', 'footer'));
  });

  it('namespaces hashes by type', () => {
    expect(gid('Menu', 'foo')).not.toBe(gid('MenuItem', 'foo'));
  });
});

describe('buildMoneyV2', () => {
  it('normalizes decimals to two places', () => {
    expect(buildMoneyV2('19.99', 'CAD')).toEqual({ amount: '19.99', currencyCode: 'CAD' });
    expect(buildMoneyV2('19', 'USD')).toEqual({ amount: '19.00', currencyCode: 'USD' });
    expect(buildMoneyV2('19.5', 'USD')).toEqual({ amount: '19.50', currencyCode: 'USD' });
  });

  it('falls back to 0.00 on a non-numeric amount', () => {
    expect(buildMoneyV2('not-a-number', 'CAD').amount).toBe('0.00');
  });
});

describe('buildImageNode', () => {
  it('rewrites a relative src to the same-origin /images/ route', () => {
    const node = buildImageNode(
      { id: 1, src: 'products/foo.jpg', alt: null, width: 100, height: 200, position: 1 },
      BASE_URL,
    );
    expect(node.url).toBe('/images/products/foo.jpg');
  });

  it('passes an absolute http(s) src through unchanged', () => {
    const cdn = 'https://cdn.shopify.com/foo.jpg';
    const node = buildImageNode(
      { id: 1, src: cdn, alt: 'cover', width: 100, height: 200, position: 1 },
      BASE_URL,
    );
    expect(node.url).toBe(cdn);
    expect(node.altText).toBe('cover');
  });

  it('strips leading slashes on src', () => {
    const node = buildImageNode(
      { id: 1, src: '/products/foo.jpg', alt: null, width: 1, height: 1, position: 1 },
      `${BASE_URL}/`,
    );
    expect(node.url).toBe('/images/products/foo.jpg');
  });

  it('does not duplicate a dataset src already rooted under images', () => {
    const node = buildImageNode(
      { id: 1, src: '/images/products/foo.jpg', alt: null, width: 1, height: 1, position: 1 },
      BASE_URL,
    );
    expect(node.url).toBe('/images/products/foo.jpg');
  });

  it('can preserve absolute backend image URLs for proxy-less storefronts', () => {
    const node = buildImageNode(
      { id: 1, src: '/images/products/foo.jpg', alt: null, width: 1, height: 1, position: 1 },
      BASE_URL,
      'absolute',
    );
    expect(node.url).toBe('https://shop.example/images/products/foo.jpg');
  });
});

describe('buildProductVariantNode', () => {
  const product = productByHandle('shopliseum-mushroom-dog-toys');
  const variant = product.variants[1];

  it('maps option1/option2/option3 onto product.options by position', () => {
    if (variant === undefined) throw new Error('expected variant at index 1');
    const node = buildProductVariantNode(product, variant, data.store, BASE_URL);
    expect(node.selectedOptions).toEqual([{ name: 'Red Mushroom', value: 'Blue Mushroom' }]);
  });

  it('exposes price + compareAtPrice in the store currency', () => {
    if (variant === undefined) throw new Error('expected variant at index 1');
    const node = buildProductVariantNode(product, variant, data.store, BASE_URL);
    expect(node.price).toEqual({ amount: '19.99', currencyCode: 'CAD' });
    expect(node.compareAtPrice).toBeNull();
  });

  it('plumbs requires_shipping through unchanged (spec §8.2)', () => {
    if (variant === undefined) throw new Error('expected variant at index 1');
    const node = buildProductVariantNode(product, variant, data.store, BASE_URL);
    expect(node.requiresShipping).toBe(true);
  });

  it('mints stable variant + product GIDs', () => {
    if (variant === undefined) throw new Error('expected variant at index 1');
    const node = buildProductVariantNode(product, variant, data.store, BASE_URL);
    expect(node.id).toBe(`gid://shopify/ProductVariant/${variant.id}`);
    expect(node.product.id).toBe(`gid://shopify/Product/${product.id}`);
  });
});

describe('buildProductVariantNode with inventory', () => {
  const product = productByHandle('shopliseum-mushroom-dog-toys');

  function variantById(id: number) {
    const variant = product.variants.find((v) => v.id === id);
    if (variant === undefined) throw new Error(`fixture missing variant ${id}`);
    return variant;
  }

  it('exposes the tracked count and stays availableForSale when stock > 0', () => {
    const variant = variantById(47242666836142);
    const node = buildProductVariantNode(
      product,
      variant,
      data.store,
      BASE_URL,
      data.inventoryByVariantId,
    );
    expect(node.quantityAvailable).toBe(2);
    expect(node.availableForSale).toBe(true);
  });

  it('overrides availableForSale to false when the tracked count is zero', () => {
    const variant = variantById(47242687709358);
    expect(variant.available).toBe(true);
    const node = buildProductVariantNode(
      product,
      variant,
      data.store,
      BASE_URL,
      data.inventoryByVariantId,
    );
    expect(node.quantityAvailable).toBe(0);
    expect(node.availableForSale).toBe(false);
  });

  it('falls back to variant.available when quantity_available is null', () => {
    const variant = variantById(47242695737518);
    const node = buildProductVariantNode(
      product,
      variant,
      data.store,
      BASE_URL,
      data.inventoryByVariantId,
    );
    expect(node.quantityAvailable).toBeNull();
    expect(node.availableForSale).toBe(variant.available);
  });

  it('falls back to variant.available when no entry exists for the variant', () => {
    const variant = variantById(47242720215214);
    expect(data.inventoryByVariantId.has(variant.id)).toBe(false);
    const node = buildProductVariantNode(
      product,
      variant,
      data.store,
      BASE_URL,
      data.inventoryByVariantId,
    );
    expect(node.quantityAvailable).toBeNull();
    expect(node.availableForSale).toBe(variant.available);
  });

  it('falls back to variant.available when no inventory map is supplied', () => {
    const variant = variantById(47242687709358);
    const node = buildProductVariantNode(product, variant, data.store, BASE_URL);
    expect(node.quantityAvailable).toBeNull();
    expect(node.availableForSale).toBe(variant.available);
  });
});

describe('buildProductNode', () => {
  it('computes priceRange across variants and exposes available variants', () => {
    const product = productByHandle('shopliseum-mushroom-dog-toys');
    const node = buildProductNode(product, data.store, BASE_URL);
    expect(node.priceRange.minVariantPrice).toEqual({ amount: '19.99', currencyCode: 'CAD' });
    expect(node.priceRange.maxVariantPrice).toEqual({ amount: '19.99', currencyCode: 'CAD' });
    expect(node.availableForSale).toBe(true);
    expect(node.variants).toHaveLength(4);
  });

  it('reports availableForSale=false when no variant is available', () => {
    const product = productByHandle('cartanvil-mackerel-and-sardines-70g');
    const node = buildProductNode(product, data.store, BASE_URL);
    expect(node.availableForSale).toBe(false);
  });

  it('strips HTML out of description but preserves descriptionHtml', () => {
    const product = productByHandle('carthaeum-toothbrush');
    const node = buildProductNode(product, data.store, BASE_URL);
    expect(node.description).toBe(
      'Dual-headed dental toothbrush for cats and dogs. Helps reduce plaque buildup.',
    );
    expect(node.descriptionHtml).toBe(product.description_html);
  });

  it('picks the lowest-position image as featuredImage', () => {
    const product = productByHandle('shopliseum-mushroom-dog-toys');
    const node = buildProductNode(product, data.store, BASE_URL);
    expect(node.featuredImage?.url).toBe('/images/products/shopliseum-mushroom-dog-toys-1.jpg');
  });
});

describe('buildCollectionNode', () => {
  it('falls back to empty strings when description fields are null', () => {
    const collection = data.collections[0];
    if (collection === undefined) throw new Error('fixture missing collection');
    const node = buildCollectionNode(collection, BASE_URL);
    expect(node.id).toBe(`gid://shopify/Collection/${collection.id}`);
    expect(node.title).toBe(collection.title);
    expect(typeof node.description).toBe('string');
    expect(typeof node.descriptionHtml).toBe('string');
  });
});

describe('buildMenuItemNode', () => {
  it('recurses over children and stamps deterministic ids', () => {
    const main = data.navigation['main-menu'];
    if (main === undefined || main[0] === undefined) {
      throw new Error('fixture missing main-menu[0]');
    }
    const node = buildMenuItemNode(main[0]);
    expect(node.id).toMatch(/^gid:\/\/shopify\/MenuItem\/[0-9a-f]{8}$/);
    expect(node.title).toBe(main[0].title);
    expect(node.items).toHaveLength(main[0].children.length);
  });
});

describe('buildPolicyNode', () => {
  it('derives a public URL from the store domain + handle', () => {
    const policy = data.policies[0];
    if (policy === undefined) throw new Error('fixture missing policy');
    const node = buildPolicyNode(policy, data.store);
    expect(node.url).toBe(`https://${data.store.domain}/policies/${policy.handle}`);
    expect(node.body).toBe(policy.body_html);
  });
});

describe('stripHtml', () => {
  it('removes tags and collapses whitespace', () => {
    expect(stripHtml('<p>Hello\n  <b>world</b></p>')).toBe('Hello world');
  });

  it('returns the empty string for input that is only tags', () => {
    expect(stripHtml('<br/><br/>')).toBe('');
  });
});

describe('matchesSearch', () => {
  it('matches when every lowercased term appears in the haystack', () => {
    expect(matchesSearch('Mushroom toy', 'plush mushroom-shaped squeaky dog toys')).toBe(true);
  });

  it('returns false if any term is missing', () => {
    expect(matchesSearch('mushroom catfish', 'plush mushroom-shaped squeaky dog toys')).toBe(false);
  });

  it('returns true on an empty query', () => {
    expect(matchesSearch('', 'anything')).toBe(true);
    expect(matchesSearch('   ', 'anything')).toBe(true);
  });
});
