import { describe, expect, it } from 'vitest';

import {
  type DoctorFacts,
  checkChromium,
  checkEnv,
  checkNode,
  checkPnpm,
  checkTemplate,
  formatReport,
  runChecks,
} from './checks.js';

const OK_FACTS: DoctorFacts = {
  nodeVersion: '22.1.0',
  pnpmVersion: '9.12.0',
  chromium: { path: '/x/chrome', exists: true },
  storefrontTemplate: { dir: '/t/storefront', exists: true },
  backendTemplate: { dir: '/t/backend', exists: true },
  envFile: { path: '/r/.env', exists: true },
  credentialKeys: ['openaiApiKey', 'piProxyApiKey'],
};

describe('doctor checks', () => {
  it('accepts Node >= 20.12 and rejects older versions with a remedy', () => {
    expect(checkNode('20.12.0').ok).toBe(true);
    expect(checkNode('24.15.0').ok).toBe(true);
    const old = checkNode('20.11.1');
    expect(old.ok).toBe(false);
    expect(old.remedy).toContain('20.12');
    expect(checkNode('18.20.0').ok).toBe(false);
  });

  it('reports pnpm missing from PATH', () => {
    expect(checkPnpm('9.12.0')).toEqual({ name: 'pnpm', ok: true, detail: 'v9.12.0' });
    expect(checkPnpm(undefined)).toMatchObject({
      ok: false,
      remedy: expect.stringContaining('corepack'),
    });
  });

  it('reports a missing Chromium executable', () => {
    expect(checkChromium({ path: '/x', exists: true }).ok).toBe(true);
    expect(checkChromium({ path: '/x', exists: false })).toMatchObject({
      ok: false,
      detail: 'missing /x',
      remedy: expect.stringContaining('playwright install chromium'),
    });
    expect(checkChromium(undefined).ok).toBe(false);
  });

  it('reports a missing template directory', () => {
    expect(checkTemplate('backend template', { dir: '/b', exists: false })).toMatchObject({
      ok: false,
      detail: 'missing /b',
    });
  });

  it('lists credential key names and fails only when none were found', () => {
    const found = checkEnv({ path: '/r/.env', exists: true }, ['openaiApiKey']);
    expect(found.ok).toBe(true);
    expect(found.detail).toBe('/r/.env; keys: openaiApiKey');
    const shellOnly = checkEnv({ path: '/r/.env', exists: false }, ['anthropicApiKey']);
    expect(shellOnly.ok).toBe(true);
    expect(shellOnly.detail).toContain('shell environment only');
    expect(checkEnv({ path: '/r/.env', exists: false }, [])).toMatchObject({
      ok: false,
      remedy: expect.stringContaining('.env.example'),
    });
  });

  it('runs every check and formats failures with remedies', () => {
    expect(runChecks(OK_FACTS).every((r) => r.ok)).toBe(true);
    const results = runChecks({ ...OK_FACTS, pnpmVersion: undefined, credentialKeys: [] });
    const report = formatReport(results);
    expect(report).toContain('ok   node');
    expect(report).toContain('FAIL pnpm');
    expect(report).toContain('pnpm: Run `corepack enable`.');
    expect(report).toContain('credentials: Run `cp .env.example .env`');
    expect(report).not.toContain('node:');
  });
});
