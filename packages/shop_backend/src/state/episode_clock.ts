/**
 * Deterministic per-episode clock. Every timestamp an episode exposes
 * (customers, sessions, orders, carts) comes from one `EpisodeClock`, never
 * from wall time, so the same action sequence always yields the same
 * timestamps.
 */

/** Default instant every episode clock starts from. */
export const DEFAULT_EPISODE_START = '2026-01-01T00:00:00.000Z';

const TICK_MS = 1_000;

/**
 * Deterministic clock: `now()` is pure; `tick()` advances one second. State
 * methods tick once per mutation so timestamps order events without wall time.
 */
export class EpisodeClock {
  private current: number;

  constructor(private readonly startTime: string = DEFAULT_EPISODE_START) {
    this.current = Date.parse(startTime);
    if (Number.isNaN(this.current)) {
      throw new RangeError(`Invalid episode start time: '${startTime}'`);
    }
  }

  now(): string {
    return new Date(this.current).toISOString();
  }

  tick(): string {
    this.current += TICK_MS;
    return this.now();
  }

  /** `now()` shifted by `ms` milliseconds; does not advance the clock. */
  offset(ms: number): string {
    return new Date(this.current + ms).toISOString();
  }
}
