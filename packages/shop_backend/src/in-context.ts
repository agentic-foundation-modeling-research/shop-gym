/**
 * `@inContext` directive enforcement (T7.3, spec §5.3).
 *
 * The Storefront API exposes an `@inContext(country:, language:, visitorConsent:)`
 * directive on `QUERY` / `MUTATION` operations. v0.1 parsed it but ignored
 * the args (the dataset is single-locale). v0.2 validates the args against
 * `Query.localization` so a request that asks for an unsupported country or
 * language fails fast instead of returning misleading single-locale data.
 *
 * The supported locale is derived from the loaded dataset:
 *
 *   - `country` → `Store.country_code` (single supported value).
 *   - `language` → `EN` (the static default returned by `Query.localization`;
 *     spec §5.2 keeps the dataset English-only).
 *
 * `visitorConsent` is accepted without validation — it's metadata about
 * tracking preferences, not a locale.
 *
 * On mismatch, the rule reports a `GraphQLError` with `extensions.code =
 * "UNSUPPORTED_LOCALE"`. Validation errors abort execution per the GraphQL
 * spec — the response carries no `data` field and the error in `errors[]`,
 * matching the "return null/UnsupportedLocale for mismatches" contract in
 * the implementation plan check for T7.3.
 */

import { type ASTVisitor, GraphQLError, type ValidationContext } from 'graphql';
import type { Plugin } from 'graphql-yoga';
import type { SandboxShopData } from './data/types.js';

/**
 * Default language served by `Query.localization`. The dataset is single-
 * locale (spec §5.2), so any other code is rejected.
 */
const DEFAULT_LANGUAGE = 'EN';

const IN_CONTEXT_DIRECTIVE = 'inContext';

const UNSUPPORTED_LOCALE_CODE = 'UNSUPPORTED_LOCALE';

/**
 * Build a GraphQL validation rule that rejects `@inContext` directives whose
 * `country` or `language` argument does not match the dataset locale.
 *
 * The rule visits every `OperationDefinition` (the only allowed location for
 * `@inContext` per the SDL) and inspects each `inContext` directive on it.
 * Arguments expressed as enum literals are checked against the dataset; any
 * other argument shape (variable references, missing args, `visitorConsent`)
 * is left alone so existing valid queries keep passing.
 */
export function createInContextValidationRule(
  data: SandboxShopData,
): (context: ValidationContext) => ASTVisitor {
  const supportedCountry = data.store.country_code;
  return (context) => ({
    OperationDefinition(operation) {
      for (const directive of operation.directives ?? []) {
        if (directive.name.value !== IN_CONTEXT_DIRECTIVE) continue;
        for (const arg of directive.arguments ?? []) {
          if (arg.value.kind !== 'EnumValue') continue;
          const argName = arg.name.value;
          const argValue = arg.value.value;
          if (argName === 'country' && argValue !== supportedCountry) {
            context.reportError(
              new GraphQLError(
                `@inContext country "${argValue}" is not supported by this SandboxShop; only "${supportedCountry}" is available.`,
                { nodes: [arg], extensions: { code: UNSUPPORTED_LOCALE_CODE } },
              ),
            );
          } else if (argName === 'language' && argValue !== DEFAULT_LANGUAGE) {
            context.reportError(
              new GraphQLError(
                `@inContext language "${argValue}" is not supported by this SandboxShop; only "${DEFAULT_LANGUAGE}" is available.`,
                { nodes: [arg], extensions: { code: UNSUPPORTED_LOCALE_CODE } },
              ),
            );
          }
        }
      }
    },
  });
}

/**
 * graphql-yoga plugin that registers the `@inContext` validation rule so
 * unsupported-locale operations are rejected at validation time.
 *
 * Runs once per server (the rule closes over the dataset's
 * `country_code`); `createSandboxServer` wires this in alongside the SDL.
 */
export function createInContextValidationPlugin(data: SandboxShopData): Plugin {
  const rule = createInContextValidationRule(data);
  return {
    onValidate({ addValidationRule }) {
      addValidationRule(rule);
    },
  };
}
