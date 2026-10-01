/** Small JSON and text file helpers shared by the gen steps. */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { z } from 'zod';

/** Reads and validates a JSON file; the error names the file. */
export async function readJsonFile<T>(file: string, schema: z.ZodType<T>): Promise<T> {
  const raw = await fs.readFile(file, 'utf-8');
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    throw new Error(`${file}: not valid JSON: ${err instanceof Error ? err.message : String(err)}`);
  }
  const result = schema.safeParse(parsed);
  if (!result.success) {
    throw new Error(`${file}: ${result.error.message}`);
  }
  return result.data;
}

/** Like `readJsonFile`, but resolves `undefined` when the file does not exist. */
export async function readJsonIfExists<T>(
  file: string,
  schema: z.ZodType<T>,
): Promise<T | undefined> {
  try {
    await fs.access(file);
  } catch {
    return undefined;
  }
  return readJsonFile(file, schema);
}

/** Writes `value` as indented JSON, atomically (temp file + rename). */
export async function writeJsonFile(file: string, value: unknown): Promise<void> {
  await writeTextFile(file, `${JSON.stringify(value, null, 2)}\n`);
}

/** Writes `text`, creating parent directories, atomically (temp file + rename). */
export async function writeTextFile(file: string, text: string): Promise<void> {
  await writeBytes(file, Buffer.from(text, 'utf-8'));
}

export async function writeBytes(file: string, bytes: Uint8Array): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp-${process.pid}`;
  await fs.writeFile(tmp, bytes);
  await fs.rename(tmp, file);
}

export async function exists(file: string): Promise<boolean> {
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
}

/** Runs `fn` over `items` with at most `limit` in flight, preserving order. */
export async function mapLimit<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results: R[] = new Array<R>(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, async () => {
    for (;;) {
      const index = next;
      next += 1;
      if (index >= items.length) {
        return;
      }
      const item = items[index] as T;
      results[index] = await fn(item, index);
    }
  });
  await Promise.all(workers);
  return results;
}
