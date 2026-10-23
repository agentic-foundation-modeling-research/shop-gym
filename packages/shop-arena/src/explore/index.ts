/**
 * Storefront exploration: prefetch, harness-driven browsing, capability
 * merge, and shop manual synthesis.
 */

export {
  type Leak,
  type LeakScanner,
  anonymizationVerifier,
  brandTokens,
  formatLeaks,
  leakScanner,
  scanParts,
} from './anonymization.js';
export {
  CAPABILITY_KEYS,
  type Capabilities,
  CapabilitiesValidationError,
  type Conflict,
  type MergeResult,
  capabilitiesJsonSchema,
  capabilitiesSchema,
  mergeFragments,
  parseCapabilities,
} from './capabilities.js';
export { coverageGaps, evidencedAreas, parsePlanCoverage } from './coverage.js';
export { fileTools } from './files.js';
export {
  DEFAULT_MAX_ITERS,
  DEFAULT_MODEL,
  DEFAULT_OUTPUT_ROOT,
  DEFAULT_TIMEOUT_MS,
  EXPLORE_STEPS,
  type ExploreOptions,
  type ExploreOutcome,
  type ExploreResult,
  type ExploreStep,
  type Manifest,
  exploreStorefront,
  parseModel,
  runId,
} from './pipeline.js';
export {
  type PrefetchEntry,
  type PrefetchOptions,
  type PrefetchReport,
  ShopUnreachableError,
  type UnreachableReason,
  normalizeBase,
  prefetch,
  robotsDisallowsRoot,
} from './prefetch.js';
export { type Stats, computeStats } from './stats.js';
export {
  MANUAL_MIN_CHARS,
  ManualRenderError,
  buildManualPrompt,
  concatParts,
  renderManual,
} from './synthesize.js';
