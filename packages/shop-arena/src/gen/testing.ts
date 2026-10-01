/**
 * Test doubles for the gen pipeline: a scripted `LlmClient` that answers
 * every synthesis prompt with a deterministic, schema-valid reply, and a
 * writer for a minimal Shop Manual fixture. No real merchant data.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { CompleteRequest, Completion, LlmClient } from '@shop-gym/agent';

import { capabilitiesSchema } from '../explore/capabilities.js';

/** JSON blocks of a rendered prompt, in order. */
function jsonBlocks(prompt: string): unknown[] {
  return [...prompt.matchAll(/```json\n([\s\S]*?)\n```/g)].map((m) => JSON.parse(m[1] ?? 'null'));
}

function handlesOf(value: unknown): string[] {
  return Array.isArray(value) ? value.map((v) => (v as { handle: string }).handle) : [];
}

export interface ScriptedSynthOptions {
  /** Vendor the first details reply uses for its first product; defaults to an allowlisted brand. */
  readonly firstVendor?: string;
}

/**
 * Answers each `data_synth` prompt from its first line. Replies are derived
 * from the JSON blocks of the prompt so counts and handles always agree
 * with what the step asked for.
 */
export class ScriptedSynthLlm implements LlmClient {
  readonly requests: CompleteRequest[] = [];
  private detailsCalls = 0;

  constructor(private readonly options: ScriptedSynthOptions = {}) {}

  async complete(request: CompleteRequest): Promise<Completion> {
    this.requests.push(request);
    if (typeof request.prompt !== 'string') {
      throw new Error('ScriptedSynthLlm: expected a string prompt');
    }
    return {
      text: JSON.stringify(this.reply(request.prompt)),
      model: request.model.id,
      stopReason: 'end_turn',
      usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, costUsd: 0 },
    };
  }

  private reply(prompt: string): unknown {
    const body = prompt.replace(
      /^[\s\S]*?Re-emit the JSON value from scratch[^\n]*\n[^\n]*\n\n/,
      '',
    );
    const first = body.split('\n')[0] ?? '';
    const blocks = jsonBlocks(body);
    if (first.includes('brand identity')) {
      return {
        descriptor: 'Minimal Homeware Shop',
        tone: ['calm', 'warm'],
        currency: 'USD',
        country: 'US',
      };
    }
    if (first.includes('`store.json`')) {
      return {
        domain: 'shop.example',
        description: 'Homeware for calm rooms.',
        payment_settings: { accepted_card_brands: ['VISA', 'MASTERCARD'] },
        brand: { logo_url: null, colors: { primary: '#223344', secondary: '#eeeeee' } },
      };
    }
    if (first.includes('content pages')) {
      return [
        { handle: 'about-us', title: 'About Us', body_html: '<p>We make quiet things.</p>' },
        { handle: 'contact', title: 'Contact', body_html: '<p>Write to hello@shop.example.</p>' },
      ];
    }
    if (first.includes('policy pages')) {
      return ['privacy-policy', 'shipping-policy', 'terms-of-service', 'refund-policy'].map(
        (handle) => ({
          handle,
          title: handle.replace(/-/g, ' '),
          body_html: `<p>${handle}: standard shipping 5.00, free over 50.00, 30 day returns.</p>`,
        }),
      );
    }
    if (first.includes('checkout rules')) {
      return {
        tax_rate: 0.08,
        free_shipping_threshold: '50.00',
        shipping_methods: [
          { handle: 'standard', title: 'Standard', price: '5.00' },
          { handle: 'express', title: 'Express', price: '12.00' },
        ],
        payment_methods: [{ handle: 'card', title: 'Credit card' }],
      };
    }
    if (first.includes('collections (categories)')) {
      const count = Number(/exactly (\d+) collection/.exec(body)?.[1] ?? 1);
      const total = Number(/must equal (\d+)/.exec(body)?.[1] ?? count * 2);
      const per = Math.floor(total / count);
      return Array.from({ length: count }, (_, i) => ({
        title: `Collection ${i + 1}`,
        handle: `collection-${i + 1}`,
        description: `Everything in group ${i + 1}.`,
        sort_order: 'manual',
        target_product_count: i === count - 1 ? total - per * (count - 1) : per,
      }));
    }
    if (first.includes('catalog skeleton')) {
      const collections = blocks[0] as { handle: string; target_product_count: number }[];
      return collections.flatMap((c) =>
        Array.from({ length: c.target_product_count }, (_, i) => ({
          title: `Oak Bowl ${c.handle.split('-')[1]}${i + 1}`,
          handle: `${c.handle}-item-${i + 1}`,
          price: `${20 + i}.00`,
          collection_handle: c.handle,
        })),
      );
    }
    if (first.includes('rich product details')) {
      this.detailsCalls += 1;
      const skeletons = handlesOf(blocks[2]);
      return skeletons.map((handle, i) => ({
        handle,
        description_html: `<p>A sturdy ${handle.replace(/-/g, ' ')} for the table.</p>`,
        vendor:
          this.detailsCalls === 1 && i === 0
            ? (this.options.firstVendor ?? 'AisleArena')
            : 'AisleArena',
        product_type: 'Bowl',
        tags: ['bowl', 'oak'],
        options: [{ name: 'Size', position: 1, values: ['Small', 'Large'] }],
        variants: ['Small', 'Large'].map((size, p) => ({
          title: size,
          sku: `${handle}-${size.toLowerCase()}`,
          price: `${20 + p * 5}.00`,
          compare_at_price: null,
          available: true,
          option1: size,
          option2: null,
          option3: null,
          position: p + 1,
          requires_shipping: true,
        })),
      }));
    }
    if (first.includes('image alt-text')) {
      const perProduct = Number(/write (\d+) short/.exec(body)?.[1] ?? 1);
      return handlesOf(blocks[1]).map((handle) => ({
        handle,
        alts: Array.from(
          { length: perProduct },
          (_, i) => `Shot ${i + 1} of the ${handle} on a wooden bench.`,
        ),
      }));
    }
    if (first.includes('navigation menus')) {
      const collections = blocks[0] as { title: string; handle: string }[];
      const pages = blocks[1] as { title: string; handle: string }[];
      return {
        'main-menu': [
          { title: 'Home', url: '/', type: 'HTTP', children: [] },
          ...collections.map((c) => ({
            title: c.title,
            url: `/collections/${c.handle}`,
            type: 'COLLECTION',
            children: [],
          })),
        ],
        footer: pages.map((p) => ({
          title: p.title,
          url: `/pages/${p.handle}`,
          type: 'PAGE',
          children: [],
        })),
      };
    }
    if (first.includes('customer personas')) {
      const count = Number(/inventing (\d+) fictional/.exec(body)?.[1] ?? 3);
      return Array.from({ length: count }, (_, i) => ({
        first_name: ['Jane', 'Omar', 'Lena'][i] ?? `Person${i}`,
        last_name: ['Doe', 'Haddad', 'Berg'][i] ?? 'Example',
        phone: null,
        accepts_marketing: i === 0,
        address: {
          address1: `${i + 1} Example Street`,
          address2: null,
          city: 'Springfield',
          province: 'Illinois',
          province_code: 'IL',
          zip: `6270${i}`,
        },
      }));
    }
    throw new Error(`ScriptedSynthLlm: unrecognised prompt: ${first}`);
  }
}

