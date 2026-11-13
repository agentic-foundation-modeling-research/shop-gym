/** Streaming JSON Lines input and output for bundle files that can be larger than one string. */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { readJsonlLines } from '@shop-gym/core';
import type { z } from 'zod';

/** Lines are written to disk in chunks of about this many characters. */
const FLUSH_CHARS = 1 << 20;

/**
 * Write one JSON line per record, in order, and create the parent
 * directories.
 *
 * @returns The number of records written.
 */
export async function writeJsonl(
  file: string,
  records: Iterable<unknown> | AsyncIterable<unknown>,
): Promise<number> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const handle = await fs.open(file, 'w');
  let count = 0;
  try {
    let chunk = '';
    for await (const record of records) {
      chunk += `${JSON.stringify(record)}\n`;
      count += 1;
      if (chunk.length >= FLUSH_CHARS) {
        await handle.write(chunk);
        chunk = '';
      }
    }
    if (chunk !== '') await handle.write(chunk);
  } finally {
    await handle.close();
  }
  return count;
}

/**
 * Stream the records of a JSON Lines file, each checked against `schema`.
 *
 * @throws Error naming the file and the line of a record that is not valid.
 */
export async function* readJsonl<T>(file: string, schema: z.ZodType<T>): AsyncGenerator<T> {
  for await (const { line, text } of readJsonlLines(file)) {
    let value: unknown;
    try {
      value = JSON.parse(text);
    } catch (err) {
      throw new Error(
        `${file}:${line}: invalid JSON (${err instanceof Error ? err.message : String(err)})`,
      );
    }
    const result = schema.safeParse(value);
    if (!result.success) throw new Error(`${file}:${line}: ${result.error.message}`);
    yield result.data;
  }
}
