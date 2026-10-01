import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  CAPABILITY_KEYS,
  CapabilitiesValidationError,
  capabilitiesJsonSchema,
  capabilitiesSchema,
  mergeFragments,
  parseCapabilities,
} from './capabilities.js';

const SPEC_EXAMPLE = {
  version: '0.1',
  shop: {
    descriptor: 'Luxury Jewelry Store',
    category: 'jewelry',
    currency: 'USD',
    tone: ['premium', 'minimal'],
  },
  site_shell: {
    has_announcement_bar: true,
    header_style: 'two-row',
    has_mega_menu: true,
    nav_depth: 3,
    footer_groups: 4,
  },
  homepage: {
    section_types: ['hero', 'featured_collection', 'testimonials', 'newsletter'],
    section_count: 9,
    has_popup_modal: true,
  },
  collection: {
    layout: 'grid',
    columns_desktop: 4,
    filters: ['price', 'material', 'size'],
    sort: ['featured', 'price_asc', 'price_desc', 'newest'],
    pagination: 'load_more',
  },
  product: {
    gallery_style: 'thumbnails_left',
    variant_selectors: ['swatch', 'dropdown'],
    has_quantity_selector: true,
    description_layout: 'accordion',
    has_reviews: true,
    has_recommendations: true,
    has_personalization: true,
  },
  cart: {
    type: 'drawer',
    has_promo_input: true,
    has_upsells: true,
    has_shipping_estimate: false,
  },
  search: {
    trigger: 'icon',
    has_predictive: true,
    predictive_types: ['products', 'collections', 'pages'],
    results_layout: 'grid',
  },
  floating: {
    has_chat_widget: true,
    has_age_gate: false,
    has_cookie_banner: true,
    has_newsletter_popup: true,
  },
  intl: { has_locale_switcher: true, has_currency_switcher: true },
  info_pages_present: [
    'about',
    'contact',
    'faq',
    'shipping',
    'returns',
    'privacy',
    'tos',
    'accessibility',
  ],
};

let partsDir: string;

beforeEach(() => {
  partsDir = mkdtempSync(join(tmpdir(), 'caps-'));
});

afterEach(() => {
  rmSync(partsDir, { recursive: true, force: true });
});

function fragment(name: string, value: unknown): void {
  writeFileSync(join(partsDir, name), typeof value === 'string' ? value : JSON.stringify(value));
}

describe('capabilitiesSchema', () => {
  it('round-trips the spec example and fills the new sections with defaults', () => {
    const parsed = parseCapabilities(SPEC_EXAMPLE);
    expect(parsed).toMatchObject(SPEC_EXAMPLE);
    expect(parsed.account).toEqual({
      has_login: null,
      has_signup: null,
      has_profile: null,
      has_addresses: null,
      has_order_history: null,
    });
    expect(parsed.checkout).toEqual({
      has_guest_checkout: null,
      payment_methods: [],
      has_discount_code: null,
      shipping_options: [],
    });
  });

  it('defaults to nulls and empty lists', () => {
    const parsed = capabilitiesSchema.parse({});
    expect(parsed.version).toBe('0.2');
    expect(parsed.shop).toEqual({ descriptor: null, category: null, currency: null, tone: [] });
    expect(parsed.info_pages_present).toEqual([]);
  });

  it('rejects unknown top-level and nested fields by name', () => {
    expect(() => parseCapabilities({ bogus: 1 })).toThrow(/bogus/);
    expect(() => parseCapabilities({ cart: { has_drive_through: true } })).toThrow(
      /has_drive_through/,
    );
  });

  it('lists every top-level key including account and checkout', () => {
    expect(CAPABILITY_KEYS).toContain('account');
    expect(CAPABILITY_KEYS).toContain('checkout');
    expect(JSON.parse(capabilitiesJsonSchema()).properties).toHaveProperty('checkout');
  });
});

