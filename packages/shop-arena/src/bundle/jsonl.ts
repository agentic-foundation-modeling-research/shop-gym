/** Streaming JSON Lines output for bundle files that can be larger than one string. */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

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
