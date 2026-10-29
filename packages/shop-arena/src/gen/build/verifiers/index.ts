/**
 * The build-loop verifier set. `buildVerifiers` returns the ordered list
 * the harness dispatches after every executor iteration: `owned_files`
 * first, then the storefront verifiers (`typecheck`, `build`,
 * `routes_200`), the backend verifiers when `genBackend`, `data_in_use`,
 * and the storefront checks that need a served tree (`nav_coverage`,
 * `cart_conformance`, `visual_judge`). Each verifier decides per task
 * whether it applies, so the order only matters within one task's set.
 */

import type { LlmClient, ModelRef } from '@shop-gym/agent';
import type { Verifier } from '@shop-gym/harness';

import type { BackendSidecar } from '../sidecar.js';
import type { StorefrontSidecar } from '../storefront_sidecar.js';
import { backendTestVerifier, backendTypecheckVerifier } from './backend_commands.js';
import { cartConformanceVerifier } from './cart_conformance.js';
import { type SchemaIntrospector, dataInUseVerifier, introspectSidecar } from './data_in_use.js';
import { navCoverageVerifier } from './nav_coverage.js';
import type { OwnedFilesVerifier } from './owned_files.js';
import { routes200Verifier } from './routes_200.js';
import { sandboxContractVerifier } from './sandbox_contract.js';
import { storefrontBuildVerifier, storefrontTypecheckVerifier } from './storefront_commands.js';
import type { StorefrontTarget } from './storefront_target.js';
import type { CommandRunner } from './subprocess.js';
import { visualJudgeVerifier } from './visual_judge.js';

/** The LLM behind `visual_judge`. */
export interface StorefrontJudge {
  readonly llm: LlmClient;
  readonly model: ModelRef;
}

export interface StorefrontVerifierOptions {
  readonly sidecar: StorefrontSidecar;
  /** The dataset the sidecars serve (`artifact/data`). */
  readonly dataDir: string;
  /** Holds `capabilities.json` and `parts/*.md` for the visual judge. */
  readonly manualDir?: string;
  /** The visual judge; omitted means no `visual_judge` verifier. */
  readonly judge?: StorefrontJudge;
}

export interface BuildVerifierOptions {
  readonly genBackend: boolean;
  readonly sidecar: BackendSidecar;
  readonly ownedFiles: OwnedFilesVerifier;
  readonly runner?: CommandRunner;
  readonly introspect?: SchemaIntrospector;
  /** Storefront verifiers; omitted means only `owned_files`, the backend set and `data_in_use`. */
  readonly storefront?: StorefrontVerifierOptions;
}

/** The ordered verifier list for one build run. */
export function buildVerifiers(options: BuildVerifierOptions): Verifier[] {
  const verifiers: Verifier[] = [options.ownedFiles];
  const storefront = options.storefront;
  if (storefront !== undefined) {
    verifiers.push(
      storefrontTypecheckVerifier(options.runner),
      storefrontBuildVerifier(options.runner),
      routes200Verifier({
        target: storefrontTarget(storefront, options.sidecar),
        dataDir: storefront.dataDir,
      }),
    );
  }
  if (options.genBackend) {
    verifiers.push(
      backendTypecheckVerifier(options.runner),
      backendTestVerifier(options.runner),
      sandboxContractVerifier(options.runner),
    );
  }
  verifiers.push(
    dataInUseVerifier({
      introspect: options.introspect ?? introspectSidecar(options.sidecar.url),
      beforeIntrospect: () => options.sidecar.ensureCurrent(),
    }),
  );
  if (storefront !== undefined) {
    const target = storefrontTarget(storefront, options.sidecar);
    verifiers.push(
      navCoverageVerifier({ target, dataDir: storefront.dataDir }),
      cartConformanceVerifier({
        target,
        backendUrl: options.sidecar.url,
        dataDir: storefront.dataDir,
      }),
    );
    if (storefront.judge !== undefined) {
      verifiers.push(
        visualJudgeVerifier({
          target,
          dataDir: storefront.dataDir,
          llm: storefront.judge.llm,
          model: storefront.judge.model,
          ...(storefront.manualDir !== undefined ? { manualDir: storefront.manualDir } : {}),
        }),
      );
    }
  }
  return verifiers;
}

