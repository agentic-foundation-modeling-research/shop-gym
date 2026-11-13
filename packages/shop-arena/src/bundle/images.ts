/**
 * Polite download of the product images of a Source bundle.
 *
 * `downloadImages` looks at the first `perProduct` images of each product.
 * Each one with a `source_url` and no `path` is picked, and each picked URL
 * is downloaded once into `catalog/images/`. The file name is a hash of
 * the URL with the extension of the URL, so a file that is on disk is an
 * image that an earlier run saved, and it is not requested again. Then the
 * products are written again, with `path` next to `source_url` on each
 * picked image that is on disk.
 *
 * The download requests only the picked URLs. It keeps a few requests open
 * at a time, gives each request a time limit, and does not follow
 * redirects. A network error, a time-out, a 408 or a 5xx is retried with
 * exponential backoff. A refusal (a redirect, a 401, 403 or 429, or an
 * answer that is not an image) is never retried, and ten refusals in a row
 * stop the download: the images not yet requested keep only their source
 * URL. A failed image is recorded in the report and does not fail the
 * download.
 */

import { createHash } from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import {
  type BundleImage,
  type BundleProduct,
  bundleProductSchema,
  readJsonlLines,
} from '@shop-gym/core';

import { writeJsonl } from './jsonl.js';

/** Requests open at one time. */
const CONCURRENCY = 4;
/** Time limit of one request, body included. */
const TIMEOUT_MS = 30_000;
/** Retries after the first attempt, for an answer that can change later. */
const RETRIES = 3;
/** Wait before the first retry; each next retry waits twice as long. */
const BACKOFF_MS = 1_000;
/** Refused requests in a row that stop the download. */
const MAX_REFUSALS_IN_A_ROW = 10;
/** A progress line is logged after each this many requested images. */
const LOG_EVERY = 500;
/** Local copies go to this directory under `catalog/`. */
const IMAGES_DIR = 'images';

const REFUSED_STATUSES: ReadonlySet<number> = new Set([401, 403, 429]);

/** The `fetch` that the download uses. The global `fetch` fits it. */
export type FetchImage = (
  url: string,
  init: { readonly signal: AbortSignal; readonly redirect: 'manual' },
) => Promise<Response>;

export interface ImageDeps {
  readonly fetch: FetchImage;
  /** Waits `ms` before a retry, and rejects when `signal` aborts. */
  readonly sleep: (ms: number, signal: AbortSignal) => Promise<void>;
  readonly log: (line: string) => void;
  /** Aborting it stops the download with an error; a rerun resumes it. */
  readonly signal: AbortSignal;
}

export interface ImageJob {
  /** The products to read, one JSON line each. */
  readonly productsFile: string;
  /** Where to write the products with the local paths. */
  readonly outFile: string;
  /** The `catalog/` directory of the bundle; image paths are relative to it. */
  readonly catalogDir: string;
  /** The first this many images of each product are picked; 0 picks none. */
  readonly perProduct: number;
}

export interface ImageFailure {
  readonly source_url: string;
  /** For example `HTTP 404` or `timed out after 30 s`. */
  readonly error: string;
}

/** What the download did, as recorded in the bundle report. */
export interface ImagesReport {
  readonly per_product: number;
  /** Distinct image URLs picked. */
  readonly picked: number;
  readonly downloaded: number;
  /** Picked images that an earlier run saved; they were not requested. */
  readonly on_disk: number;
  /** In the order that the images were picked. */
  readonly failed: readonly ImageFailure[];
  /** Picked images that were not requested because the download stopped. */
  readonly not_requested: number;
  /** Why the download stopped before the end. */
  readonly stopped?: string;
}

interface Failure {
  readonly kind: 'refused' | 'failed';
  readonly error: string;
}

/** The result of one request. */
type Answer =
  | { readonly kind: 'image'; readonly bytes: Uint8Array }
  | { readonly kind: 'retry'; readonly error: string }
  | Failure;

/** The result of one image, after its retries. */
type Outcome = { readonly kind: 'saved' } | Failure;

interface Picked {
  readonly url: string;
  /** Relative to the `catalog/` directory. */
  readonly path: string;
}

/**
 * Download the picked images of the products in `job.productsFile` and
 * write the products with the local paths to `job.outFile`.
 *
 * @throws The abort reason of `deps.signal`, or a file system error.
 */
