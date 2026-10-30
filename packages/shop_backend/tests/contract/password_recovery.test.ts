/**
 * Contract: the password-recovery mock. `customerRecover(email)` takes the
 * Storefront API argument and answers with no user errors for every email,
 * known or not, so the answer never tells which emails have an account. It
 * sends nothing and changes no password. Each request moves the Episode
 * clock and shows in the StateSnapshot `passwordResetRequests` with its
 * email and Episode clock time. Each test uses its own episode so requests
 * do not leak between tests.
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { type ContractServer, startContractServer } from './helpers.js';

// Seeded Persona of the fixture.
const MARC = { email: 'marc.tremblay@example.com', password: 'password123' };

let ctx: ContractServer;

beforeAll(async () => {
  ctx = await startContractServer();
});

afterAll(async () => {
  await ctx.server.close();
});

interface RecoverData {
  readonly customerRecover: {
    readonly customerUserErrors: readonly {
      readonly code: string | null;
      readonly message: string;
    }[];
  };
}

async function recover(episode: string, email: string): Promise<RecoverData> {
  const result = await ctx.query<RecoverData>(
    /* GraphQL */ `mutation {
      customerRecover(email: "${email}") {
        customerUserErrors { code message }
      }
    }`,
    episode,
  );
  if (result.data === undefined || result.errors !== undefined) {
    throw new Error(JSON.stringify(result.errors));
  }
  return result.data;
}

describe('customerRecover', () => {
  it('answers with no user errors and records the request at the Episode clock time', async () => {
    const episode = 'recover-known';
    const before = (await ctx.snapshot(episode)).now;

    expect(await recover(episode, MARC.email)).toEqual({
      customerRecover: { customerUserErrors: [] },
    });

    const state = await ctx.snapshot(episode);
    expect(Date.parse(state.now)).toBeGreaterThan(Date.parse(before));
    expect(state.passwordResetRequests).toEqual([{ email: MARC.email, requestedAt: state.now }]);
  });

  it('answers the same for an email with no account, and records it too', async () => {
    const episode = 'recover-unknown';

    expect(await recover(episode, 'nobody@example.com')).toEqual({
      customerRecover: { customerUserErrors: [] },
    });

    const state = await ctx.snapshot(episode);
    expect(state.passwordResetRequests).toEqual([
      { email: 'nobody@example.com', requestedAt: state.now },
    ]);
  });

  it('records the email without the spaces around it', async () => {
    const episode = 'recover-trim';
    await recover(episode, `  ${MARC.email} `);

    const state = await ctx.snapshot(episode);
    expect(state.passwordResetRequests.map((request) => request.email)).toEqual([MARC.email]);
  });

  it('changes no password: the customer still logs in with the old one', async () => {
    const episode = 'recover-password-kept';
    await recover(episode, MARC.email);

    const result = await ctx.query<{
      customerAccessTokenCreate: { customerAccessToken: { accessToken: string } | null };
    }>(
      /* GraphQL */ `mutation {
        customerAccessTokenCreate(input: { email: "${MARC.email}", password: "${MARC.password}" }) {
          customerAccessToken { accessToken }
        }
      }`,
      episode,
    );
    expect(result.data?.customerAccessTokenCreate.customerAccessToken).not.toBeNull();
  });

  it('lists the requests of the episode in request order, and none in another episode', async () => {
    const episode = 'recover-two';
    await recover(episode, MARC.email);
    const first = (await ctx.snapshot(episode)).now;
    await recover(episode, 'nobody@example.com');

    const state = await ctx.snapshot(episode);
    expect(state.passwordResetRequests).toEqual([
      { email: MARC.email, requestedAt: first },
      { email: 'nobody@example.com', requestedAt: state.now },
    ]);
    expect((await ctx.snapshot('recover-other')).passwordResetRequests).toEqual([]);
  });
});
