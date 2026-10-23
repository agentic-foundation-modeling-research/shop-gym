/**
 * Pure doctor checks: each takes already-probed facts and returns a result
 * with a remedy, so the report is testable without touching the machine.
 */

export interface CheckResult {
  readonly name: string;
  readonly ok: boolean;
  readonly detail: string;
  readonly remedy?: string;
}

/** Facts the `doctor` command gathers before running the checks. */
export interface DoctorFacts {
  /** `process.versions.node`. */
  readonly nodeVersion: string;
  /** `pnpm --version` output, or `undefined` when pnpm is not on PATH. */
  readonly pnpmVersion: string | undefined;
  /** Playwright's Chromium executable path and whether it exists. */
  readonly chromium: { readonly path: string; readonly exists: boolean } | undefined;
  readonly storefrontTemplate: { readonly dir: string; readonly exists: boolean };
  readonly backendTemplate: { readonly dir: string; readonly exists: boolean };
  readonly envFile: { readonly path: string; readonly exists: boolean };
  /** Credential field names `loadCredentials` resolved (never values). */
  readonly credentialKeys: readonly string[];
}

const MIN_NODE = [20, 12] as const;

export function runChecks(facts: DoctorFacts): CheckResult[] {
  return [
    checkNode(facts.nodeVersion),
    checkPnpm(facts.pnpmVersion),
    checkChromium(facts.chromium),
    checkTemplate('storefront template', facts.storefrontTemplate),
    checkTemplate('backend template', facts.backendTemplate),
    checkEnv(facts.envFile, facts.credentialKeys),
  ];
}

export function checkNode(version: string): CheckResult {
  const [major = 0, minor = 0] = version.split('.').map(Number);
  const ok = major > MIN_NODE[0] || (major === MIN_NODE[0] && minor >= MIN_NODE[1]);
  return {
    name: 'node',
    ok,
    detail: `v${version}`,
    ...(ok ? {} : { remedy: `Install Node >= ${MIN_NODE.join('.')} (https://nodejs.org).` }),
  };
}

export function checkPnpm(version: string | undefined): CheckResult {
  return version === undefined
    ? { name: 'pnpm', ok: false, detail: 'not on PATH', remedy: 'Run `corepack enable`.' }
    : { name: 'pnpm', ok: true, detail: `v${version}` };
}

export function checkChromium(chromium: DoctorFacts['chromium']): CheckResult {
  const remedy = 'Run `pnpm exec playwright install chromium` from the repo root.';
  if (chromium === undefined) {
    return { name: 'playwright chromium', ok: false, detail: 'playwright not resolvable', remedy };
  }
  return chromium.exists
    ? { name: 'playwright chromium', ok: true, detail: chromium.path }
    : { name: 'playwright chromium', ok: false, detail: `missing ${chromium.path}`, remedy };
}

export function checkTemplate(
  name: string,
  template: { readonly dir: string; readonly exists: boolean },
): CheckResult {
  return template.exists
    ? { name, ok: true, detail: template.dir }
    : {
        name,
        ok: false,
        detail: `missing ${template.dir}`,
        remedy: 'Restore the template from git (`git checkout -- packages/`).',
      };
}

export function checkEnv(
  envFile: { readonly path: string; readonly exists: boolean },
  credentialKeys: readonly string[],
): CheckResult {
  const keys = credentialKeys.length > 0 ? `keys: ${credentialKeys.join(', ')}` : 'no keys found';
  const source = envFile.exists ? envFile.path : 'no .env (shell environment only)';
  if (credentialKeys.length === 0) {
    return {
      name: 'credentials',
      ok: false,
      detail: `${source}; ${keys}`,
      remedy: 'Run `cp .env.example .env` and fill in the provider keys.',
    };
  }
  return { name: 'credentials', ok: true, detail: `${source}; ${keys}` };
}

/** One line per check, followed by remedies for the failed ones. */
export function formatReport(results: readonly CheckResult[]): string {
  const width = Math.max(...results.map((r) => r.name.length));
  const lines = results.map(
    (r) => `${r.ok ? 'ok  ' : 'FAIL'} ${r.name.padEnd(width)}  ${r.detail}`,
  );
  const failed = results.filter((r) => !r.ok);
  if (failed.length > 0) {
    lines.push('');
    for (const r of failed) {
      lines.push(`${r.name}: ${r.remedy ?? 'no remedy known'}`);
    }
  }
  return `${lines.join('\n')}\n`;
}
