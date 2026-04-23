import { describe, expect, it } from 'vitest';
import { createSchema } from './schema.js';
import { createYoga } from 'graphql-yoga';

describe('schema', () => {
  it('responds to ping', async () => {
    const yoga = createYoga({ schema: createSchema() });
    const response = await yoga.fetch('http://yoga/graphql', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: '{ ping }' })
    });
    const result = await response.json();
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({ ping: 'pong' });
  });
});
