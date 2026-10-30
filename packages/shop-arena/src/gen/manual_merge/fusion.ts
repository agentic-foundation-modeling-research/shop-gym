/**
 * Fusion: fits the shop's copy of the Standard sub-manual to the Account
 * and Checkout notes that Storefront exploration observed on the Live
 * storefront.
 *
 * Each observed section goes into the Standard sub-manual section of the
 * same name through one LLM call. The observed notes win on labels, layout
 * and wording; observed behavior that the backend does not support keeps
 * the standard text; and the labels and messages that the browser steps
 * look up stay word for word. The rest of the file is copied unchanged.
 * Without observed notes there is no LLM call, and the copy is the
 * checked-in file.
 */

import { fileURLToPath } from 'node:url';

import { type LlmCall, completeText, loadPrompt } from '../llm.js';
import { parseManualSections } from './prose.js';

/** H2 sections of the Merged manual that fusion consumes, instead of a cut Sub-manual. */
export const FUSED_SECTIONS = ['Account', 'Checkout'] as const;

type FusedSection = (typeof FUSED_SECTIONS)[number];

/**
 * Labels and messages of each fused section that the browser steps (and so
 * the Verifiers and the Final eval) look up on the storefront. A fused
 * section must keep each one, in double quotes, as the standard text has it.
 */
export const CHECKED_LABELS: Readonly<Record<FusedSection, readonly string[]>> = {
  Account: [
    'Forgot your password?',
    "We've sent you an email with a link to update your password.",
    'Order number <order name>',
    'Order <order name>',
    'Add a new address',
    'Add address',
    'Edit address <n>',
    'Update address',
    'Delete <n>',
    'Set as default address',
    'Default',
  ],
  Checkout: ['Enter a valid discount code', 'Total'],
};

/** The Standard sub-manual section that the fusion prompt gets as the backend's limits. */
const SUPPORTED_BEHAVIOR_SECTION = 'Supported behavior';
const PROMPTS_DIR = fileURLToPath(new URL('./prompts/', import.meta.url));

/**
 * The shop's copy of the Standard sub-manual for one Merged manual.
 *
 * @param call LLM settings for the fusion calls.
 * @param standard The checked-in Standard sub-manual.
 * @param manual The Merged `manual.md`.
 * @param log Receives one line for each fused section.
 * @returns `standard` unchanged when `manual` has no observed notes.
 * @throws SynthError when a fused section still breaks a rule after one retry.
 */
export async function fuseStandardSubManual(
  call: LlmCall,
  standard: string,
  manual: string,
  log: (line: string) => void,
): Promise<string> {
  const observed = parseManualSections(manual);
  const standardSections = parseManualSections(standard);
  const supported = standardSections.get(SUPPORTED_BEHAVIOR_SECTION) ?? '';
  let fused = standard;
  for (const section of FUSED_SECTIONS) {
    const notes = observed.get(section)?.trim() ?? '';
    if (notes === '') {
      continue;
    }
    const prompt = loadPrompt(PROMPTS_DIR, 'fuse_standard_section', {
      section,
      standard_section: standardSections.get(section) ?? '',
      observed_section: notes,
      supported_behavior: supported,
      checked_labels: CHECKED_LABELS[section].map((label) => `- "${label}"`).join('\n'),
    });
    const body = await completeText(call, prompt, (reply) => fusedSectionProblem(section, reply));
    fused = replaceSection(fused, section, body);
    log(`[manual_merge] fused the observed ${section} notes into the Standard sub-manual`);
  }
  return fused;
}

/** Why `body` cannot be the fused `section`, or `undefined` when it can. */
function fusedSectionProblem(section: FusedSection, body: string): string | undefined {
  if (/^#{1,2}\s/m.test(body)) {
    return 'the reply has a "#" or "##" heading; write the section body only, with "###" or deeper headings';
  }
  const missing = CHECKED_LABELS[section].filter((label) => !body.includes(`"${label}"`));
  if (missing.length > 0) {
    return `the reply drops the checked label(s) ${missing.map((label) => `"${label}"`).join(', ')}; keep each one word for word, in double quotes`;
  }
  return undefined;
}

/** `markdown` with the body of its `## <section>` replaced by `body`. */
function replaceSection(markdown: string, section: string, body: string): string {
  const headings = [...markdown.matchAll(/^##\s+(.+?)\s*$/gm)];
  const index = headings.findIndex((match) => match[1]?.trim() === section);
  const heading = headings[index];
  if (heading === undefined) {
    throw new Error(`the Standard sub-manual has no "## ${section}" section`);
  }
  // The match can end with the newline after the heading line; the body starts after the line.
  const start = heading.index + heading[0].trimEnd().length;
  const next = headings[index + 1];
  const tail = next === undefined ? '\n' : `\n\n${markdown.slice(next.index)}`;
  return `${markdown.slice(0, start)}\n\n${body}${tail}`;
}
