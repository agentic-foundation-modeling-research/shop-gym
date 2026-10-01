/**
 * Customer domain resolvers: account creation, access-token login/logout,
 * and the authenticated `customer` query with addresses and order history.
 *
 * Credentials are checked against the episode's `ShopState`, which is seeded
 * from `customers.json` (plain-text passwords; this is a sandbox). Tokens are
 * opaque strings minted by the state and resolved on every request.
 */

import type {
  CustomerAddressesArgs,
  CustomerOrdersArgs,
  MutationCustomerAccessTokenCreateArgs,
  MutationCustomerAccessTokenDeleteArgs,
  MutationCustomerCreateArgs,
  QueryCustomerArgs,
} from '../__generated__/resolvers-types.js';
import type { AddressRecord, CustomerRecord } from '../state/shop_state.js';
import { gid } from './builders.js';
import type { ResolverContext } from './index.js';
import { type OrderConnectionNode, buildOrderConnection } from './order.js';

const MIN_PASSWORD_LENGTH = 5;

// ── Node shapes ───────────────────────────────────────────────────────────

export interface MailingAddressNode {
  readonly id: string;
  readonly firstName: string | null;
  readonly lastName: string | null;
  readonly name: string | null;
  readonly company: string | null;
  readonly address1: string;
  readonly address2: string | null;
  readonly city: string;
  readonly province: string | null;
  readonly provinceCode: string | null;
  readonly country: string;
  readonly countryCodeV2: string;
  readonly zip: string;
  readonly phone: string | null;
  readonly formatted: readonly string[];
}

export interface MailingAddressConnectionNode {
  readonly nodes: readonly MailingAddressNode[];
  readonly edges: readonly { readonly node: MailingAddressNode }[];
}

export interface CustomerNode {
  readonly id: string;
  readonly email: string;
  readonly firstName: string | null;
  readonly lastName: string | null;
  readonly displayName: string;
  readonly phone: string | null;
  readonly acceptsMarketing: boolean;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly defaultAddress: MailingAddressNode | null;
  /** Internal: numeric record id used by field resolvers that need the store. */
  readonly recordId: number;
  /** Internal: all addresses, sliced by `Customer.addresses(first)`. */
  readonly addressNodes: readonly MailingAddressNode[];
}

export interface CustomerUserErrorNode {
  readonly code: 'BLANK' | 'INVALID' | 'TAKEN' | 'TOO_SHORT' | 'UNIDENTIFIED_CUSTOMER' | null;
  readonly field: readonly string[] | null;
  readonly message: string;
}

export interface CustomerAccessTokenNode {
  readonly accessToken: string;
  readonly expiresAt: string;
}

// ── Builders ──────────────────────────────────────────────────────────────

export function buildMailingAddressNode(address: AddressRecord): MailingAddressNode {
  const name = [address.firstName, address.lastName].filter((p) => p !== null).join(' ');
  const cityLine = [address.city, address.provinceCode ?? address.province, address.zip]
    .filter((p) => p !== null && p !== '')
    .join(' ');
  const formatted = [
    name,
    address.company,
    address.address1,
    address.address2,
    cityLine,
    address.country,
  ].filter((line): line is string => line !== null && line !== '');
  return {
    id: gid('MailingAddress', address.id),
    firstName: address.firstName,
    lastName: address.lastName,
    name: name === '' ? null : name,
    company: address.company,
    address1: address.address1,
    address2: address.address2,
    city: address.city,
    province: address.province,
    provinceCode: address.provinceCode,
    country: address.country,
    countryCodeV2: address.countryCode,
    zip: address.zip,
    phone: address.phone,
    formatted,
  };
}

export function buildCustomerNode(customer: CustomerRecord): CustomerNode {
  const addressNodes = customer.addresses.map(buildMailingAddressNode);
  const defaultAddress = customer.addresses.find((a) => a.id === customer.defaultAddressId);
  const displayName =
    [customer.firstName, customer.lastName].filter((p) => p !== null).join(' ') || customer.email;
  return {
    id: gid('Customer', customer.id),
    email: customer.email,
    firstName: customer.firstName,
    lastName: customer.lastName,
    displayName,
    phone: customer.phone,
    acceptsMarketing: customer.acceptsMarketing,
    createdAt: customer.createdAt,
    updatedAt: customer.updatedAt,
    defaultAddress: defaultAddress === undefined ? null : buildMailingAddressNode(defaultAddress),
    recordId: customer.id,
    addressNodes,
  };
}