describe('mergeFragments', () => {
  it('returns defaults and no conflicts for an empty directory', () => {
    const { capabilities, conflicts } = mergeFragments(partsDir);
    expect(capabilities).toEqual(capabilitiesSchema.parse({}));
    expect(conflicts).toEqual([]);
  });

  it('throws when the directory is missing', () => {
    expect(() => mergeFragments(join(partsDir, 'missing'))).toThrow();
  });

  it('ignores files that are not caps fragments', () => {
    fragment('homepage.md', '# notes');
    fragment('notes.json', { cart: { type: 'page' } });
    expect(mergeFragments(partsDir).capabilities.cart.type).toBeNull();
  });

  it('combines disjoint sections', () => {
    fragment('a.caps.json', { cart: { type: 'drawer' } });
    fragment('b.caps.json', { search: { has_predictive: true } });
    const { capabilities, conflicts } = mergeFragments(partsDir);
    expect(capabilities.cart.type).toBe('drawer');
    expect(capabilities.search.has_predictive).toBe(true);
    expect(conflicts).toEqual([]);
  });

  it('unions lists in order without conflicts', () => {
    fragment('a.caps.json', { collection: { filters: ['size', 'color'] } });
    fragment('b.caps.json', { collection: { filters: ['color', 'price', 'material'] } });
    const { capabilities, conflicts } = mergeFragments(partsDir);
    expect(capabilities.collection.filters).toEqual(['size', 'color', 'price', 'material']);
    expect(conflicts).toEqual([]);
  });

  it('records a conflict for a leaf written twice with different values', () => {
    fragment('a_cart.caps.json', { cart: { type: 'drawer' } });
    fragment('b_cart.caps.json', { cart: { type: 'page' } });
    const { capabilities, conflicts } = mergeFragments(partsDir);
    expect(capabilities.cart.type).toBe('page');
    expect(conflicts).toEqual([
      {
        path: 'cart.type',
        previous_value: 'drawer',
        previous_source: 'a_cart.caps.json',
        new_value: 'page',
        new_source: 'b_cart.caps.json',
      },
    ]);
  });

  it('does not record a conflict when both fragments agree', () => {
    fragment('a.caps.json', { cart: { type: 'drawer' } });
    fragment('b.caps.json', { cart: { type: 'drawer' } });
    expect(mergeFragments(partsDir).conflicts).toEqual([]);
  });

  it('rejects an unknown field in a fragment', () => {
    fragment('a.caps.json', { bogus: true });
    expect(() => mergeFragments(partsDir)).toThrow(/bogus/);
  });

  it('names the file for malformed JSON', () => {
    fragment('broken.caps.json', '{not json');
    expect(() => mergeFragments(partsDir)).toThrow(/broken\.caps\.json is not valid JSON/);
  });

  it('names the file for a non-object fragment', () => {
    fragment('list.caps.json', [1, 2]);
    expect(() => mergeFragments(partsDir)).toThrow(
      /list\.caps\.json must be a JSON object, got array/,
    );
  });

  it('merges in filename order', () => {
    fragment('z_last.caps.json', { shop: { descriptor: 'last' } });
    fragment('a_first.caps.json', { shop: { descriptor: 'first' } });
    const { capabilities, conflicts } = mergeFragments(partsDir);
    expect(capabilities.shop.descriptor).toBe('last');
    expect(conflicts[0]).toMatchObject({
      previous_source: 'a_first.caps.json',
      new_source: 'z_last.caps.json',
    });
  });

  it('merges the full spec example cleanly', () => {
    fragment('full.caps.json', SPEC_EXAMPLE);
    const { capabilities, conflicts } = mergeFragments(partsDir);
    expect(capabilities).toMatchObject(SPEC_EXAMPLE);
    expect(conflicts).toEqual([]);
  });

  it('wraps schema failures in CapabilitiesValidationError', () => {
    fragment('a.caps.json', { site_shell: { nav_depth: 'deep' } });
    expect(() => mergeFragments(partsDir)).toThrow(CapabilitiesValidationError);
  });
});
