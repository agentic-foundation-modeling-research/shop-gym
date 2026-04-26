import type { GraphQLObjectType } from 'graphql';
import { describe, expect, it } from 'vitest';
import { createSandboxSchema } from './schema.js';

describe('createSandboxSchema', () => {
  it('builds a non-null GraphQLSchema with the storefront Query surface', () => {
    const schema = createSandboxSchema();
    expect(schema).not.toBeNull();

    const queryType = schema.getQueryType();
    expect(queryType).toBeDefined();

    // Query.shop is the canonical sentinel for the storefront subset.
    const fields = (queryType as GraphQLObjectType).getFields();
    expect(fields.shop).toBeDefined();
    expect(String(fields.shop?.type)).toBe('Shop!');

    // A handful of other top-level queries should also be wired.
    for (const name of [
      'product',
      'products',
      'collection',
      'collections',
      'menu',
      'page',
      'blog',
      'blogs',
      'search',
      'predictiveSearch',
      'productRecommendations',
      'localization',
      'cart',
    ]) {
      expect(fields[name], `Query.${name} missing`).toBeDefined();
    }
  });

  it('exposes the cart mutations from the v0.1 surface', () => {
    const schema = createSandboxSchema();
    const mutationType = schema.getMutationType();
    expect(mutationType).toBeDefined();

    const fields = (mutationType as GraphQLObjectType).getFields();
    for (const name of [
      'cartCreate',
      'cartLinesAdd',
      'cartLinesUpdate',
      'cartLinesRemove',
      'cartDiscountCodesUpdate',
      'cartBuyerIdentityUpdate',
      'cartNoteUpdate',
      'cartAttributesUpdate',
      'cartGiftCardCodesUpdate',
    ]) {
      expect(fields[name], `Mutation.${name} missing`).toBeDefined();
    }
  });
});