/**
 * Point the HTTP verifiers at the storefront sidecar. Before each check, bring
 * the backend it renders from up to date, then start or rebuild the storefront.
 */
function storefrontTarget(
  options: StorefrontVerifierOptions,
  backend: BackendSidecar,
): StorefrontTarget {
  return {
    url: options.sidecar.url,
    prepare: async () => {
      await backend.ensureCurrent();
      await options.sidecar.ensureCurrent();
    },
  };
}

export {
  BACKEND_DIRNAME,
  type BackendCommandVerifierOptions,
  backendCommandVerifier,
  backendTestVerifier,
  backendTypecheckVerifier,
} from './backend_commands.js';
export {
  CART_CONFORMANCE_NAME,
  type CartConformanceOptions,
  type CartStep,
  cartConformanceVerifier,
  formatMoney,
} from './cart_conformance.js';
export {
  DATA_IN_USE_NAME,
  type DataInUseOptions,
  type OperationProblem,
  type SchemaIntrospector,
  dataInUseVerifier,
  extractGraphqlBlocks,
  introspectSidecar,
  validateBlocks,
} from './data_in_use.js';
export { type HttpResult, StorefrontClient, type StorefrontClientOptions } from './http.js';
export {
  type MenuTarget,
  type MenuTargetCheck,
  NAV_COVERAGE_NAME,
  type NavCoverageOptions,
  navCoverageVerifier,
  readMenuTargets,
} from './nav_coverage.js';
export { OWNED_FILES_NAME, OwnedFilesVerifier } from './owned_files.js';
export {
  type CapturePageOptions,
  JUDGE_VIEWPORTS,
  type JudgeContext,
  type JudgePageOptions,
  PASS_SCORE,
  type PageCapture,
  type PageJudgement,
  type PageScreenshot,
  type PageVerdict,
  RUBRIC_PATH,
  type Viewport,
  type ViewportName,
  capturePage,
  coerceVerdict,
  judgeContext,
  judgePage,
  loadJudgeRubric,
  mapConcurrent,
  pageVerdictSchema,
  routeSlug,
} from './page_judge.js';
export {
  ROUTES_200_NAME,
  type RouteProbe,
  type Routes200Options,
  internalLinks,
  routes200Verifier,
} from './routes_200.js';
export {
  READ_ONLY_BACKEND_GLOBS,
  type ReadOnlyDrift,
  SANDBOX_CONTRACT_NAME,
  readOnlyDrift,
  sandboxContractVerifier,
} from './sandbox_contract.js';
export {
  STOREFRONT_DIRNAME,
  type StorefrontCommandVerifierOptions,
  storefrontBuildVerifier,
  storefrontCommandVerifier,
  storefrontTypecheckVerifier,
} from './storefront_commands.js';
export {
  CHECKOUT_ADDRESS,
  type CheckoutMethods,
  type SeededCustomer,
  type StorefrontTarget,
  prepareTarget,
  readCheckoutMethods,
  readSeededCustomer,
} from './storefront_target.js';
export {
  type CommandOptions,
  type CommandResult,
  type CommandRunner,
  renderCommandFailure,
  runCommand,
  truncateStream,
} from './subprocess.js';
export {
  ALL_BUCKETS,
  type BucketCaps,
  DEFAULT_CAPS,
  type DatasetHandles,
  type PageBucket,
  SWEEP_CAPS,
  TASK_BUCKETS,
  bucketRoutes,
  bucketsForTask,
  isStorefrontTask,
  readDatasetHandles,
  routesForBuckets,
  sampleProductHandles,
  searchToken,
} from './task_routes.js';
export { isBackendTask } from './tasks.js';
export {
  type RetryBudgetState,
  VISUAL_BUDGET_FILE,
  VISUAL_JUDGE_NAME,
  VISUAL_RETRY_BUDGET,
  type VisualJudgeOptions,
  visualJudgeVerifier,
} from './visual_judge.js';
