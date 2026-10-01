/**
 * The build-loop verifier set. `buildVerifiers` returns the ordered list the
 * harness dispatches after each executor iteration; storefront verifiers
 * (`routes_200`, `nav_coverage`, `visual_judge`) are added by the pipeline
 * that wires the storefront template (M7).
 */

import type { Verifier } from '@shop-gym/harness';

import type { BackendSidecar } from '../sidecar.js';
import { backendTestVerifier, backendTypecheckVerifier } from './backend_commands.js';
import { type SchemaIntrospector, dataInUseVerifier, introspectSidecar } from './data_in_use.js';
import type { OwnedFilesVerifier } from './owned_files.js';
import { sandboxContractVerifier } from './sandbox_contract.js';
import type { CommandRunner } from './subprocess.js';

export interface BuildVerifierOptions {
  readonly genBackend: boolean;
  readonly sidecar: BackendSidecar;
  readonly ownedFiles: OwnedFilesVerifier;
  readonly runner?: CommandRunner;
  /** Overrides introspection of the sidecar; tests build the schema in-process. */
  readonly introspect?: SchemaIntrospector;
}

/** Ordered verifier list: ownership, backend health, then schema use. */
export function buildVerifiers(options: BuildVerifierOptions): Verifier[] {
  const verifiers: Verifier[] = [options.ownedFiles];
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
      beforeIntrospect: () => options.sidecar.restartIfChanged(),
    }),
  );
  return verifiers;
}

export {
  BACKEND_DIRNAME,
  backendCommandVerifier,
  backendTestVerifier,
  backendTypecheckVerifier,
} from './backend_commands.js';
export {
  DATA_IN_USE_NAME,
  type OperationProblem,
  type SchemaIntrospector,
  dataInUseVerifier,
  extractGraphqlBlocks,
  introspectSidecar,
  validateBlocks,
} from './data_in_use.js';
export { OWNED_FILES_NAME, OwnedFilesVerifier } from './owned_files.js';
export {
  READ_ONLY_BACKEND_GLOBS,
  type ReadOnlyDrift,
  SANDBOX_CONTRACT_NAME,
  readOnlyDrift,
  sandboxContractVerifier,
} from './sandbox_contract.js';
export {
  type CommandOptions,
  type CommandResult,
  type CommandRunner,
  renderCommandFailure,
  runCommand,
  truncateStream,
} from './subprocess.js';
export { isBackendTask } from './tasks.js';
