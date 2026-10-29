import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import type { VerifierContext } from '@shop-gym/harness';
import { beforeEach, describe, expect, it } from 'vitest';

import { TEMPLATE_JSON, defaultBackendTemplateDir, templateFingerprint } from '../seed.js';
import { backendTestVerifier, backendTypecheckVerifier } from './backend_commands.js';
import { OwnedFilesVerifier } from './owned_files.js';
import { readOnlyDrift, sandboxContractVerifier } from './sandbox_contract.js';
import { type CommandResult, type CommandRunner, truncateStream } from './subprocess.js';

const OK: CommandResult = { exitCode: 0, stdout: '', stderr: '', timedOut: false };
const FAILED: CommandResult = {
  exitCode: 2,
  stdout: 'src/x.ts(1,1): error TS2322',
  stderr: '',
  timedOut: false,
};

let artifactDir: string;
let backendDir: string;

beforeEach(async () => {
  const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'verifiers-'));
  artifactDir = path.join(runDir, 'artifact');
  backendDir = path.join(artifactDir, 'backend');
  await fs.mkdir(path.join(backendDir, 'src', 'data'), { recursive: true });
  await fs.mkdir(path.join(backendDir, 'src', 'sandbox'), { recursive: true });
  await fs.mkdir(path.join(backendDir, 'tests', 'contract'), { recursive: true });
  await fs.mkdir(path.join(artifactDir, 'storefront', 'app'), { recursive: true });
});

function ctx(selectedTaskId: string): VerifierContext {
  return {
    runDir: path.dirname(artifactDir),
    iterId: 'exec-0001',
    selectedTaskId,
    plan: [],
    artifactDir,
  };
}

function recording(result: CommandResult, calls: { argv: string[]; cwd: string }[]): CommandRunner {
  return async (argv, options) => {
    calls.push({ argv: [...argv], cwd: options.cwd });
    return result;
  };
}

describe('backend command verifiers', () => {
  it('apply to backend tasks only', () => {
    for (const verifier of [backendTypecheckVerifier(), backendTestVerifier()]) {
      expect(verifier.appliesTo('gen_backend')).toBe(true);
      expect(verifier.appliesTo('backend_followup')).toBe(true);
      expect(verifier.appliesTo('gen_homepage')).toBe(false);
      expect(verifier.appliesTo('visual_fix')).toBe(false);
    }
  });

  it('run pnpm inside artifact/backend and pass on exit 0', async () => {
    const calls: { argv: string[]; cwd: string }[] = [];
    const result = await backendTypecheckVerifier(recording(OK, calls)).run(ctx('gen_backend'));
    expect(result.verdict).toBe('pass');
    expect(calls).toEqual([{ argv: ['pnpm', 'typecheck'], cwd: backendDir }]);
  });

  it('fail with fenced output on a non-zero exit', async () => {
    const result = await backendTestVerifier(recording(FAILED, [])).run(ctx('gen_backend'));
    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain('`pnpm test` failed.');
    expect(result.feedback).toContain('error TS2322');
    expect(result.details).toMatchObject({ exitCode: 2 });
  });

  it('fail on timeout', async () => {
    const timedOut = { ...OK, exitCode: null, timedOut: true };
    const result = await backendTypecheckVerifier(recording(timedOut, [])).run(ctx('gen_backend'));
    expect(result.verdict).toBe('fail');
    expect(result.feedback).toMatch(/exceeded the verifier timeout/);
  });
});

describe('truncateStream', () => {
  it('keeps the head and marks truncation', () => {
    expect(truncateStream('abcdef', 3)).toBe('abc\n[...truncated]');
    expect(truncateStream('abc', 3)).toBe('abc');
  });
});

describe('sandbox_contract', () => {
  async function seedReadOnly(): Promise<void> {
    const template = defaultBackendTemplateDir();
    for (const rel of [
      'src/data/schema.ts',
      'src/sandbox/episode.ts',
      'tests/contract/helpers.ts',
    ]) {
      await fs.copyFile(path.join(template, rel), path.join(backendDir, rel));
    }
    const fingerprint = await templateFingerprint(template, async (argv) => {
      if (argv[1] === 'ls-files') {
        return {
          ...OK,
          stdout:
            'src/data/schema.ts\0src/sandbox/episode.ts\0tests/contract/helpers.ts\0package.json\0',
        };
      }
      return { ...OK, exitCode: 1 };
    });
    await fs.writeFile(path.join(backendDir, TEMPLATE_JSON), JSON.stringify(fingerprint));
  }

  it('passes when read-only paths match and the suite passes', async () => {
    await seedReadOnly();
    const calls: { argv: string[]; cwd: string }[] = [];
    const result = await sandboxContractVerifier(recording(OK, calls)).run(ctx('gen_backend'));
    expect(result.verdict).toBe('pass');
    expect(calls).toEqual([
      { argv: ['pnpm', 'exec', 'vitest', 'run', 'tests/contract'], cwd: backendDir },
    ]);
  });

  it('fails without running the suite when a read-only path drifted', async () => {
    await seedReadOnly();
    await fs.appendFile(path.join(backendDir, 'src', 'data', 'schema.ts'), '\n// edited\n');
    await fs.rm(path.join(backendDir, 'src', 'sandbox', 'episode.ts'));
    await fs.writeFile(path.join(backendDir, 'tests', 'contract', 'new.test.ts'), '');
    const calls: { argv: string[]; cwd: string }[] = [];
    const result = await sandboxContractVerifier(recording(OK, calls)).run(ctx('gen_backend'));
    expect(result.verdict).toBe('fail');
    expect(calls).toEqual([]);
    expect(result.feedback).toContain('`backend/src/data/schema.ts` (modified)');
    expect(result.feedback).toContain('`backend/src/sandbox/episode.ts` (deleted)');
    expect(result.feedback).toContain('`backend/tests/contract/new.test.ts` (added)');
    const fingerprint = JSON.parse(
      await fs.readFile(path.join(backendDir, TEMPLATE_JSON), 'utf-8'),
    );
    expect((await readOnlyDrift(backendDir, fingerprint)).map((d) => d.kind)).toEqual([
      'modified',
      'deleted',
      'added',
    ]);
  });

  it('fails with the suite output when the suite fails', async () => {
    await seedReadOnly();
    const result = await sandboxContractVerifier(recording(FAILED, [])).run(ctx('backend_fix'));
    expect(result.verdict).toBe('fail');
    expect(result.feedback).toContain('`pnpm exec vitest run tests/contract` failed.');
  });
});

describe('owned_files verifier', () => {
  it('classifies the paths the iteration changed', async () => {
    let changed: string[] = [];
    const verifier = new OwnedFilesVerifier({ changedPaths: async () => changed });
    expect(verifier.appliesTo('anything')).toBe(true);
    expect((await verifier.run(ctx('gen_theme'))).verdict).toBe('pass');

    changed = ['storefront/app/root.tsx'];
    const first = await verifier.run(ctx('gen_theme'));
    expect(first.verdict).toBe('pass');
    expect(first.details).toMatchObject({ changedPaths: ['storefront/app/root.tsx'] });

    const second = await verifier.run(ctx('gen_homepage'));
    expect(second.verdict).toBe('advisory');
    expect(second.feedback).toContain("another task's slice");

    changed = ['backend/src/data/schema.ts'];
    const third = await verifier.run(ctx('gen_backend'));
    expect(third.verdict).toBe('fail');
    expect(third.feedback).toContain('`backend/src/data/schema.ts`');
  });
});
