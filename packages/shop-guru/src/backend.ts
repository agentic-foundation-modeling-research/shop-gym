/**
 * Thin client for the sandbox backend: episode-scoped GraphQL and the
 * `/__shopgym` control API.
 */

import { EPISODE_HEADER, type StateSnapshot, stateSnapshotSchema } from '@shop-gym/shop-backend';

/** The backend answered a request with a non-2xx status or GraphQL errors. */
export class BackendError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'BackendError';
  }
}

/** Requests bound to one backend origin and one episode id. */
export class BackendClient {
  constructor(
    /** Origin such as `http://127.0.0.1:4000`; GraphQL is served at `/graphql`. */
    readonly backendUrl: string,
    readonly episodeId: string,
  ) {}

  /** `POST /__shopgym/episodes/<id>/reset`: re-seed the episode branch. */
  async reset(): Promise<StateSnapshot> {
    return this.control('reset', 'POST');
  }

  /** `GET /__shopgym/episodes/<id>/state`: the grader-facing snapshot. */
  async state(): Promise<StateSnapshot> {
    return this.control('state', 'GET');
  }

  /** Run one GraphQL document under the episode header. Errors throw. */
  async graphql<T>(query: string, variables: Record<string, unknown> = {}): Promise<T> {
    const response = await fetch(new URL('/graphql', this.backendUrl), {
      method: 'POST',
      headers: { 'content-type': 'application/json', [EPISODE_HEADER]: this.episodeId },
      body: JSON.stringify({ query, variables }),
    });
    if (!response.ok) {
      throw new BackendError(`graphql: HTTP ${response.status}`);
    }
    const body = (await response.json()) as { data?: T; errors?: { message: string }[] };
    if (body.errors !== undefined && body.errors.length > 0) {
      throw new BackendError(`graphql: ${body.errors.map((e) => e.message).join('; ')}`);
    }
    if (body.data === undefined) {
      throw new BackendError('graphql: reply has no data');
    }
    return body.data;
  }

  private async control(action: 'reset' | 'state', method: 'POST' | 'GET'): Promise<StateSnapshot> {
    const url = new URL(
      `/__shopgym/episodes/${encodeURIComponent(this.episodeId)}/${action}`,
      this.backendUrl,
    );
    const response = await fetch(url, { method });
    if (!response.ok) {
      throw new BackendError(`${method} ${url.pathname}: HTTP ${response.status}`);
    }
    return stateSnapshotSchema.parse(await response.json());
  }
}
