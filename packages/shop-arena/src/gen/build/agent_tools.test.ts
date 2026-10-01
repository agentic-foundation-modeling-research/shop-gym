/**
 * `run_command` against a fake and the real shell; `screenshot_page`
 * against a static page served from `node:http` with a real browser.
 */

import * as http from 'node:http';
import * as os from 'node:os';
import * as path from 'node:path';

import type { ToolContent, ToolContext } from '@shop-gym/agent';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { buildAgentTools, runCommandTool, screenshotTool } from './agent_tools.js';
import { runCommand } from './verifiers/subprocess.js';

const PAGE =
  '<!doctype html><html><head><title>Shot</title></head><body><h1>Hello</h1></body></html>';

let server: http.Server;
let url: string;
const hits: string[] = [];

beforeAll(async () => {
  server = http.createServer((req, res) => {
    hits.push(req.url ?? '');
    res.writeHead(req.url === '/missing' ? 404 : 200, { 'content-type': 'text/html' });
    res.end(PAGE);
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (address === null || typeof address === 'string') throw new Error('no port');
  url = `http://127.0.0.1:${address.port}`;
});

afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

function ctx(cwd: string): ToolContext {
  return { cwd, callId: 'call-1', signal: new AbortController().signal };
}

function text(content: readonly ToolContent[]): string {
  return content
    .filter((c): c is Extract<ToolContent, { type: 'text' }> => c.type === 'text')
    .map((c) => c.text)
    .join('\n');
}

describe('buildAgentTools', () => {
  it('exposes the shell and the screenshot tool', () => {
    expect(buildAgentTools({ target: { url } }).map((t) => t.name)).toEqual([
      'run_command',
      'screenshot_page',
    ]);
  });
});

describe('run_command', () => {
  const tool = runCommandTool(runCommand);

  it('runs through sh in the requested directory and reports the exit code', async () => {
    const result = await tool.execute(
      { command: 'pwd && echo out && echo err 1>&2' },
      ctx(os.tmpdir()),
    );
    expect(result.isError).toBeUndefined();
    const body = text(result.content);
    expect(body).toContain('exited with code 0');
    expect(body).toContain('out');
    expect(body).toContain('stderr:\n```\nerr');
    const nested = await tool.execute({ command: 'pwd', cwd: '.' }, ctx(os.tmpdir()));
    expect(text(nested.content)).toContain(path.resolve(os.tmpdir()));
  });

  it('flags a non-zero exit as an error result', async () => {
    const result = await tool.execute({ command: 'echo nope; exit 3' }, ctx(os.tmpdir()));
    expect(result.isError).toBe(true);
    expect(text(result.content)).toContain('exited with code 3');
  });

  it('refuses a cwd outside the run directory', async () => {
    const result = await tool.execute({ command: 'pwd', cwd: '../..' }, ctx(os.tmpdir()));
    expect(result.isError).toBe(true);
    expect(text(result.content)).toContain('escapes the run directory');
  });

  it('elides the middle of long output', async () => {
    const result = await tool.execute(
      { command: 'i=0; while [ $i -lt 3000 ]; do echo "line $i"; i=$((i+1)); done' },
      ctx(os.tmpdir()),
    );
    const body = text(result.content);
    expect(body).toContain('line 0\n');
    expect(body).toContain('line 2999');
    expect(body).toMatch(/\[\.\.\.\d+ characters elided\.\.\.\]/);
  });

  it('reports a timeout', async () => {
    const result = await tool.execute({ command: 'sleep 5', timeoutMs: 1000 }, ctx(os.tmpdir()));
    expect(result.isError).toBe(true);
    expect(text(result.content)).toContain('timed out');
  }, 10_000);
});

describe('screenshot_page', () => {
  it('prepares the target and returns the desktop and mobile captures', async () => {
    let prepared = 0;
    const tool = screenshotTool({
      url,
      prepare: async () => {
        prepared += 1;
      },
    });
    const result = await tool.execute({ route: '/' }, ctx(os.tmpdir()));
    expect(prepared).toBe(1);
    expect(result.isError).toBeUndefined();
    expect(text(result.content)).toBe('/ responded 200; captures: desktop, then mobile.');
    const images = result.content.filter((c) => c.type === 'image');
    expect(images).toHaveLength(2);
    expect(images.every((c) => c.type === 'image' && c.data.length > 100)).toBe(true);
    expect(hits.filter((h) => h === '/')).toHaveLength(2);
  }, 60_000);

  it('reports the status of a missing route and rejects malformed ones', async () => {
    const tool = screenshotTool({ url });
    const missing = await tool.execute({ route: '/missing' }, ctx(os.tmpdir()));
    expect(text(missing.content)).toContain('/missing responded 404');
    const bad = await tool.execute({ route: 'collections' }, ctx(os.tmpdir()));
    expect(bad.isError).toBe(true);
    expect(text(bad.content)).toContain('route must start with "/"');
  }, 60_000);

  it('turns a failed prepare into an error result', async () => {
    const tool = screenshotTool({
      url,
      prepare: async () => {
        throw new Error('build failed');
      },
    });
    const result = await tool.execute({ route: '/' }, ctx(os.tmpdir()));
    expect(result.isError).toBe(true);
    expect(text(result.content)).toContain('the storefront did not start: build failed');
  });
});
