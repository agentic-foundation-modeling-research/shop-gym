import { describe, expect, it } from 'vitest';

import { InvalidPlanError, NOTE_PREFIX, diff, parse, selectNext } from './parser.js';

const D = NOTE_PREFIX;

describe('parse', () => {
  it('parses statuses, priorities, and notes', () => {
    const text = `# Plan\n\n## Tasks\n\n- [ ] a [priority: 2] ${D} first\n- [~] b\n- [x] c [priority: -1]\n- [!] d ${D} stuck\n\n## Notes\n\n- [ ] not_a_task\n`;
    expect(parse(text)).toEqual([
      { id: 'a', status: 'pending', priority: 2, note: 'first' },
      { id: 'b', status: 'in_progress', priority: 0, note: null },
      { id: 'c', status: 'done', priority: -1, note: null },
      { id: 'd', status: 'blocked', priority: 0, note: 'stuck' },
    ]);
  });

  it('ignores non-task lines inside the section', () => {
    expect(parse('## Tasks\n\nsome prose\n\n- [ ] a\n')).toHaveLength(1);
  });

  it('rejects a missing tasks section', () => {
    expect(() => parse('# Plan\n')).toThrow("plan.md is missing the '## Tasks' section");
  });

  it('rejects multiple tasks sections', () => {
    expect(() => parse('## Tasks\n- [ ] a\n## Tasks\n- [ ] b\n')).toThrow(
      "multiple '## Tasks' sections in plan.md",
    );
  });

  it('rejects duplicate ids', () => {
    expect(() => parse('## Tasks\n- [ ] a\n- [x] a\n')).toThrow("duplicate task id: 'a'");
  });

  it('rejects malformed task lines', () => {
    expect(() => parse('## Tasks\n- [ ]\n')).toThrow(InvalidPlanError);
    expect(() => parse('## Tasks\n- [?] a\n')).toThrow('unknown status marker [?]');
    expect(() => parse('## Tasks\n- [ ] Bad-Id\n')).toThrow('invalid task id "Bad-Id"');
    expect(() => parse('## Tasks\n- [ ] a trailing\n')).toThrow('unexpected trailing content');
  });
});

describe('selectNext', () => {
  it('prefers the highest priority pending or in-progress task, source order on ties', () => {
    const tasks = parse(
      '## Tasks\n- [x] a [priority: 9]\n- [ ] b\n- [~] c [priority: 1]\n- [ ] d [priority: 1]\n- [!] e [priority: 5]\n',
    );
    expect(selectNext(tasks)?.id).toBe('c');
  });

  it('returns undefined when nothing is selectable', () => {
    expect(selectNext(parse('## Tasks\n- [x] a\n- [!] b\n'))).toBeUndefined();
  });
});

describe('diff', () => {
  it('reports completed, blocked, and added ids', () => {
    const before = parse('## Tasks\n- [ ] a\n- [ ] b\n- [x] c\n');
    const after = parse('## Tasks\n- [x] a\n- [!] b\n- [x] c\n- [ ] d\n');
    expect(diff(before, after)).toEqual({
      completedTaskIds: ['a'],
      blockedTaskIds: ['b'],
      addedTaskIds: ['d'],
    });
  });

  it('throws on resurrected done tasks', () => {
    const before = parse('## Tasks\n- [x] a\n');
    const after = parse('## Tasks\n- [ ] a\n');
    expect(() => diff(before, after)).toThrow("resurrected [x] task ids: ['a']");
  });
});
