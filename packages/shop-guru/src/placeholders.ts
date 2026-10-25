/**
 * The only templating prompts get: `{{name}}` substitution.
 */

/** Replace every `{{name}}` in `template`; a name without a value throws. */
export function fillPlaceholders(
  template: string,
  values: Readonly<Record<string, string>>,
): string {
  return template.replace(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g, (_, name: string) => {
    const value = values[name];
    if (value === undefined) {
      throw new Error(`prompt placeholder "{{${name}}}" has no value`);
    }
    return value;
  });
}
