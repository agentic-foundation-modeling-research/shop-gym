/**
 * Subprocess seam shared by the command-backed verifiers and template
 * seeding. Production code uses `runCommand`; tests inject a fake runner.
 */

import { type ExecFileException, execFile } from 'node:child_process';

export interface CommandResult {
  /** `null` when the process was killed (timeout). */
  readonly exitCode: number | null;
  readonly stdout: string;
  readonly stderr: string;
  readonly timedOut: boolean;
}

export interface CommandOptions {
  readonly cwd: string;
  readonly timeoutMs: number;
  /** Variables set on top of the inherited environment. */
  readonly env?: Readonly<Record<string, string>>;
}

export type CommandRunner = (
  argv: readonly string[],
  options: CommandOptions,
) => Promise<CommandResult>;

const MAX_BUFFER_BYTES = 16 * 1024 * 1024;

/** Run `argv[0]` with the remaining arguments; never throws on a non-zero exit. */
export const runCommand: CommandRunner = (argv, options) => {
  const [command, ...args] = argv;
  if (command === undefined) {
    throw new Error('runCommand: empty argv');
  }
  return new Promise((resolve) => {
    execFile(
      command,
      args,
      {
        cwd: options.cwd,
        timeout: options.timeoutMs,
        killSignal: 'SIGKILL',
        maxBuffer: MAX_BUFFER_BYTES,
        env: { ...process.env, CI: '1', FORCE_COLOR: '0', ...options.env },
      },
      (error, stdout, stderr) => {
        if (error === null) {
          resolve({ exitCode: 0, stdout, stderr, timedOut: false });
          return;
        }
        const failure: ExecFileException = error;
        const timedOut = failure.killed === true && failure.signal === 'SIGKILL';
        const exitCode = typeof failure.code === 'number' ? failure.code : null;
        const detail = exitCode === null && !timedOut ? `${stderr}\n${failure.message}` : stderr;
        resolve({ exitCode, stdout, stderr: detail, timedOut });
      },
    );
  });
};

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
