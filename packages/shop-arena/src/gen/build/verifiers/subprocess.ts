/**
 * Subprocess seam shared by the command-backed verifiers and template
 * seeding. Production code uses `runCommand`; tests inject a fake runner.
 */

import { type ChildProcess, spawn } from 'node:child_process';

export interface CommandResult {
  /**
   * `null` when the command did not exit on its own: timeout, output past the
   * buffer limit, a kill signal, or a program that could not start.
   */
  readonly exitCode: number | null;
  readonly stdout: string;
  readonly stderr: string;
  readonly timedOut: boolean;
}

export interface CommandOptions {
  readonly cwd: string;
  readonly timeoutMs: number;
  /** Variables set on top of `commandEnv()`. */
  readonly env?: Readonly<Record<string, string>>;
}

/**
 * Variables that commands inherit from this process: what node, pnpm and git
 * need to find their tools, home, store, temp dir and locale, and to reach a
 * registry through a proxy or a custom CA. All others, API keys and tokens
 * above all, stay out of the agent's shell and of the code it writes.
 */
const INHERITED_ENV: ReadonlySet<string> = new Set([
  'PATH',
  'HOME',
  'USER',
  'LOGNAME',
  'SHELL',
  'TMPDIR',
  'TZ',
  'LANG',
  'PNPM_HOME',
  'XDG_CACHE_HOME',
  'XDG_CONFIG_HOME',
  'XDG_DATA_HOME',
  'HTTP_PROXY',
  'HTTPS_PROXY',
  'NO_PROXY',
  'http_proxy',
  'https_proxy',
  'no_proxy',
  'NODE_EXTRA_CA_CERTS',
  'SSL_CERT_FILE',
  'SSL_CERT_DIR',
]);
const INHERITED_ENV_PREFIX = 'LC_';

/** The environment for agent-run code: the allowlisted variables of this process, then `overrides`. */
export function commandEnv(overrides: Readonly<Record<string, string>> = {}): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const [name, value] of Object.entries(process.env)) {
    if (INHERITED_ENV.has(name) || name.startsWith(INHERITED_ENV_PREFIX)) {
      env[name] = value;
    }
  }
  return { ...env, ...overrides };
}

export type CommandRunner = (
  argv: readonly string[],
  options: CommandOptions,
) => Promise<CommandResult>;

const MAX_BUFFER_BYTES = 16 * 1024 * 1024;

/**
 * Run `argv[0]` with the remaining arguments; never throws on a non-zero exit.
 *
 * The command leads its own process group, and the whole group is killed
 * when the command exits or times out: a process it started in the
 * background (a server, a test worker) does not outlive the call or keep its
 * output open. A process that starts its own session escapes the group.
 */
export const runCommand: CommandRunner = (argv, options) => {
  const [command, ...args] = argv;
  if (command === undefined) {
    throw new Error('runCommand: empty argv');
  }
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: commandEnv({ CI: '1', FORCE_COLOR: '0', ...options.env }),
      detached: true,
    });
    const output = { stdout: '', stderr: '' };
    const bytes = { stdout: 0, stderr: 0 };
    let timedOut = false;
    let failure: string | undefined;
    const stop = (): void => {
      killGroup(child);
      child.stdout.destroy();
      child.stderr.destroy();
    };
    const timer = setTimeout(() => {
      timedOut = true;
      stop();
    }, options.timeoutMs);
    for (const name of ['stdout', 'stderr'] as const) {
      child[name].setEncoding('utf8');
      child[name].on('data', (chunk: string) => {
        output[name] += chunk;
        bytes[name] += Buffer.byteLength(chunk);
        if (bytes[name] > MAX_BUFFER_BYTES && failure === undefined) {
          failure = `${name} exceeded ${MAX_BUFFER_BYTES} bytes`;
          stop();
        }
      });
    }
    child.on('exit', () => killGroup(child));
    child.on('error', (error) => {
      failure ??= error.message;
    });
    child.on('close', (code, signal) => {
      clearTimeout(timer);
      if (code === null && !timedOut) {
        failure ??= `killed by ${signal ?? 'a signal'}`;
      }
      const exitCode = timedOut || failure !== undefined ? null : code;
      const stderr = failure === undefined ? output.stderr : `${output.stderr}\n${failure}`;
      resolve({ exitCode, stdout: output.stdout, stderr, timedOut });
    });
  });
};

/** SIGKILL every process left in the command's group. */
function killGroup(child: ChildProcess): void {
  if (child.pid === undefined) {
    return;
  }
  try {
    process.kill(-child.pid, 'SIGKILL');
  } catch (error) {
    // ESRCH: the group is already empty. EPERM: only zombies or processes
    // this user may not signal are left.
    const code = (error as NodeJS.ErrnoException).code;
    if (code !== 'ESRCH' && code !== 'EPERM') {
      throw error;
    }
  }
}

export const STREAM_LIMIT_CHARS = 1500;

/** Keep the head of a stream so feedback stays within the prompt budget. */
export function truncateStream(text: string, limit = STREAM_LIMIT_CHARS): string {
  return text.length <= limit ? text : `${text.slice(0, limit)}\n[...truncated]`;
}

/** Markdown body for a failed command: label plus fenced stdout/stderr. */
export function renderCommandFailure(label: string, result: CommandResult): string {
  const lines = [`\`${label}\` failed.`];
  if (result.stdout.trim() !== '') {
    lines.push('', 'stdout:', '```', truncateStream(result.stdout.trimEnd()), '```');
  }
  if (result.stderr.trim() !== '') {
    lines.push('', 'stderr:', '```', truncateStream(result.stderr.trimEnd()), '```');
  }
  return lines.join('\n');
}

export function argvLabel(argv: readonly string[]): string {
  return argv.join(' ');
}
