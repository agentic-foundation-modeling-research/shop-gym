import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

import { build } from '@shop-gym/shop-arena';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';

import { CliError } from '../context.js';
import {
  killTree,
  pidAlive,
  portFree,
  runCommand,
  spawnDetached,
  waitForHealth,
} from './process.js';

const SERVER = `
const http = require('node:http');
const port = Number(process.argv[2] ?? process.env.PORT);
http.createServer((req, res) => res.end(req.url === '/health' ? 'ok' : 'hi')).listen(port, '127.0.0.1');
`;

let dir: string;
let script: string;
const pids: number[] = [];

beforeAll(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), 'host-process-'));
  script = path.join(dir, 'server.cjs');
  await fs.writeFile(script, SERVER);
});

afterEach(async () => {
  for (const pid of pids.splice(0)) {
    await killTree(pid);
  }
});

describe('host process primitives', () => {
  it('spawns a detached server, waits for /health, then kills it', async () => {
    const port = await build.freePort();
    const logPath = path.join(dir, 'server.log');
    const pid = await spawnDetached({
      command: process.execPath,
      args: [script, String(port)],
      cwd: dir,
      env: { ...process.env },
      logPath,
    });
    pids.push(pid);
    expect(pidAlive(pid)).toBe(true);
    await waitForHealth(`http://127.0.0.1:${port}`, pid, 10_000, logPath);
    expect(await portFree(port)).toBe(false);

    await killTree(pid, 1_000);
    expect(pidAlive(pid)).toBe(false);
    expect(await portFree(port)).toBe(true);
    await killTree(pid);
  });

  it('fails fast when the process exits before /health', async () => {
    const port = await build.freePort();
    const logPath = path.join(dir, 'exit.log');
    const pid = await spawnDetached({
      command: process.execPath,
      args: ['-e', 'console.error("nope"); process.exit(3)'],
      cwd: dir,
      env: { ...process.env },
      logPath,
    });
    pids.push(pid);
    await expect(waitForHealth(`http://127.0.0.1:${port}`, pid, 10_000, logPath)).rejects.toThrow(
      /exited before answering \/health; see .*exit\.log/,
    );
    expect(await fs.readFile(logPath, 'utf-8')).toContain('nope');
  });

  it('times out when /health never answers', async () => {
    const port = await build.freePort();
    await expect(
      waitForHealth(`http://127.0.0.1:${port}`, process.pid, 500, '/dev/null'),
    ).rejects.toBeInstanceOf(CliError);
  });

  it('runs foreground commands and reports the exit code', async () => {
    const ok = await runCommand([process.execPath, '-e', 'console.log("hi")'], dir);
    expect(ok).toEqual({ exitCode: 0, output: 'hi\n' });
    const bad = await runCommand(
      [process.execPath, '-e', 'console.error("x"); process.exit(2)'],
      dir,
    );
    expect(bad.exitCode).toBe(2);
    expect(bad.output).toContain('x');
  });

  it('kills what a foreground command left in the background', async () => {
    const result = await runCommand(['/bin/sh', '-c', 'sleep 30 & echo $!'], dir);

    expect(result.exitCode).toBe(0);
    const pid = Number(result.output.trim());
    for (let attempt = 0; attempt < 20 && pidAlive(pid); attempt += 1) {
      await sleep(50);
    }
    expect(pidAlive(pid)).toBe(false);
  });
});
