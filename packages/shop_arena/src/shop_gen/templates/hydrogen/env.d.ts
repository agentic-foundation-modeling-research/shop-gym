/// <reference types="vite/client" />
/// <reference types="react-router" />
/// <reference types="@shopify/hydrogen/react-router-types" />

// Enhance TypeScript's built-in typings.
// Enhance TypeScript's built-in typings.
import '@total-typescript/ts-reset';

// Augment the global `Env` interface (declared by
// `@shopify/hydrogen/react-router-types` as `interface Env extends HydrogenEnv {}`)
// with template-owned environment variables. Optional because legacy artifacts
// may not set the variable; the loader applies a `'footer'` default at read time.
declare global {
  interface Env {
    /**
     * Comma-separated list of Storefront API menu handles to load as footer
     * column menus. Read in `app/root.tsx`'s deferred loader. Defaults to
     * `'footer'` (the single legacy handle) when unset or empty.
     */
    PUBLIC_FOOTER_MENU_HANDLES?: string;
  }
}

export {};
