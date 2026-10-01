import { describe, expect, it } from 'vitest';

import { buildModelsConfig, providerApiKey } from './model-runtime.js';

describe('buildModelsConfig', () => {
  it('writes only base-url overrides, never keys', () => {
    const config = buildModelsConfig({
      anthropicBaseUrl: 'https://gw.example/anthropic',
      anthropicApiKey: 'sk-secret',
      piProxyApiKey: 'proxy-secret',
    });
    expect(config).toEqual({
      providers: { anthropic: { baseUrl: 'https://gw.example/anthropic' } },
    });
    expect(JSON.stringify(config)).not.toContain('secret');
  });

  it('is empty when no routing is configured', () => {
    expect(buildModelsConfig({ openaiApiKey: 'k' })).toEqual({ providers: {} });
  });
});

describe('providerApiKey', () => {
  it('prefers the proxy key when the provider is routed through a gateway', () => {
    const credentials = {
      openaiBaseUrl: 'https://gw',
      openaiApiKey: 'direct',
      piProxyApiKey: 'proxy',
    };
    expect(providerApiKey('openai', credentials)).toBe('proxy');
  });

  it('ignores the proxy key when the provider is not routed', () => {
    expect(providerApiKey('openai', { openaiApiKey: 'direct', piProxyApiKey: 'proxy' })).toBe(
      'direct',
    );
  });

  it('falls back to the anthropic auth token', () => {
    expect(providerApiKey('anthropic', { anthropicAuthToken: 'tok' })).toBe('tok');
  });

  it('is undefined for unknown providers', () => {
    expect(providerApiKey('mistral', { openaiApiKey: 'k' })).toBeUndefined();
  });
});
