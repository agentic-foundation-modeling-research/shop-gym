/**
 * The `shopgym bundle` pipeline: `sample -> images -> publish`, run by the
 * core pipeline runner. `sample` reads the source files and writes a raw
 * Source bundle under `.bundle/raw`. `images` downloads the first images of
 * each product into `catalog/images/` and writes the products with the
 * local paths under `.bundle/images`. `publish` copies the bundle to the
 * bundle directory, validates it at the `raw` level, and writes
 * `report.json`.
 *
 * Completion is derived from the files: the source files and
 * `.bundle/request.json` (the resolved sample options) are the inputs of
 * `sample`, and `.bundle/images-request.json` is an input of `images`, so
 * a rerun with the same options and source skips every step, and `from`
 * forces a step and the steps after it. No step owns the files in
 * `catalog/images/`, so a rerun never deletes them, and `images` does not
 * request a file that is already there. The same options and source give
 * the same bytes.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

import {
  BUNDLE_FILES,
  type BundleCounts,
  type Step,
  type StepReport,
  runPipeline,
  validateBundle,
} from '@shop-gym/core';

import { writeJsonFile } from '../gen/io.js';
import { type Ar23Files, ar23Files, writeAr23Bundle } from './ar23/adapter.js';
import { type FetchImage, downloadImages } from './images.js';
import { type BundleOptions, type BundleOptionsInput, bundleOptionsSchema } from './options.js';

const WORK_DIR = '.bundle';
const REQUEST_FILE = path.join(WORK_DIR, 'request.json');
const RAW_DIR = path.join(WORK_DIR, 'raw');
const SAMPLE_REPORT_FILE = path.join(WORK_DIR, 'sample.json');
const IMAGES_REQUEST_FILE = path.join(WORK_DIR, 'images-request.json');
const IMAGES_PRODUCTS_FILE = path.join(WORK_DIR, 'images', 'products.jsonl');
const IMAGES_REPORT_FILE = path.join(WORK_DIR, 'images', 'report.json');
/** What the adapter read, dropped and kept, the image download, and the validation counts. */
export const BUNDLE_REPORT_FILE = 'report.json';
/** Bundle entries that `publish` copies from the raw bundle as they are. */
const PUBLISHED = [BUNDLE_FILES.manifest, BUNDLE_FILES.reviews, 'events'] as const;

interface BundleContext {
  readonly options: BundleOptions;
  readonly files: Ar23Files;
  readonly fetch: FetchImage;
  readonly sleep: (ms: number, signal: AbortSignal) => Promise<void>;
}

export interface BundleDeps {
  readonly log?: (line: string) => void;
  readonly signal?: AbortSignal;
  /** Downloads the images; the global `fetch` by default. */
  readonly fetch?: FetchImage;
  /** Waits before an image download retry; a timer by default. */
  readonly sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
}

export interface BundleResult {
  readonly bundleDir: string;
  /** `<bundleDir>/bundle.json`. */
  readonly manifestPath: string;
  /** `<bundleDir>/report.json`. */
  readonly reportPath: string;
  readonly reports: readonly StepReport[];
}

/** The content of `report.json`. */
export interface BundleReport {
  readonly sample: unknown;
  /** An `ImagesReport`: what was downloaded, what failed, and why the download stopped. */
  readonly images: unknown;
  readonly validation: { readonly level: 'raw'; readonly counts: BundleCounts };
}

function sampleStep(files: Ar23Files): Step<BundleContext> {
  return {
    id: 'sample',
    inputs: [REQUEST_FILE, files.reviews, files.meta],
    outputs: [RAW_DIR, SAMPLE_REPORT_FILE],
    run: async ({ outDir, context, log }) => {
      const rawDir = path.join(outDir, RAW_DIR);
      await fs.rm(rawDir, { recursive: true, force: true });
      const { options } = context;
      const report = await writeAr23Bundle(
        context.files,
        {
          name: path.basename(outDir),
          category: options.category,
          cutoff: options.cutoff,
          products: options.products,
          users: options.users,
          seed: options.seed,
          minEventsBefore: options.minEventsBefore,
          reviewsPerProduct: options.reviewsPerProduct,
        },
        rawDir,
        log,
      );
      await writeJsonFile(path.join(outDir, SAMPLE_REPORT_FILE), report);
    },
  };
}

