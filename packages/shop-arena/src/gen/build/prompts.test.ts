import { describe, expect, it } from 'vitest';

import { PromptError, loadBuildPrompts, renderPlaceholders } from './prompts.js';

describe('renderPlaceholders', () => {
  it('substitutes known names and keeps listed ones verbatim', () => {
    expect(renderPlaceholders('a {{x}} {{keep}}', { x: '1' }, ['keep'])).toBe('a 1 {{keep}}');
  });

  it('throws on an unknown placeholder', () => {
    expect(() => renderPlaceholders('{{nope}}', {})).toThrow(PromptError);
  });
});

describe('loadBuildPrompts', () => {
  it('renders the backend URL and mode and keeps the verifier feedback slot', async () => {
    const prompts = await loadBuildPrompts({
      backendUrl: 'http://127.0.0.1:4555',
      genBackend: true,
    });
    expect(prompts.agentsMd).toContain('http://127.0.0.1:4555/graphql');
    expect(prompts.agentsMd).toContain('**enabled**');
    expect(prompts.planner).toContain('gen_backend');
    expect(prompts.planner).toContain('[priority: 10]');
    expect(prompts.execute).toContain('{{verifier_feedback}}');
    expect(prompts.execute).not.toContain('{{backend_url}}');
    const disabled = await loadBuildPrompts({ backendUrl: 'http://x', genBackend: false });
    expect(disabled.planner).toContain('**disabled**');
  });
});
