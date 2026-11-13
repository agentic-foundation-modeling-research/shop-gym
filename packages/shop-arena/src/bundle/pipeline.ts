/**
 * The `shopgym bundle` pipeline: `sample -> complete -> images -> publish`,
 * run by the core pipeline runner. `sample` reads the source files and
 * writes a raw Source bundle under `.bundle/raw`. `complete` fills its gaps
 * by rules and by an LLM and writes a complete bundle under
 * `.bundle/complete`. `images` downloads the first images of each complete
 * product into `catalog/images/` and writes the products with the local
 * paths under `.bundle/images`. `publish` copies the bundle to the bundle
 * directory, validates it there at the `complete` level (so each image
 * path names a file on disk), and writes `report.json`.
 *
 * Completion is derived from the files: the source files and
 * `.bundle/request.json` (the resolved sample options) are the inputs of
 * `sample`, `.bundle/complete_request.json` (the model) is an input of
 * `complete`, and `.bundle/images-request.json` is an input of `images`, so
 * a rerun with the same options and source skips every step. `from` forces
 * a step, and a later step runs again when its inputs changed. The LLM
 * replies are cached by their input under `.bundle/llm_cache`, which no step
 * owns, so a forced rerun makes no LLM call. No step owns the files in
 * `catalog/images/` either, so a rerun never deletes them, and `images`
 * does not request a file that is already there. The same options and
 * source give the same bytes.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

import type { LlmClient } from '@shop-gym/agent';
import {
  BUNDLE_FILES,
  type BundleCounts,
  type Step,
  type StepReport,
  runPipeline,
  validateBundle,
} from '@shop-gym/core';

import { parseModel } from '../explore/pipeline.js';
import { DEFAULT_LLM_TIMEOUT_MS } from '../gen/config.js';
import { writeJsonFile } from '../gen/io.js';
import { type Ar23Files, ar23Files, writeAr23Bundle } from './ar23/adapter.js';
import { completeBundle } from './complete/complete.js';
import { type FetchImage, downloadImages } from './images.js';
import { type BundleOptions, type BundleOptionsInput, bundleOptionsSchema } from './options.js';

const WORK_DIR = '.bundle';
const REQUEST_FILE = path.join(WORK_DIR, 'request.json');
const RAW_DIR = path.join(WORK_DIR, 'raw');
const SAMPLE_REPORT_FILE = path.join(WORK_DIR, 'sample.json');
const COMPLETE_REQUEST_FILE = path.join(WORK_DIR, 'complete_request.json');
const COMPLETE_DIR = path.join(WORK_DIR, 'complete');
const COMPLETE_REPORT_FILE = path.join(WORK_DIR, 'complete.json');
const LLM_CACHE_DIR = path.join(WORK_DIR, 'llm_cache');
const IMAGES_REQUEST_FILE = path.join(WORK_DIR, 'images-request.json');
const IMAGES_PRODUCTS_FILE = path.join(WORK_DIR, 'images', 'products.jsonl');
const IMAGES_REPORT_FILE = path.join(WORK_DIR, 'images', 'report.json');
/** What the adapter read, dropped and kept, what the complete step filled, the image download, and the validation counts. */
export const BUNDLE_REPORT_FILE = 'report.json';
/**
 * Bundle entries that `publish` copies from the complete bundle as they
 * are; the products come from the images step. Each entry is a file or a
 * directory without images, so publish never removes `catalog/images/`.
 */
const PUBLISHED = [
  BUNDLE_FILES.manifest,
  BUNDLE_FILES.reviews,
  path.dirname(BUNDLE_FILES.profiles),
  path.dirname(BUNDLE_FILES.events),
] as const;

interface BundleContext {
  readonly options: BundleOptions;
  readonly files: Ar23Files;
  readonly llm: LlmClient;
  readonly fetch: FetchImage;
  readonly sleep: (ms: number, signal: AbortSignal) => Promise<void>;
}

