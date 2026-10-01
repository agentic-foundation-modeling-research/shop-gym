import { describe, expect, it } from 'vitest';

import { parse } from './parser.js';
import { mergeProtocolResults, runProtocolChecks } from './protocol.js';
import type { Task } from './tasks.js';

function check(before: string, after: string | Task[], selectedTaskId = 'a') {
  return runProtocolChecks({
    iterId: 'exec-0001',
    before: parse(before),
    after: typeof after === 'string' ? parse(after) : after,
    selectedTaskId,
  });
}

describe('runProtocolChecks', () => {
  it('passes a clean completion', () => {
    const result = check('## Tasks\n- [ ] a\n- [ ] b\n', '## Tasks\n- [x] a\n- [ ] b\n- [ ] c\n');
    expect(result).toEqual({ iterId: 'exec-0001', passed: true, violations: [] });
  });

  it('flags a non-terminal selected task', () => {
    expect(check('## Tasks\n- [ ] a\n', '## Tasks\n- [ ] a\n').violations).toEqual([
      "selected task 'a' is not terminal in after snapshot (status='pending')",
    ]);
  });

  it('flags a missing selected task', () => {
    expect(check('## Tasks\n- [ ] a\n', '## Tasks\n- [ ] b\n').violations).toEqual([
      "selected task 'a' is missing from after snapshot",
    ]);
  });

  it('flags resurrection and non-selected terminal transitions', () => {
    const result = check(
      '## Tasks\n- [ ] a\n- [x] b\n- [ ] c\n',
      '## Tasks\n- [x] a\n- [ ] b\n- [!] c\n',
    );
    expect(result.violations).toEqual([
      "resurrected [x] task ids: ['b']",
      "non-selected tasks newly marked terminal: ['c']",
    ]);
  });

  it('flags added tasks that are not pending', () => {
    expect(check('## Tasks\n- [ ] a\n', '## Tasks\n- [x] a\n- [x] z\n').violations).toEqual([
      "non-selected tasks newly marked terminal: ['z']",
      "newly added tasks are not PENDING: ['z']",
    ]);
  });

  it('flags duplicate ids in a raw after snapshot', () => {
    const dup: Task = { id: 'a', status: 'done', priority: 0, note: null };
    expect(check('## Tasks\n- [ ] a\n', [dup, dup]).violations).toEqual([
      "duplicate task ids in after snapshot: ['a']",
    ]);
  });
});

describe('mergeProtocolResults', () => {
  it('concatenates violations and skips undefined', () => {
    const merged = mergeProtocolResults('exec-0002', [
      { iterId: 'exec-0002', passed: false, violations: ['x'] },
      undefined,
      { iterId: 'exec-0002', passed: true, violations: [] },
    ]);
    expect(merged).toEqual({ iterId: 'exec-0002', passed: false, violations: ['x'] });
  });
});
