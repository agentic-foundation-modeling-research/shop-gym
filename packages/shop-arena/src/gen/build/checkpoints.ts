/**
 * Git checkpoints of a build run's `artifact/` tree.
 *
 * The repository is bare and sits beside the tree, so the agent's file
 * tools and the published shop never see it. The build loop commits after
 * seeding and after each iteration the harness keeps, and rolls an
 * abandoned iteration back to the last commit, so `changedPaths()` is what
 * the current iteration changed.
 *
 * Dependencies, build outputs, the caller's `untrackedDirs` and paths the
 * tree's own `.gitignore` files exclude are not tracked, and a rollback
 * leaves them in place. Git runs without the user's global and system
 * config, so hooks, signing and excludes set there do not apply.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { DEFAULT_IGNORED_DIRS } from './tree.js';
import { type CommandRunner, argvLabel, runCommand } from './verifiers/subprocess.js';

const GIT_TIMEOUT_MS = 120_000;
const GIT_ENV: Readonly<Record<string, string>> = {
  GIT_CONFIG_GLOBAL: '/dev/null',
  GIT_CONFIG_NOSYSTEM: '1',
  GIT_AUTHOR_NAME: 'shopgym',
  GIT_AUTHOR_EMAIL: 'shopgym@localhost',
  GIT_COMMITTER_NAME: 'shopgym',
  GIT_COMMITTER_EMAIL: 'shopgym@localhost',
};

export class CheckpointError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CheckpointError';
  }
}

export interface ArtifactCheckpointsOptions {
  /** The bare repository, created by `open()` on first use. */
  readonly gitDir: string;
  /** The checkpointed tree. */
  readonly workTree: string;
  /** Top-level directories of `workTree` that are not tracked, e.g. an immutable seed. */
  readonly untrackedDirs?: readonly string[];
  /** Test seam for `git`. */
  readonly runner?: CommandRunner;
}

export class ArtifactCheckpoints {
  private readonly runner: CommandRunner;

  constructor(private readonly options: ArtifactCheckpointsOptions) {
    this.runner = options.runner ?? runCommand;
  }

  /**
   * Create the repository when it does not exist, then commit the tree as
   * it is. On resume this keeps whatever an interrupted iteration left, as
   * the harness does, so the next iteration starts from a clean checkpoint.
   */
  async open(message: string): Promise<void> {
    const { gitDir } = this.options;
    if ((await fs.stat(gitDir).catch(() => undefined)) === undefined) {
      await this.run(['git', 'init', '--bare', '--quiet', '--initial-branch=main', gitDir]);
    }
    const excludes = [
      ...(this.options.untrackedDirs ?? []).map((dir) => `/${dir}/`),
      ...DEFAULT_IGNORED_DIRS.map((dir) => `${dir}/`),
    ];
    await fs.mkdir(path.join(gitDir, 'info'), { recursive: true });
    await fs.writeFile(path.join(gitDir, 'info', 'exclude'), `${excludes.join('\n')}\n`);
    await this.commit(message);
  }

  /** Commit every tracked change, also when there is none. */
  async commit(message: string): Promise<void> {
    await this.git(['add', '--all']);
    await this.git(['commit', '--quiet', '--allow-empty', '--no-verify', '-m', message]);
  }

  /** Restore the last commit: undo edits and deletions, and remove new files. */
  async rollback(): Promise<void> {
    await this.git(['reset', '--hard', '--quiet', 'HEAD']);
    await this.git(['clean', '-d', '--force', '--quiet']);
  }

  /** Sorted tree-relative POSIX paths added, removed or modified since the last commit. */
  async changedPaths(): Promise<string[]> {
    const status = await this.git([
      'status',
      '--porcelain=v1',
      '-z',
      '--untracked-files=all',
      '--no-renames',
    ]);
    // Each entry is "XY <path>"; -z leaves paths unquoted.
    return status
      .split('\0')
      .filter((entry) => entry !== '')
      .map((entry) => entry.slice(3))
      .sort();
  }

  private git(args: readonly string[]): Promise<string> {
    const { gitDir, workTree } = this.options;
    return this.run(['git', `--git-dir=${gitDir}`, `--work-tree=${workTree}`, ...args]);
  }

  /** @throws CheckpointError when the command exits non-zero. */
  private async run(argv: readonly string[]): Promise<string> {
    const result = await this.runner(argv, {
      cwd: this.options.workTree,
      timeoutMs: GIT_TIMEOUT_MS,
      env: GIT_ENV,
    });
    if (result.exitCode !== 0) {
      const reason = result.timedOut ? 'timed out' : result.stderr.trim();
      throw new CheckpointError(`${argvLabel(argv)} failed: ${reason}`);
    }
    return result.stdout;
  }
}