export interface BundleDeps {
  /** The LLM of the complete step. */
  readonly llm: LlmClient;
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
  /** What the adapter read, dropped and kept (`Ar23Report` for Amazon Reviews 2023). */
  readonly sample: unknown;
  /** What the complete step filled (`CompleteReport`). */
  readonly complete: unknown;
  /** An `ImagesReport`: what was downloaded, what failed, and why the download stopped. */
  readonly images: unknown;
  readonly validation: { readonly level: 'complete'; readonly counts: BundleCounts };
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

function completeStep(): Step<BundleContext> {
  return {
    id: 'complete',
    inputs: [RAW_DIR, COMPLETE_REQUEST_FILE],
    outputs: [COMPLETE_DIR, COMPLETE_REPORT_FILE],
    run: async ({ outDir, context, log, signal }) => {
      const completeDir = path.join(outDir, COMPLETE_DIR);
      await fs.rm(completeDir, { recursive: true, force: true });
      const { options } = context;
      const report = await completeBundle(path.join(outDir, RAW_DIR), completeDir, {
        call: {
          llm: context.llm,
          model: parseModel(options.model),
          timeoutMs: DEFAULT_LLM_TIMEOUT_MS,
          signal,
        },
        cacheDir: path.join(outDir, LLM_CACHE_DIR),
        concurrency: options.concurrency,
        seed: options.seed,
        log,
      });
      await writeJsonFile(path.join(outDir, COMPLETE_REPORT_FILE), report);
    },
  };
}

function imagesStep(): Step<BundleContext> {
  const products = path.join(COMPLETE_DIR, BUNDLE_FILES.products);
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
    inputs: [
      COMPLETE_DIR,
      SAMPLE_REPORT_FILE,
      COMPLETE_REPORT_FILE,
      IMAGES_PRODUCTS_FILE,
      IMAGES_REPORT_FILE,
    ],
    outputs: [...PUBLISHED, BUNDLE_FILES.products, BUNDLE_REPORT_FILE],
    run: async ({ outDir, log }) => {
      const completeDir = path.join(outDir, COMPLETE_DIR);
      for (const entry of PUBLISHED) {
        await fs.rm(path.join(outDir, entry), { recursive: true, force: true });
        await fs.cp(path.join(completeDir, entry), path.join(outDir, entry), { recursive: true });
      }
      await fs.cp(
        path.join(outDir, IMAGES_PRODUCTS_FILE),
        path.join(outDir, BUNDLE_FILES.products),
      );
      const validation = await validateBundle(outDir, 'complete');
      const readReport = async (file: string): Promise<unknown> =>
        JSON.parse(await fs.readFile(path.join(outDir, file), 'utf-8'));
      const report: BundleReport = {
        sample: await readReport(SAMPLE_REPORT_FILE),
        complete: await readReport(COMPLETE_REPORT_FILE),
        images: await readReport(IMAGES_REPORT_FILE),
        validation: { level: 'complete', counts: validation.counts },
      };
      await writeJsonFile(path.join(outDir, BUNDLE_REPORT_FILE), report);
      const { counts } = validation;
      log(
        `[publish] complete bundle: ${counts.products} products, ${counts.variants} variants, ${counts.reviews} reviews, ${counts.profiles} profiles, ${counts.events} events`,
      );
    },
  };
}

/**
 * Builds a complete Source bundle from one category of a source dataset.
 *
 * @throws z.ZodError when `input` is invalid.
 * @throws StepFailedError when a step fails; `cause` carries the step's
 *   error, for example a `BundleValidationError`.
 * @throws MissingInputError when a source file does not exist.
 */
export async function buildBundle(
  input: BundleOptionsInput,
  deps: BundleDeps,
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
  await writeJsonFile(path.join(bundleDir, COMPLETE_REQUEST_FILE), { model: options.model });
  await writeJsonFile(path.join(bundleDir, IMAGES_REQUEST_FILE), {
    images_per_product: options.imagesPerProduct,
  });
  const reports = await runPipeline(
    [sampleStep(files), completeStep(), imagesStep(), publishStep()],
    {
      outDir: bundleDir,
      context: {
        options,
        files,
        llm: deps.llm,
        fetch: deps.fetch ?? fetch,
        sleep: deps.sleep ?? ((ms, signal) => sleep(ms, undefined, { signal })),
      },
      ...(options.from !== undefined ? { from: options.from } : {}),
      ...(deps.log !== undefined ? { log: deps.log } : {}),
      ...(deps.signal !== undefined ? { signal: deps.signal } : {}),
    },
  );
  return {
    bundleDir,
    manifestPath: path.join(bundleDir, BUNDLE_FILES.manifest),
    reportPath: path.join(bundleDir, BUNDLE_REPORT_FILE),
    reports,
  };
}
