import { describe, expect, it } from 'vitest';

import { NOTE_PREFIX } from './parser.js';
import { blockTask, reopenTask } from './rewrite.js';

const D = NOTE_PREFIX;

describe('reopenTask', () => {
  it('rewrites [x] and [!] markers to [~] for the given id only', () => {
    const text = '## Tasks\n- [x] a\n- [!] ab\n- [x] b\n';
    expect(reopenTask(text, 'a')).toBe('## Tasks\n- [~] a\n- [!] ab\n- [x] b\n');
    expect(reopenTask(text, 'ab')).toBe('## Tasks\n- [x] a\n- [~] ab\n- [x] b\n');
  });

  it('leaves pending tasks and unrelated text untouched', () => {
    const text = '## Tasks\r\n- [ ] a\r\nprose a\r\n';
    expect(reopenTask(text, 'a')).toBe(text);
  });
});

describe('blockTask', () => {
  it('marks the task blocked, keeps the priority tag, and replaces the note', () => {
    const text = `## Tasks\n- [ ] a [priority: 3] ${D} old\n- [ ] b\n`;
    expect(blockTask(text, 'a', 'protocol_violation: x')).toBe(
      `## Tasks\n- [!] a [priority: 3] ${D} protocol_violation: x\n- [ ] b\n`,
    );
  });

  it('returns undefined when the task line is absent', () => {
    expect(blockTask('## Tasks\n- [ ] b\n', 'a', 'n')).toBeUndefined();
  });
});