const MANUAL_MD = `# Shop Manual - Minimal Homeware Shop

## Overview

A compact homeware storefront with a drawer cart.

## Site shell

Single-row header with one link per collection.

## Homepage

Hero followed by a featured collection grid.

## Product page

Gallery on the left, buy box on the right.

## Cart

Drawer cart with a promo input.
`;

/** Writes `manual.md`, `capabilities.json`, and `stats.json` into `dir`. */
export async function writeManualFixture(
  dir: string,
  overrides: { descriptor?: string; tone?: string[] } = {},
): Promise<string> {
  await fs.mkdir(dir, { recursive: true });
  const capabilities = capabilitiesSchema.parse({
    shop: {
      descriptor: overrides.descriptor ?? 'Minimal Homeware Shop',
      currency: 'USD',
      tone: overrides.tone ?? ['calm'],
    },
    homepage: { section_types: ['hero', 'featured_collection'], section_count: 2 },
    cart: { type: 'drawer', has_promo_input: true },
  });
  await fs.writeFile(path.join(dir, 'manual.md'), MANUAL_MD);
  await fs.writeFile(path.join(dir, 'capabilities.json'), JSON.stringify(capabilities, null, 2));
  await fs.writeFile(
    path.join(dir, 'stats.json'),
    JSON.stringify({
      products_total: 40,
      collections_total: 4,
      products_per_collection: { avg: 10, median: 10, max: 12 },
      price: { min: 10, max: 120, median: 35, currency: 'USD' },
      products_with_variants_pct: 50,
      variant_axes_observed: ['Size'],
      navigation_depth_max: 1,
      homepage_section_count: 2,
      info_pages_count: 2,
      feature_count: 4,
    }),
  );
  return dir;
}
