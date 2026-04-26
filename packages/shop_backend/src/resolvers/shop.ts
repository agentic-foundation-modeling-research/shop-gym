/**
 * Resolvers for the Shop / Menu / Localization areas of the Storefront API.
 *
 * Covers the surface enumerated in
 * `docs/specs/shop_backend/storefront_api.md` §5.2:
 *
 *   - `Query.shop` — derives the Shop node from `store.json`.
 *   - `Query.menu(handle)` — looks up a navigation handle in `navigation.json`,
 *     returns `null` when absent.
 *   - `Query.localization` — single country/language pair derived from
 *     `store.country_code` / `store.currency_code`.
 *   - `Shop.privacyPolicy` / `shippingPolicy` / `termsOfService` /
 *     `refundPolicy` / `subscriptionPolicy` — each looks up its handle in
 *     `policies.json` and returns `null` when the policy is absent.
 *
 * Pure: every resolver is a function from `(parent, args, ctx)` to a typed
 * plain object. Strict-mode types throughout (no `any`); brand colors and
 * payment settings come from the dataset, not from mock-api hardcodes.
 */

import type { QueryMenuArgs } from '../__generated__/resolvers-types.js';
import type { Policy, SandboxShopData, Store } from '../data/types.js';
import {
  type MenuItemNode,
  type ShopPolicyNode,
  buildMenuItemNode,
  buildPolicyNode,
  gid,
} from './builders.js';
import type { ResolverContext } from './index.js';

// ── Node shapes ────────────────────────────────────────────────────────────
// Argument types are imported from the generated resolver types module above;
// the hand-typed parent shapes below remain because codegen mappers are
// deferred (see `codegen.ts`).

export interface ShopParentNode {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly primaryDomain: ShopDomainNode;
  readonly brand: BrandNode;
  readonly paymentSettings: PaymentSettingsNode;
}

export interface ShopDomainNode {
  readonly url: string;
  readonly host: string;
}

export interface BrandNode {
  readonly logo: MediaImageNode | null;
  readonly colors: BrandColorsNode;
  readonly coverImage: MediaImageNode | null;
  readonly shortDescription: string | null;
}

export interface BrandColorsNode {
  readonly primary: readonly BrandColorGroupNode[];
}

export interface BrandColorGroupNode {
  readonly background: string;
  readonly foreground: string;
}

export interface MediaImageNode {
  readonly image: MediaImageImageNode;
  readonly previewImage: MediaImageImageNode;
}

export interface MediaImageImageNode {
  readonly url: string;
  readonly altText: string | null;
}

export interface PaymentSettingsNode {
  readonly currencyCode: string;
  readonly acceptedCardBrands: readonly string[];
  readonly countryCode: string;
}

export interface MenuNode {
  readonly id: string;
  readonly handle: string;
  readonly title: string;
  readonly items: readonly MenuItemNode[];
}

export interface LocalizationNode {
  readonly country: LocalizationCountryNode;
  readonly language: LanguageNode;
  readonly availableCountries: readonly CountryNode[];
  readonly availableLanguages: readonly LanguageNode[];
}

export interface LocalizationCountryNode {
  readonly isoCode: string;
  readonly name: string;
  readonly currency: CurrencyNode;
}

export interface CountryNode {
  readonly isoCode: string;
  readonly name: string;
  readonly currency: CountryCurrencyNode;
  readonly availableLanguages: readonly LanguageNode[];
}

export interface CountryCurrencyNode {
  readonly isoCode: string;
}

export interface CurrencyNode {
  readonly isoCode: string;
  readonly name: string;
  readonly symbol: string;
}

export interface LanguageNode {
  readonly isoCode: string;
  readonly name: string;
}

// ── Static lookup tables ──────────────────────────────────────────────────

/**
 * Maps the SDL field name on `Shop` to the `Policy.handle` value the dataset
 * uses (per spec §8.1.1 `policies.json`).
 */
const POLICY_HANDLES = {
  privacyPolicy: 'privacy-policy',
  shippingPolicy: 'shipping-policy',
  termsOfService: 'terms-of-service',
  refundPolicy: 'refund-policy',
  subscriptionPolicy: 'subscription-policy',
} as const;

const COUNTRY_NAMES: Readonly<Record<string, string>> = {
  US: 'United States',
  CA: 'Canada',
  GB: 'United Kingdom',
  AU: 'Australia',
  DE: 'Germany',
  FR: 'France',
};

const CURRENCY_NAMES: Readonly<Record<string, string>> = {
  USD: 'US Dollar',
  CAD: 'Canadian Dollar',
  EUR: 'Euro',
  GBP: 'British Pound',
  AUD: 'Australian Dollar',
};

const CURRENCY_SYMBOLS: Readonly<Record<string, string>> = {
  USD: '$',
  CAD: '$',
  EUR: '€',
  GBP: '£',
  AUD: '$',
};

