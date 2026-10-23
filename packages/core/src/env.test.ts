import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { loadCredentials } from './env.js';

let root: string;

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'shopgym-env-'));
});

afterEach(() => {
  fs.rmSync(root, { recursive: true, force: true });
});

describe('loadCredentials', () => {
  it('reads values from the project .env', () => {
    fs.writeFileSync(
      path.join(root, '.env'),
      'OPENAI_API_KEY=sk-file\nOPENAI_BASE_URL="https://proxy"\n',
    );
    expect(loadCredentials(root, {})).toEqual({
      openaiApiKey: 'sk-file',
      openaiBaseUrl: 'https://proxy',
    });
  });

  it('lets shell values override the file', () => {
    fs.writeFileSync(path.join(root, '.env'), 'OPENAI_API_KEY=sk-file\n');
    expect(loadCredentials(root, { OPENAI_API_KEY: 'sk-shell' })).toEqual({
      openaiApiKey: 'sk-shell',
    });
  });

  it('treats blank values as unset', () => {
    fs.writeFileSync(path.join(root, '.env'), 'ANTHROPIC_API_KEY=\nPI_PROXY_API_KEY=proxy\n');
    expect(loadCredentials(root, { OPENAI_API_KEY: '  ' })).toEqual({ piProxyApiKey: 'proxy' });
  });

  it('returns an empty object when there is no .env and no shell values', () => {
    expect(loadCredentials(root, {})).toEqual({});
  });
});
