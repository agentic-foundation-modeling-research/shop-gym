/** Build loop public API: seeding, sidecar, prompts, owned files, checkpoints, verifiers, loop. */

export {
  BUILD_JSON,
  type BuildLoopOptions,
  type BuildLoopResult,
  type BuildRunInfo,
  CHECKPOINTS_DIRNAME,
  DATA_DIRNAME,
  MANUAL_DIRNAME,
  SIDECAR_LOG,
  STOREFRONT_LOG,
  readBuildInfo,
  runBuildLoop,
} from './build_loop.js';
export {
  ArtifactCheckpoints,
  type ArtifactCheckpointsOptions,
  CheckpointError,
} from './checkpoints.js';
export {
  type OwnedFileOptions,
  type OwnedFileViolation,
  PROTECTED_GLOBS,
  type ViolationKind,
  globToRegExp,
  ownedFileViolations,
} from './owned_files.js';
export {
  type BuildPromptValues,
  type BuildPrompts,
  PromptError,
  loadBuildPrompts,
  renderPlaceholders,
} from './prompts.js';
export {
  SeedError,
  type SeedTemplateOptions,
  TEMPLATE_JSON,
  type TemplateFingerprint,
  defaultBackendTemplateDir,
  listTrackedFiles,
  seedBackend,
  seedTemplate,
  templateFingerprint,
} from './seed.js';
export {
  BackendSidecar,
  type BackendSidecarOptions,
  SidecarError,
  type SidecarLaunch,
  type SidecarLaunchOptions,
  type SidecarProcess,
  freePort,
  spawnSidecar,
} from './sidecar.js';
export {
  type StorefrontLaunch,
  type StorefrontLaunchOptions,
  StorefrontSidecar,
  type StorefrontSidecarOptions,
  launchWithRunner,
  spawnStorefront,
} from './storefront_sidecar.js';
export { type TreeSnapshot, diffTrees, hashSnapshot, snapshotTree } from './tree.js';
export * from './verifiers/index.js';