// ── Resolvers ─────────────────────────────────────────────────────────────

export const customerResolvers = {
  Query: {
    customer: (
      _parent: unknown,
      args: QueryCustomerArgs,
      ctx: ResolverContext,
    ): CustomerNode | null => {
      const customer = ctx.state.resolveSession(args.customerAccessToken);
      return customer === undefined ? null : buildCustomerNode(customer);
    },
  },

  Mutation: {
    customerCreate: (
      _parent: unknown,
      args: MutationCustomerCreateArgs,
      ctx: ResolverContext,
    ): { customer: CustomerNode | null; customerUserErrors: readonly CustomerUserErrorNode[] } => {
      const { input } = args;
      const errors: CustomerUserErrorNode[] = [];
      const email = input.email.trim();
      if (email === '') {
        errors.push({ code: 'BLANK', field: ['input', 'email'], message: "Email can't be blank" });
      } else if (ctx.state.findCustomerByEmail(email) !== undefined) {
        errors.push({
          code: 'TAKEN',
          field: ['input', 'email'],
          message: 'Email has already been taken',
        });
      }
      if (input.password.length < MIN_PASSWORD_LENGTH) {
        errors.push({
          code: 'TOO_SHORT',
          field: ['input', 'password'],
          message: `Password is too short (minimum is ${MIN_PASSWORD_LENGTH} characters)`,
        });
      }
      if (errors.length > 0) return { customer: null, customerUserErrors: errors };
      const customer = ctx.state.createCustomer({
        email,
        password: input.password,
        firstName: input.firstName ?? null,
        lastName: input.lastName ?? null,
        phone: input.phone ?? null,
        acceptsMarketing: input.acceptsMarketing ?? false,
      });
      return { customer: buildCustomerNode(customer), customerUserErrors: [] };
    },

    customerAccessTokenCreate: (
      _parent: unknown,
      args: MutationCustomerAccessTokenCreateArgs,
      ctx: ResolverContext,
    ): {
      customerAccessToken: CustomerAccessTokenNode | null;
      customerUserErrors: readonly CustomerUserErrorNode[];
    } => {
      const customer = ctx.state.findCustomerByEmail(args.input.email);
      if (customer === undefined || customer.password !== args.input.password) {
        return {
          customerAccessToken: null,
          customerUserErrors: [
            {
              code: 'UNIDENTIFIED_CUSTOMER',
              field: null,
              message: 'Unidentified customer',
            },
          ],
        };
      }
      const session = ctx.state.createSession(customer.id);
      return {
        customerAccessToken: { accessToken: session.accessToken, expiresAt: session.expiresAt },
        customerUserErrors: [],
      };
    },

    customerAccessTokenDelete: (
      _parent: unknown,
      args: MutationCustomerAccessTokenDeleteArgs,
      ctx: ResolverContext,
    ): {
      deletedAccessToken: string | null;
      deletedCustomerAccessTokenId: string | null;
      userErrors: readonly { field: readonly string[] | null; message: string }[];
    } => {
      const session = ctx.state.deleteSession(args.customerAccessToken);
      if (session === undefined) {
        return {
          deletedAccessToken: null,
          deletedCustomerAccessTokenId: null,
          userErrors: [{ field: ['customerAccessToken'], message: 'Access token is invalid' }],
        };
      }
      return {
        deletedAccessToken: session.accessToken,
        deletedCustomerAccessTokenId: gid('CustomerAccessToken', session.accessToken),
        userErrors: [],
      };
    },
  },

  Customer: {
    addresses: (
      parent: CustomerNode,
      args: CustomerAddressesArgs,
    ): MailingAddressConnectionNode => {
      const slice = sliceFirst(parent.addressNodes, args.first);
      return { nodes: slice, edges: slice.map((node) => ({ node })) };
    },
    numberOfOrders: (parent: CustomerNode, _args: unknown, ctx: ResolverContext): number =>
      ctx.state.ordersForCustomer(parent.recordId).length,
    orders: (
      parent: CustomerNode,
      args: CustomerOrdersArgs,
      ctx: ResolverContext,
    ): OrderConnectionNode =>
      buildOrderConnection(ctx.state.ordersForCustomer(parent.recordId), args, ctx),
  },
};

/** First `first` items, or all of them when `first` is null or negative. */
export function sliceFirst<T>(items: readonly T[], first: number | null | undefined): readonly T[] {
  if (first === null || first === undefined || first < 0) return items;
  return items.slice(0, first);
}
