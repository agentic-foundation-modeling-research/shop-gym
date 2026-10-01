/** Public surface of the `gen` module: `generateShop` plus its config, context, and step factories. */

export {
  type Allowlist,
  type BrandHit,
  brandSafetyBlock,
  findAllowlistedToken,
  isAllowedBrand,
  loadAllowlist,
  pickBrandName,
  scanBrandLeaks,
} from './brands/allowlist.js';
export {
  type CatalogSize,
  DEFAULT_MODEL,
  DEFAULT_OUTPUT_ROOT,
  GEN_STEPS,
  type GenConfig,
  type GenConfigInput,
  type GenStepName,
  genConfigSchema,
  parseGenConfig,
} from './config.js';
export { type GenContext, type GenDeps, createGenContext } from './context.js';
export * as dataSynth from './data_synth/index.js';
export { DATA_DIR, dataSynthStep } from './data_synth/index.js';
export {
  type ImageBackend,
  type ImageBackendName,
  type ImageRequest,
  createImageBackend,
} from './data_synth/images/backend.js';
export * as dataValidation from './data_validation/index.js';
export {
  DATA_VALIDATION_FILE,
  DataValidationError,
  dataValidationStep,
} from './data_validation/index.js';
export { SynthError } from './llm.js';
export * as manualMerge from './manual_merge/index.js';
export { MANUAL_DIR, manualMergeStep } from './manual_merge/index.js';
export {
  BUILD_RUN_DIR,
  BuildIncompleteError,
  FINAL_EVAL_DIR,
  type GenResult,
  buildStep,
  finalEvalStep,
  genSteps,
  generateShop,
  publishStep,
} from './pipeline.js';
