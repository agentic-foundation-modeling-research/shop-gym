/** Conservative secret scrubber for the `configSnapshot` in `run.json`. */

export const REDACTED = '***REDACTED***';
const SECRET_KEY_RE = /secret|token|password|passwd|api[_-]?key|access[_-]?key|auth|credential/i;

/**
 * Deep copy `value`, replacing the value of any object key that looks
 * secret-shaped with `***REDACTED***`. Substring matching on purpose: a
 * false positive like `authorize` is cheaper than a leaked token.
 */
export function scrubSecrets(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(scrubSecrets);
  }
  if (value !== null && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [key, sub] of Object.entries(value)) {
      out[key] = SECRET_KEY_RE.test(key) ? REDACTED : scrubSecrets(sub);
    }
    return out;
  }
  return value;
}
