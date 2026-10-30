/**
 * Merges the prose of several `manual.md` files section by section.
 *
 * Sections are the H2 headings. A section only one seed wrote is copied
 * verbatim; sections with several contributions go through the injected
 * `mergeSection` callback (an LLM call in production).
 */

export const CANONICAL_SECTIONS = [
  'Overview',
  'Site shell',
  'Homepage',
  'Collections & navigation',
  'Product page',
  'Cart',
  'Search',
  'Internationalization',
  'Floating UX',
  'Policy & info pages',
  'UX Patterns Summary',
] as const;

const FALLBACK_DESCRIPTOR = 'Generic Storefront';
/** An H2 heading line; group 1 is the section name. */
const H2_HEADING = /^##\s+(.+?)\s*$/gm;

/** `## heading` -> body (without the heading), in document order. Preamble and the H1 are dropped. */
export function parseManualSections(markdown: string): Map<string, string> {
  const sections = new Map<string, string>();
  const headings = [...markdown.matchAll(H2_HEADING)];
  headings.forEach((match, i) => {
    const start = match.index + match[0].length;
    const end = headings[i + 1]?.index ?? markdown.length;
    sections.set((match[1] as string).trim(), markdown.slice(start, end).replace(/^\n+|\s+$/g, ''));
  });
  return sections;
}

/**
 * `markdown` with the body of its `## <name>` section replaced by `body`;
 * every other byte stays the same.
 *
 * @throws Error when `markdown` has no `## <name>` section.
 */
export function replaceManualSection(markdown: string, name: string, body: string): string {
  const headings = [...markdown.matchAll(H2_HEADING)];
  const index = headings.findIndex((match) => (match[1] as string).trim() === name);
  const heading = headings[index];
  if (heading === undefined) {
    throw new Error(`no "## ${name}" section`);
  }
  // The match can end with the newline after the heading line; the body starts after the line.
  const start = heading.index + heading[0].trimEnd().length;
  const next = headings[index + 1];
  const tail = next === undefined ? '\n' : `\n\n${markdown.slice(next.index)}`;
  return `${markdown.slice(0, start)}\n\n${body}${tail}`;
}

/** Canonical sections present in any seed first, then the rest in first-seen order. */
export function sectionOrder(seeds: readonly Map<string, string>[]): string[] {
  const present = new Set(seeds.flatMap((s) => [...s.keys()]));
  const canonical = CANONICAL_SECTIONS.filter((name) => present.has(name));
  const extra: string[] = [];
  for (const seed of seeds) {
    for (const name of seed.keys()) {
      if (!CANONICAL_SECTIONS.includes(name as (typeof CANONICAL_SECTIONS)[number])) {
        if (!extra.includes(name)) extra.push(name);
      }
    }
  }
  return [...canonical, ...extra];
}

export type SectionMerger = (
  section: string,
  contributions: readonly { seed: string; body: string }[],
) => Promise<string>;

/** Renders a manual with the H1 `# Shop Manual - <descriptor>` and the given sections. */
export function renderManualDocument(
  descriptor: string | null | undefined,
  sections: readonly (readonly [string, string])[],
): string {
  const title = descriptor?.trim() ? descriptor.trim() : FALLBACK_DESCRIPTOR;
  const lines = [`# Shop Manual - ${title}`, ''];
  for (const [name, body] of sections) {
    lines.push(`## ${name}`, '', body.trimEnd(), '');
  }
  return `${lines.join('\n').trimEnd()}\n`;
}

/**
 * Merges seed manuals.
 *
 * @param manuals Seed `manual.md` texts in seed order.
 * @param descriptor Merged `shop.descriptor` for the H1.
 * @param mergeSection Called for every section with two or more non-blank contributions.
 */
export async function mergeManualProse(
  manuals: readonly string[],
  descriptor: string | null | undefined,
  mergeSection: SectionMerger,
): Promise<string> {
  const parsed = manuals.map(parseManualSections);
  const sections: (readonly [string, string])[] = [];
  for (const name of sectionOrder(parsed)) {
    const contributions = parsed.flatMap((seed, i) => {
      const body = seed.get(name);
      return body !== undefined && body.trim() !== '' ? [{ seed: `seed_${i}`, body }] : [];
    });
    let body = '';
    if (contributions.length === 1) {
      body = (contributions[0] as { body: string }).body;
    } else if (contributions.length > 1) {
      body = (await mergeSection(name, contributions)).replace(/^\n+|\s+$/g, '');
      if (body === '') {
        throw new Error(`section ${JSON.stringify(name)}: merged body is empty`);
      }
    }
    sections.push([name, body]);
  }
  return renderManualDocument(descriptor, sections);
}

/** Formats seed contributions as `### seed_i` blocks for the merge prompt. */
export function seedBlocks(contributions: readonly { seed: string; body: string }[]): string {
  return contributions.map((c) => `### ${c.seed}\n\n${c.body}`.trimEnd()).join('\n\n');
}
