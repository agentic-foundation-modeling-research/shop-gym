/**
 * ShopArena public API.
 *
 * Modules are added per milestone: `explore/` (M8), `gen/build/` (M5),
 * `gen/` pipeline (M7). Each module re-exports from here once it lands.
 */
export * as build from './gen/build/index.js';
export * as finalEval from './gen/final_eval/index.js';
export * as publish from './gen/publish/index.js';
export { STOREFRONT_TEMPLATE_DIR } from './templates.js';
export * from './explore/index.js';
