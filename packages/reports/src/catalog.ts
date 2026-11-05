/**
 * The report catalog: the HTML report files in one directory, with the date,
 * title and description of each.
 *
 * A report file is named `YYYY-MM-DD-<slug>.html` and holds an HTML fragment,
 * not a full document. The fragment starts with a head block of `<title>` and
 * `<meta>` tags, which must include `<meta name="description">`. The rest of
 * the fragment (report styles, markup and scripts) is the body. The site shell
 * writes the doctype, `<head>` and `<body>` around it.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

/** `YYYY-MM-DD-<slug>.html`, where the slug is lowercase kebab-case. */
export const REPORT_FILE_RE = /^(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)\.html$/;

/** The leading run of `<title>` and `<meta>` tags, with the whitespace between them. */
const HEAD_BLOCK_RE = /^(?:\s*(?:<title>[\s\S]*?<\/title>|<meta\b[^>]*>))+/i;
const TITLE_RE = /<title>([\s\S]*?)<\/title>/i;
const META_RE = /<meta\b[^>]*>/gi;
const DOCUMENT_TAG_RE = /<!doctype\b|<(?:html|head|body)[\s>]/i;

const NAMED_ENTITIES: Readonly<Record<string, string>> = {
  amp: '&',
  lt: '<',
  gt: '>',
  quot: '"',
  apos: "'",
  nbsp: ' ',
};

/** A report file that does not follow the report page contract. */
export class ReportFormatError extends Error {
  constructor(file: string, problem: string) {
    super(`${file}: ${problem}`);
    this.name = 'ReportFormatError';
  }
}

/** A report fragment split into the parts the site shell needs. */
export interface ReportPage {
  /** Plain text of the `<title>`. */
  readonly title: string;
  /** Plain text of `<meta name="description">`. */
  readonly description: string;
  /** The fragment after the head block. */
  readonly body: string;
}

/** One report file, read and parsed. */
export interface Report extends ReportPage {
  /** File name; the report is served at `/<file>`. */
  readonly file: string;
  /** `YYYY-MM-DD` from the file name. */
  readonly date: string;
}

/**
 * Split a report fragment into its title, description and body.
 *
 * @param file Name used in error messages.
 * @throws ReportFormatError when the fragment is a full document, or when its
 *   head block has no non-empty `<title>` or `<meta name="description">`.
 */
export function parseReport(file: string, html: string): ReportPage {
  if (DOCUMENT_TAG_RE.test(html)) {
    throw new ReportFormatError(
      file,
      'is a full document; remove the doctype, <html>, <head> and <body> tags',
    );
  }
  const head = HEAD_BLOCK_RE.exec(html)?.[0] ?? '';
  const title = decodeEntities(TITLE_RE.exec(head)?.[1] ?? '').trim();
  if (title === '') {
    throw new ReportFormatError(file, 'must start with a non-empty <title>');
  }
  const description = descriptionOf(head);
  if (description === '') {
    throw new ReportFormatError(
      file,
      'needs a non-empty <meta name="description"> next to its <title>',
    );
  }
  return { title, description, body: html.slice(head.length).trimStart() };
}

/**
 * Read and parse the report `file` in `dir`.
 *
 * @returns `undefined` when `file` is not a report file name or does not exist.
 * @throws ReportFormatError when the report does not follow the page contract.
 */
export async function readReport(dir: string, file: string): Promise<Report | undefined> {
  const date = REPORT_FILE_RE.exec(file)?.[1];
  if (date === undefined) {
    return undefined;
  }
  let html: string;
  try {
    html = await fs.readFile(path.join(dir, file), 'utf8');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return undefined;
    }
    throw error;
  }
  return { file, date, ...parseReport(file, html) };
}

/**
 * Every report in `dir`, newest first; reports with the same date are sorted
 * by file name. Files whose names do not match `REPORT_FILE_RE` are skipped.
 *
 * @throws ReportFormatError when a report does not follow the page contract.
 */
export async function listReports(dir: string): Promise<Report[]> {
  const files = await fs.readdir(dir);
  const reports = await Promise.all(files.map((file) => readReport(dir, file)));
  return reports
    .filter((report): report is Report => report !== undefined)
    .sort((a, b) => b.date.localeCompare(a.date) || a.file.localeCompare(b.file));
}

function descriptionOf(head: string): string {
  for (const tag of head.match(META_RE) ?? []) {
    if (attribute(tag, 'name')?.toLowerCase() === 'description') {
      return decodeEntities(attribute(tag, 'content') ?? '').trim();
    }
  }
  return '';
}

function attribute(tag: string, name: string): string | undefined {
  const match = new RegExp(`\\s${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)')`, 'i').exec(tag);
  return match?.[1] ?? match?.[2];
}

function decodeEntities(text: string): string {
  return text.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (entity, code: string) => {
    if (code[0] === '#') {
      const point =
        code[1] === 'x' || code[1] === 'X'
          ? Number.parseInt(code.slice(2), 16)
          : Number(code.slice(1));
      return String.fromCodePoint(point);
    }
    return NAMED_ENTITIES[code.toLowerCase()] ?? entity;
  });
}
