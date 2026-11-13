/** Line-by-line reading of JSON Lines files that can be larger than memory. */

import * as fs from 'node:fs';

export interface JsonlLine {
  /** 1-based line number in the file. */
  readonly line: number;
  readonly text: string;
}

/**
 * Stream the lines of a JSON Lines file, without parsing them, so that a
 * caller can skip the lines it does not need. Lines end at `\n` (a `\r`
 * before it is dropped) and nowhere else: U+2028 and U+2029 may occur
 * unescaped inside JSON strings. Blank lines are skipped.
 */
export async function* readJsonlLines(file: string): AsyncGenerator<JsonlLine> {
  let line = 0;
  let rest = '';
  for await (const chunk of fs.createReadStream(file, { encoding: 'utf-8' })) {
    const parts = `${rest}${String(chunk)}`.split('\n');
    rest = parts.pop() ?? '';
    for (const part of parts) {
      line += 1;
      const text = withoutCr(part);
      if (/\S/.test(text)) yield { line, text };
    }
  }
  const last = withoutCr(rest);
  if (/\S/.test(last)) yield { line: line + 1, text: last };
}

function withoutCr(text: string): string {
  return text.endsWith('\r') ? text.slice(0, -1) : text;
}
