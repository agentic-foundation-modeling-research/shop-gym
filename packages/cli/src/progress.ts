/**
 * Progress reporting: pipeline log lines and agent events go to stderr,
 * one line each, so stdout stays reserved for the final result.
 */

import type { AgentEvent } from '@shop-gym/agent';

const EVENT_MAX_CHARS = 200;

export function logLine(line: string): void {
  process.stderr.write(`${line}\n`);
}

export function logEvent(iterId: string, event: AgentEvent): void {
  logLine(`[${iterId}] ${formatEvent(event)}`);
}

/** One-line summary of an agent event. */
export function formatEvent(event: AgentEvent): string {
  switch (event.kind) {
    case 'message':
      return `${event.role}> ${clip(event.text)}`;
    case 'thought':
      return `thinking: ${clip(event.text)}`;
    case 'tool_call':
      return `call ${event.tool} ${clip(JSON.stringify(event.arguments))}`;
    case 'tool_result':
      return `${event.isError ? 'ERROR' : 'result'} ${clip(event.output)}`;
    case 'screenshot':
      return `screenshot ${event.path}`;
    case 'error':
      return `error: ${clip(event.message)}`;
  }
}

function clip(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length <= EVENT_MAX_CHARS ? flat : `${flat.slice(0, EVENT_MAX_CHARS)}...`;
}
