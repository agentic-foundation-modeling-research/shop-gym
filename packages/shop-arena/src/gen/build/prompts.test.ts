import { type TaskList, parse, selectNext } from '@shop-gym/harness';
import { describe, expect, it } from 'vitest';

import { PromptError, loadBuildPrompts, renderPlaceholders } from './prompts.js';

/** The task ids of the planner's canonical list, in the order the harness runs them. */
function canonicalRunOrder(planner: string): string[] {
  const section = planner.split('## 2. Canonical task list')[1] ?? '';
  const block = /```\n([\s\S]*?)```/.exec(section)?.[1] ?? '';
  let tasks: TaskList = parse(`## Tasks\n\n${block}`);
  const order: string[] = [];
  for (let next = selectNext(tasks); next !== undefined; next = selectNext(tasks)) {
    const id = next.id;
    order.push(id);
    tasks = tasks.map((task) => (task.id === id ? { ...task, status: 'done' } : task));
  }
  return order;
}

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

describe('planner canonical task list', () => {
  it('restyles the account and checkout pages after the theme and navigation, before visual_fix', async () => {
    const { planner } = await loadBuildPrompts({ backendUrl: 'http://x', genBackend: false });
    expect(canonicalRunOrder(planner)).toEqual([
      'gen_theme',
      'gen_navigation',
      'gen_homepage',
      'gen_collections',
      'gen_product',
      'gen_cart_search',
      'gen_info_pages',
      'gen_account',
      'gen_checkout',
      'visual_fix',
    ]);
  });
});
