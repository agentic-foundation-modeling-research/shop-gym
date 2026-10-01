/**
 * The `propose_task` tool the explorer calls once per candidate task, and the
 * `probe` tool it uses to confirm selectors before proposing.
 */

import type { Tool, ToolResult } from '@shop-gym/agent';
import { type BrowserSession, probe } from '@shop-gym/browser';
import { type Task, taskSchema } from '@shop-gym/core';
import { Type } from '@sinclair/typebox';

/** A proposal as the explorer stated it, before verification. */
export interface Proposal {
  readonly task: Task;
  /** Page on which `url: 'last'` probes are verified. */
  readonly verifyUrl: string;
}

const PROPOSE_PARAMS = Type.Object({
  skill: Type.String({ description: 'Skill category for the task.' }),
  goal: Type.String({ description: 'The shopper intent, self-contained.' }),
  eval: Type.Array(Type.Unknown(), { description: 'Checks, see the verification vocabulary.' }),
  verifyUrl: Type.String({
    description: 'Path where probes with url "last" must hold, e.g. "/cart".',
  }),
  setup: Type.Optional(
    Type.Object({
      login: Type.Optional(Type.String({ description: 'Persona id to log in as.' })),
      cart: Type.Optional(
        Type.Array(Type.Object({ variantId: Type.Integer(), quantity: Type.Integer() })),
      ),
    }),
  ),
});

function text(value: string, isError = false): ToolResult {
  return { content: [{ type: 'text', text: value }], isError };
}

/**
 * Build the explorer's extra tools. Accepted proposals are appended to
 * `proposals`; ids are `<shop>-explore-<n>` in proposal order.
 */
export function proposalTools(
  session: BrowserSession,
  shop: string,
  proposals: Proposal[],
): Tool[] {
  const proposeTask: Tool<typeof PROPOSE_PARAMS> = {
    name: 'propose_task',
    description: 'Propose one benchmark task with its verification checks.',
    parameters: PROPOSE_PARAMS,
    async execute(params) {
      const parsed = taskSchema.safeParse({
        id: `${shop}-explore-${proposals.length + 1}`,
        shop,
        skill: params.skill,
        goal: params.goal,
        ...(params.setup === undefined ? {} : { setup: params.setup }),
        eval: params.eval,
        source: 'explore',
      });
      if (!parsed.success) {
        const issue = parsed.error.issues[0];
        return text(`Rejected: ${issue?.path.join('.')} ${issue?.message ?? 'invalid'}`, true);
      }
      proposals.push({ task: parsed.data, verifyUrl: params.verifyUrl });
      return text(`Recorded ${parsed.data.id}.`);
    },
  };
  const probeTool: Tool = {
    name: 'probe',
    description:
      'Count elements matching a Playwright selector on the current page and return their text.',
    parameters: Type.Object({ locator: Type.String({ description: 'Playwright selector.' }) }),
    async execute(params) {
      const { locator } = params as { locator: string };
      try {
        const found = await probe(session, locator);
        return text(JSON.stringify(found));
      } catch (error) {
        return text(`Error: ${error instanceof Error ? error.message : String(error)}`, true);
      }
    },
  };
  return [proposeTask, probeTool];
}
