/**
 * Operation directives: the Storefront API `@inContext` / `@defer` pair plus
 * `@sandbox`, which marks operations and fields that have no Storefront API
 * equivalent. Everything carrying `@sandbox` exists only in this sandbox.
 */

export const directivesTypeDefs = /* GraphQL */ `
  directive @inContext(language: LanguageCode, country: CountryCode, visitorConsent: VisitorConsent) on QUERY | MUTATION
  directive @defer(if: Boolean = true, label: String) on FRAGMENT_SPREAD | INLINE_FRAGMENT

  """
  Marks a field, type, or argument that is specific to the ShopGym sandbox and
  has no counterpart in the Shopify Storefront API.
  """
  directive @sandbox(reason: String) on FIELD_DEFINITION | OBJECT | INPUT_OBJECT | ENUM | ARGUMENT_DEFINITION

  input VisitorConsent {
    marketing: Boolean
    analytics: Boolean
    preferences: Boolean
    saleOfData: Boolean
  }
`;
