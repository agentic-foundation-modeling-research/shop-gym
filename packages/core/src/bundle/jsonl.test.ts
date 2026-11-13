import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { readJsonlLines } from './jsonl.js';

let dir: string;

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shopgym-jsonl-'));
});

afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
});

async function lines(content: string): Promise<{ line: number; text: string }[]> {
  const file = path.join(dir, 'x.jsonl');
  fs.writeFileSync(file, content);
  const out: { line: number; text: string }[] = [];
  for await (const entry of readJsonlLines(file)) out.push(entry);
  return out;
}

describe('readJsonlLines', () => {
  it('splits only at line feeds and keeps U+2028 and U+2029 inside a line', async () => {
    const record = JSON.stringify({ text: 'one two three' });
    expect(await lines(`${record}\n{"b":2}\r\n\n  \n{"c":3}`)).toEqual([
      { line: 1, text: record },
      { line: 2, text: '{"b":2}' },
      { line: 5, text: '{"c":3}' },
    ]);
  });

  it('reads lines that are longer than one read chunk', async () => {
    const long = JSON.stringify({ text: 'x'.repeat(200_000) });
    expect((await lines(`${long}\n${long}\n`)).map((entry) => entry.text.length)).toEqual([
      long.length,
      long.length,
    ]);
  });
});