/** Single-locale dataset → English-only language list (spec §5.2). */
const DEFAULT_LANGUAGE: LanguageNode = { isoCode: 'EN', name: 'English' };

const HANDLE_SEPARATORS = /[-_]+/g;

// ── Resolvers ─────────────────────────────────────────────────────────────

/**
 * Resolver map for the Shop / Menu / Localization area. Wired into
 * `createSandboxSchema` once T2.6 combines the per-area maps.
 */
export const shopResolvers = {
  Query: {
    shop: (_parent: unknown, _args: unknown, ctx: ResolverContext): ShopParentNode =>
      buildShopNode(ctx.data.store),

    menu: (_parent: unknown, args: QueryMenuArgs, ctx: ResolverContext): MenuNode | null => {
      const items = ctx.data.navigation[args.handle];
      if (items === undefined) return null;
      return {
        id: gid('Menu', args.handle),
        handle: args.handle,
        title: humanizeHandle(args.handle),
        items: items.map(buildMenuItemNode),
      };
    },

    localization: (_parent: unknown, _args: unknown, ctx: ResolverContext): LocalizationNode =>
      buildLocalization(ctx.data.store),
  },

  Shop: {
    privacyPolicy: (_p: ShopParentNode, _a: unknown, ctx: ResolverContext): ShopPolicyNode | null =>
      resolvePolicy(ctx.data, POLICY_HANDLES.privacyPolicy),
    shippingPolicy: (
      _p: ShopParentNode,
      _a: unknown,
      ctx: ResolverContext,
    ): ShopPolicyNode | null => resolvePolicy(ctx.data, POLICY_HANDLES.shippingPolicy),
    termsOfService: (
      _p: ShopParentNode,
      _a: unknown,
      ctx: ResolverContext,
    ): ShopPolicyNode | null => resolvePolicy(ctx.data, POLICY_HANDLES.termsOfService),
    refundPolicy: (_p: ShopParentNode, _a: unknown, ctx: ResolverContext): ShopPolicyNode | null =>
      resolvePolicy(ctx.data, POLICY_HANDLES.refundPolicy),
    subscriptionPolicy: (
      _p: ShopParentNode,
      _a: unknown,
      ctx: ResolverContext,
    ): ShopPolicyNode | null => resolvePolicy(ctx.data, POLICY_HANDLES.subscriptionPolicy),
  },
};

// ── Builders ──────────────────────────────────────────────────────────────

function buildShopNode(store: Store): ShopParentNode {
  return {
    id: gid('Shop', store.shop_id),
    name: store.name,
    description: store.description,
    primaryDomain: { url: `https://${store.domain}`, host: store.domain },
    brand: buildBrand(store),
    paymentSettings: {
      currencyCode: store.currency_code,
      countryCode: store.country_code,
      acceptedCardBrands: store.payment_settings.accepted_card_brands,
    },
  };
}

function buildBrand(store: Store): BrandNode {
  const logoUrl = store.brand.logo_url;
  const logo: MediaImageNode | null =
    logoUrl === null
      ? null
      : {
          image: { url: logoUrl, altText: null },
          previewImage: { url: logoUrl, altText: null },
        };
  return {
    logo,
    colors: {
      primary: [
        {
          background: store.brand.colors.primary,
          foreground: store.brand.colors.secondary,
        },
      ],
    },
    coverImage: null,
    shortDescription: null,
  };
}

function buildLocalization(store: Store): LocalizationNode {
  const country: LocalizationCountryNode = {
    isoCode: store.country_code,
    name: countryName(store.country_code),
    currency: {
      isoCode: store.currency_code,
      name: currencyName(store.currency_code),
      symbol: currencySymbol(store.currency_code),
    },
  };
  const availableCountry: CountryNode = {
    isoCode: store.country_code,
    name: countryName(store.country_code),
    currency: { isoCode: store.currency_code },
    availableLanguages: [DEFAULT_LANGUAGE],
  };
  return {
    country,
    language: DEFAULT_LANGUAGE,
    availableCountries: [availableCountry],
    availableLanguages: [DEFAULT_LANGUAGE],
  };
}

function resolvePolicy(data: SandboxShopData, handle: string): ShopPolicyNode | null {
  const policy = findPolicy(data.policies, handle);
  return policy === null ? null : buildPolicyNode(policy, data.store);
}

function findPolicy(policies: readonly Policy[], handle: string): Policy | null {
  for (const p of policies) {
    if (p.handle === handle) return p;
  }
  return null;
}

function countryName(code: string): string {
  return COUNTRY_NAMES[code] ?? code;
}

function currencyName(code: string): string {
  return CURRENCY_NAMES[code] ?? code;
}

function currencySymbol(code: string): string {
  return CURRENCY_SYMBOLS[code] ?? code;
}

/** `main-menu` → `Main Menu`. Used as the (best-effort) `Menu.title`. */
function humanizeHandle(handle: string): string {
  return handle
    .split(HANDLE_SEPARATORS)
    .filter((part) => part !== '')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}
