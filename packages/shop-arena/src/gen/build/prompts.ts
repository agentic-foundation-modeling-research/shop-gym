/**
 * Loads the build-loop prompts (`prompts/*.md`) and renders their
 * `{{name}}` placeholders. The prompt files are plain, self-contained
 * markdown; the only templating is literal placeholder substitution.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

export const VERIFIER_FEEDBACK_PLACEHOLDER = '{{verifier_feedback}}';
const PROMPTS_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), 'prompts');
const PLACEHOLDER_RE = /\{\{([a-z_]+)\}\}/g;

export interface BuildPrompts {
  readonly agentsMd: string;
  readonly planner: string;
  readonly execute: string;
}

export interface BuildPromptValues {
  readonly backendUrl: string;
  readonly genBackend: boolean;
}

export class PromptError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PromptError';
  }
}

/**
 * Replace every `{{name}}` in `text` with `values[name]`.
 *
 * @throws PromptError when a placeholder has no value, except the names in
 *   `keep`, which are left verbatim for a later renderer.
 */
export function renderPlaceholders(
  text: string,
  values: Readonly<Record<string, string>>,
  keep: readonly string[] = [],
): string {
  return text.replace(PLACEHOLDER_RE, (match, name: string) => {
    if (keep.includes(name)) {
      return match;
    }
    const value = values[name];
    if (value === undefined) {
      throw new PromptError(`no value for prompt placeholder {{${name}}}`);
    }
    return value;
  });
}

/** Read and render the three prompt files for one run. */
export async function loadBuildPrompts(values: BuildPromptValues): Promise<BuildPrompts> {
  const substitutions = {
    backend_url: values.backendUrl,
    gen_backend_mode: values.genBackend ? 'enabled' : 'disabled',
  };
  const [agents, planner, execute] = await Promise.all(
    ['agents.md', 'planner.md', 'execute.md'].map((name) =>
      fs.readFile(path.join(PROMPTS_DIR, name), 'utf-8'),
    ),
  );
  const rendered = {
    agentsMd: renderPlaceholders(agents ?? '', substitutions, ['verifier_feedback']),
    planner: renderPlaceholders(planner ?? '', substitutions),
    execute: renderPlaceholders(execute ?? '', substitutions, ['verifier_feedback']),
  };
  if (!rendered.execute.includes(VERIFIER_FEEDBACK_PLACEHOLDER)) {
    throw new PromptError(`execute.md must contain ${VERIFIER_FEEDBACK_PLACEHOLDER}`);
  }
  return rendered;
}