function imagesStep(): Step<BundleContext> {
  const products = path.join(RAW_DIR, BUNDLE_FILES.products);
  return {
    id: 'images',
    inputs: [IMAGES_REQUEST_FILE, products],
    outputs: [IMAGES_PRODUCTS_FILE, IMAGES_REPORT_FILE],
    run: async ({ outDir, context, log, signal }) => {
      const report = await downloadImages(
        {
          productsFile: path.join(outDir, products),
          outFile: path.join(outDir, IMAGES_PRODUCTS_FILE),
          catalogDir: path.join(outDir, path.dirname(BUNDLE_FILES.products)),
          perProduct: context.options.imagesPerProduct,
        },
        { fetch: context.fetch, sleep: context.sleep, log, signal },
      );
      await writeJsonFile(path.join(outDir, IMAGES_REPORT_FILE), report);
    },
  };
}

function publishStep(): Step<BundleContext> {
  return {
    id: 'publish',
    inputs: [RAW_DIR, SAMPLE_REPORT_FILE, IMAGES_PRODUCTS_FILE, IMAGES_REPORT_FILE],
    outputs: [...PUBLISHED, BUNDLE_FILES.products, BUNDLE_REPORT_FILE],
    run: async ({ outDir, log }) => {
      const rawDir = path.join(outDir, RAW_DIR);
      for (const entry of PUBLISHED) {
        await fs.rm(path.join(outDir, entry), { recursive: true, force: true });
        await fs.cp(path.join(rawDir, entry), path.join(outDir, entry), { recursive: true });
      }
      await fs.cp(
        path.join(outDir, IMAGES_PRODUCTS_FILE),
        path.join(outDir, BUNDLE_FILES.products),
      );
      const validation = await validateBundle(outDir, 'raw');
      const readReport = async (file: string): Promise<unknown> =>
        JSON.parse(await fs.readFile(path.join(outDir, file), 'utf-8'));
      const report: BundleReport = {
        sample: await readReport(SAMPLE_REPORT_FILE),
        images: await readReport(IMAGES_REPORT_FILE),
        validation: { level: 'raw', counts: validation.counts },
      };
      await writeJsonFile(path.join(outDir, BUNDLE_REPORT_FILE), report);
      const { counts } = validation;
      log(
        `[publish] raw bundle: ${counts.products} products, ${counts.variants} variants, ${counts.reviews} reviews, ${counts.events} events`,
      );
    },
  };
}

/**
 * Builds a raw Source bundle from one category of a source dataset.
 *
 * @throws z.ZodError when `input` is invalid.
 * @throws StepFailedError when a step fails; `cause` carries the step's
 *   error, for example a `BundleValidationError`.
 * @throws MissingInputError when a source file does not exist.
 */
export async function buildBundle(
  input: BundleOptionsInput,
  deps: BundleDeps = {},
): Promise<BundleResult> {
  const options = bundleOptionsSchema.parse(input);
  const bundleDir = path.resolve(options.outDir);
  const files = ar23Files(path.resolve(options.sourceDir), options.category);
  await writeJsonFile(path.join(bundleDir, REQUEST_FILE), {
    adapter: options.adapter,
    files,
    category: options.category,
    cutoff: options.cutoff,
    products: options.products,
    users: options.users,
    seed: options.seed,
    min_events_before: options.minEventsBefore,
    reviews_per_product: options.reviewsPerProduct ?? null,
  });
  await writeJsonFile(path.join(bundleDir, IMAGES_REQUEST_FILE), {
    images_per_product: options.imagesPerProduct,
  });
  const reports = await runPipeline([sampleStep(files), imagesStep(), publishStep()], {
    outDir: bundleDir,
    context: {
      options,
      files,
      fetch: deps.fetch ?? fetch,
      sleep: deps.sleep ?? ((ms, signal) => sleep(ms, undefined, { signal })),
    },
    ...(options.from !== undefined ? { from: options.from } : {}),
    ...(deps.log !== undefined ? { log: deps.log } : {}),
    ...(deps.signal !== undefined ? { signal: deps.signal } : {}),
  });
  return {
    bundleDir,
    manifestPath: path.join(bundleDir, BUNDLE_FILES.manifest),
    reportPath: path.join(bundleDir, BUNDLE_REPORT_FILE),
    reports,
  };
}
