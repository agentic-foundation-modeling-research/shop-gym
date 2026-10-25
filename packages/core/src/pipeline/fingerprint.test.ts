import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { fingerprintPaths } from './fingerprint.js';

let root: string;

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'shopgym-fp-'));
});

afterEach(() => {
  fs.rmSync(root, { recursive: true, force: true });
});

describe('fingerprintPaths', () => {
  it('is stable across calls and path order', () => {
    const a = path.join(root, 'a.txt');
    const b = path.join(root, 'b.txt');
    fs.writeFileSync(a, 'alpha');
    fs.writeFileSync(b, 'beta');
    expect(fingerprintPaths([a, b])).toBe(fingerprintPaths([b, a]));
  });

  it('changes when a file inside a directory changes', () => {
    const dir = path.join(root, 'data');
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'x.json'), '1');
    const before = fingerprintPaths([dir]);
    fs.writeFileSync(path.join(dir, 'x.json'), '2');
    expect(fingerprintPaths([dir])).not.toBe(before);
  });

  it('distinguishes a missing path from an empty directory', () => {
    const dir = path.join(root, 'empty');
    const missing = fingerprintPaths([dir]);
    fs.mkdirSync(dir);
    expect(fingerprintPaths([dir])).not.toBe(missing);
  });
});