export async function downloadImages(job: ImageJob, deps: ImageDeps): Promise<ImagesReport> {
  const picked = new Map<string, Picked>();
  if (job.perProduct > 0) {
    for await (const product of readProducts(job.productsFile)) {
      (product.images ?? []).forEach((image, index) => {
        const url = pickedUrl(image, index, job.perProduct);
        if (url !== undefined && !picked.has(url)) picked.set(url, { url, path: localPath(url) });
      });
    }
  }
  const saved = new Map<string, string>();
  const queue: Picked[] = [];
  for (const image of picked.values()) {
    if (await isFile(path.join(job.catalogDir, image.path))) {
      saved.set(image.url, image.path);
    } else {
      queue.push(image);
    }
  }
  const onDisk = saved.size;
  deps.log(
    `[images] ${picked.size} images picked (${job.perProduct} per product), ${onDisk} already on disk`,
  );
  if (queue.length > 0) await fs.mkdir(path.join(job.catalogDir, IMAGES_DIR), { recursive: true });

  const failures = new Map<string, string>();
  let next = 0;
  let refusalsInARow = 0;
  let stopped: string | undefined;
  let thrown: unknown;
  const take = (): Picked | undefined => {
    if (stopped !== undefined || thrown !== undefined) return undefined;
    const image = queue[next];
    if (image !== undefined) next += 1;
    return image;
  };
  const worker = async (): Promise<void> => {
    for (let image = take(); image !== undefined; image = take()) {
      let outcome: Outcome;
      try {
        outcome = await download(image.url, path.join(job.catalogDir, image.path), deps);
      } catch (err) {
        thrown ??= err;
        return;
      }
      if (outcome.kind === 'saved') {
        saved.set(image.url, image.path);
        refusalsInARow = 0;
      } else {
        failures.set(image.url, outcome.error);
        refusalsInARow = outcome.kind === 'refused' ? refusalsInARow + 1 : 0;
        if (refusalsInARow >= MAX_REFUSALS_IN_A_ROW && stopped === undefined) {
          stopped = `${MAX_REFUSALS_IN_A_ROW} refused requests in a row (last: ${outcome.error})`;
        }
      }
      const done = saved.size - onDisk + failures.size;
      if (done % LOG_EVERY === 0) deps.log(`[images] ${done}/${queue.length} requested`);
    }
  };
  await Promise.all(Array.from({ length: CONCURRENCY }, worker));
  if (thrown !== undefined) {
    throw thrown instanceof Error ? thrown : new Error(String(thrown));
  }

  const notRequested = queue.length - next;
  if (stopped !== undefined) {
    deps.log(`[images] stopped after ${stopped}; ${notRequested} images not requested`);
  }
  deps.log(
    `[images] ${saved.size - onDisk} downloaded, ${onDisk} on disk, ${failures.size} failed`,
  );
  await writeJsonl(job.outFile, withPaths(readProducts(job.productsFile), job.perProduct, saved));
  return {
    per_product: job.perProduct,
    picked: picked.size,
    downloaded: saved.size - onDisk,
    on_disk: onDisk,
    failed: queue.flatMap(({ url }) => {
      const error = failures.get(url);
      return error !== undefined ? [{ source_url: url, error }] : [];
    }),
    not_requested: notRequested,
    ...(stopped !== undefined ? { stopped } : {}),
  };
}

/** The URL to download for the image at `index` of a product, if it is picked. */
function pickedUrl(image: BundleImage, index: number, perProduct: number): string | undefined {
  return index < perProduct && image.path === undefined ? image.source_url : undefined;
}

/** `images/<16 hex digits of the URL hash><extension of the URL>`. */
function localPath(url: string): string {
  const hash = createHash('sha256').update(url).digest('hex').slice(0, 16);
  const extension = /\.[A-Za-z0-9]{1,5}$/.exec(new URL(url).pathname)?.[0] ?? '';
  return `${IMAGES_DIR}/${hash}${extension.toLowerCase()}`;
}

async function* readProducts(file: string): AsyncGenerator<BundleProduct> {
  for await (const { line, text } of readJsonlLines(file)) {
    const result = bundleProductSchema.safeParse(JSON.parse(text));
    if (!result.success) throw new Error(`${file}:${line}: ${result.error.message}`);
    yield result.data;
  }
}

/** The products, with `path` set on each picked image that is saved. */
async function* withPaths(
  products: AsyncIterable<BundleProduct>,
  perProduct: number,
  saved: ReadonlyMap<string, string>,
): AsyncGenerator<BundleProduct> {
  for await (const product of products) {
    if (product.images === undefined) {
      yield product;
      continue;
    }
    const images = product.images.map((image, index) => {
      const url = pickedUrl(image, index, perProduct);
      const local = url !== undefined ? saved.get(url) : undefined;
      return local !== undefined ? { ...image, path: local } : image;
    });
    yield { ...product, images };
  }
}

/** Request one image, and retry with backoff while the answer can change. */
async function download(url: string, file: string, deps: ImageDeps): Promise<Outcome> {
  for (let attempt = 0; ; attempt += 1) {
    const answer = await request(url, deps);
    if (answer.kind === 'image') {
      // A partial file never has the final name, so a file on disk is complete.
      await fs.writeFile(`${file}.part`, answer.bytes);
      await fs.rename(`${file}.part`, file);
      return { kind: 'saved' };
    }
    if (answer.kind !== 'retry') return answer;
    if (attempt === RETRIES) return { kind: 'failed', error: answer.error };
    await deps.sleep(BACKOFF_MS * 2 ** attempt, deps.signal);
  }
}

async function request(url: string, deps: ImageDeps): Promise<Answer> {
  const signal = AbortSignal.any([deps.signal, AbortSignal.timeout(TIMEOUT_MS)]);
  try {
    const response = await deps.fetch(url, { signal, redirect: 'manual' });
    const type = response.headers.get('content-type') ?? '';
    if (response.ok && type.startsWith('image/')) {
      return { kind: 'image', bytes: new Uint8Array(await response.arrayBuffer()) };
    }
    await response.body?.cancel();
    if (response.ok) {
      return { kind: 'refused', error: `not an image (${type === '' ? 'no content type' : type})` };
    }
    const { status } = response;
    const error = `HTTP ${status}`;
    if (REFUSED_STATUSES.has(status) || (status >= 300 && status < 400)) {
      return { kind: 'refused', error };
    }
    return { kind: status === 408 || status >= 500 ? 'retry' : 'failed', error };
  } catch (err) {
    deps.signal.throwIfAborted();
    return { kind: 'retry', error: errorText(err) };
  }
}

function errorText(err: unknown): string {
  if (!(err instanceof Error)) return String(err);
  if (err.name === 'TimeoutError') return `timed out after ${TIMEOUT_MS / 1000} s`;
  return err.cause instanceof Error ? `${err.message}: ${err.cause.message}` : err.message;
}

async function isFile(file: string): Promise<boolean> {
  try {
    return (await fs.stat(file)).isFile();
  } catch {
    return false;
  }
}
