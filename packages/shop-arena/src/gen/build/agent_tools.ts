/**
 * Tools the build executor gets on top of the run-dir file tools: a shell
 * for the template copies' `pnpm` scripts and sidecar queries, and a
 * storefront screenshot that returns the same desktop and mobile captures
 * the `visual_judge` verifier scores, so the agent can see the page it is
 * styling before it marks the task done.
 */

import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import type { Tool, ToolContent, ToolResult } from '@shop-gym/agent';
import { BrowserSession } from '@shop-gym/browser';
import { Type } from '@sinclair/typebox';

import { resolveInside } from '../../explore/files.js';
import { JUDGE_VIEWPORTS, capturePage } from './verifiers/page_judge.js';
import type { StorefrontTarget } from './verifiers/storefront_target.js';
import { type CommandResult, type CommandRunner, runCommand } from './verifiers/subprocess.js';

export const RUN_COMMAND_TOOL = 'run_command';
export const SCREENSHOT_TOOL = 'screenshot_page';
const DEFAULT_COMMAND_TIMEOUT_MS = 300_000;
const MAX_COMMAND_TIMEOUT_MS = 900_000;
/** Characters of combined output returned per call; the middle is elided. */
const OUTPUT_LIMIT_CHARS = 12_000;

export interface AgentToolsOptions {
  /** The served storefront; `prepare` rebuilds it before a screenshot. */
  readonly target: StorefrontTarget;
  /** Test seam for `run_command`. */
  readonly runner?: CommandRunner;
}

/** `run_command` and `screenshot_page`, both rooted at the run directory. */
export function buildAgentTools(options: AgentToolsOptions): readonly Tool[] {
  return [runCommandTool(options.runner ?? runCommand), screenshotTool(options.target)];
}

const RUN_COMMAND_PARAMS = Type.Object({
  command: Type.String({ description: 'Shell command line, e.g. "pnpm typecheck && pnpm build".' }),
  cwd: Type.Optional(
    Type.String({
      description:
        'Working directory relative to the run directory, e.g. "artifact/storefront". Defaults to the run directory.',
    }),
  ),
  timeoutMs: Type.Optional(
    Type.Integer({
      minimum: 1000,
      maximum: MAX_COMMAND_TIMEOUT_MS,
      description: `Kill the command after this many milliseconds (default ${DEFAULT_COMMAND_TIMEOUT_MS}).`,
    }),
  ),
});

const SCREENSHOT_PARAMS = Type.Object({
  route: Type.String({
    description: 'Storefront route starting with "/", e.g. "/" or "/collections/all".',
  }),
});

export function runCommandTool(runner: CommandRunner): Tool<typeof RUN_COMMAND_PARAMS> {
  return {
    name: RUN_COMMAND_TOOL,
    description:
      'Run a shell command with `sh -c` inside the run directory and return its exit code, stdout and stderr. ' +
      'Use it for `pnpm typecheck`, `pnpm build`, `pnpm test`, `pnpm codegen` and `curl` against the sidecar. ' +
      'Chain commands with `&&` in one call; do not start servers that outlive the call.',
    parameters: RUN_COMMAND_PARAMS,
    async execute(params, ctx): Promise<ToolResult> {
      let cwd: string;
      try {
        cwd = resolveInside(ctx.cwd, params.cwd ?? '.');
      } catch (error) {
        return errorResult(error);
      }
      const result = await runner(['/bin/sh', '-c', params.command], {
        cwd,
        timeoutMs: params.timeoutMs ?? DEFAULT_COMMAND_TIMEOUT_MS,
      });
      return {
        content: [{ type: 'text', text: renderCommandResult(params.command, result) }],
        ...(result.exitCode === 0 ? {} : { isError: true }),
      };
    },
  };
}

export function screenshotTool(target: StorefrontTarget): Tool<typeof SCREENSHOT_PARAMS> {
  const viewports = JUDGE_VIEWPORTS.map((v) => `${v.name} ${v.width}x${v.height}`).join(', ');
  return {
    name: SCREENSHOT_TOOL,
    description: [
      'Rebuild the storefront if its source changed, load a route in a headless browser and return',
      `one screenshot per judge viewport (${viewports}), exactly what the visual_judge verifier scores.`,
      'Call it after styling a page and before marking the task done.',
    ].join(' '),
    parameters: SCREENSHOT_PARAMS,
    async execute(params, ctx): Promise<ToolResult> {
      if (!params.route.startsWith('/')) {
        return errorResult(new Error(`route must start with "/": ${params.route}`));
      }
      try {
        await target.prepare?.();
      } catch (error) {
        return errorResult(new Error(`the storefront did not start: ${errorMessage(error)}`));
      }
      const outDir = await fs.mkdtemp(path.join(os.tmpdir(), 'shopgym-screenshot-'));
      try {
        const session = await BrowserSession.launch({ episodeId: screenshotEpisodeId(ctx.callId) });
        let capture: Awaited<ReturnType<typeof capturePage>>;
        try {
          capture = await capturePage({
            session,
            baseUrl: target.url,
            route: params.route,
            outDir,
          });
        } finally {
          await session.close();
        }
        if (capture.error !== undefined) {
          return errorResult(new Error(`${params.route} did not load: ${capture.error}`));
        }
        const images: ToolContent[] = await Promise.all(
          capture.screenshots.map(async (shot) => ({
            type: 'image' as const,
            data: (await fs.readFile(shot.path)).toString('base64'),
            mimeType: 'image/png',
          })),
        );
        const order = capture.screenshots.map((shot) => shot.viewport).join(', then ');
        return {
          content: [
            {
              type: 'text',
              text: `${params.route} responded ${capture.status ?? 'unknown'}; captures: ${order}.`,
            },
            ...images,
          ],
        };
      } finally {
        await fs.rm(outDir, { recursive: true, force: true });
      }
    },
  };
}

function renderCommandResult(command: string, result: CommandResult): string {
  const status = result.timedOut
    ? 'timed out and was killed'
    : `exited with code ${result.exitCode ?? 'unknown'}`;
  const lines = [`\`${command}\` ${status}.`];
  if (result.stdout.trim() !== '') {
    lines.push('', 'stdout:', '```', clipMiddle(result.stdout.trimEnd()), '```');
  }
  if (result.stderr.trim() !== '') {
    lines.push('', 'stderr:', '```', clipMiddle(result.stderr.trimEnd()), '```');
  }
  return lines.join('\n');
}

/** Keep the head and tail of long output; compiler errors sit at either end. */
function clipMiddle(text: string, limit = OUTPUT_LIMIT_CHARS): string {
  if (text.length <= limit) {
    return text;
  }
  const half = Math.floor(limit / 2);
  const dropped = text.length - 2 * half;
  return `${text.slice(0, half)}\n[...${dropped} characters elided...]\n${text.slice(-half)}`;
}

/**
 * Backend episode ids match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`; provider
 * tool-call ids can carry other characters (`|`) and exceed that length.
 */
export function screenshotEpisodeId(callId: string): string {
  return `screenshot-${callId.replace(/[^A-Za-z0-9._-]/g, '-')}`.slice(0, 64);
}

function errorResult(error: unknown): ToolResult {
  return { content: [{ type: 'text', text: `Error: ${errorMessage(error)}` }], isError: true };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
