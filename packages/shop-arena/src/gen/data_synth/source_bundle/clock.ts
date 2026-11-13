/**
 * The time shift of a Source bundle shop. A bundle keeps the times of its
 * source. The shop moves every time by one whole number of days, so that
 * the bundle cutoff falls on the Episode clock start: history is before
 * the clock start, and the hidden User events are after it.
 */

import { DEFAULT_EPISODE_START } from '@shop-gym/shop-backend';

import type { SourceBundle } from './read.js';

const DAY_MS = 86_400_000;

export interface BundleClock {
  /** The bundle cutoff, as the bundle gives it. */
  readonly cutoff: string;
  /**
   * Whole days that the shop adds to every bundle time. The shifted cutoff
   * is the Episode clock start, or less than one day before it when the
   * cutoff is not at midnight UTC.
   */
  readonly offsetDays: number;
}

export function bundleClock(cutoff: string): BundleClock {
  return {
    cutoff,
    offsetDays: Math.floor((Date.parse(DEFAULT_EPISODE_START) - Date.parse(cutoff)) / DAY_MS),
  };
}

/** True for a time before the cutoff: shop history. A time at the cutoff or later is hidden. */
export function isBeforeCutoff(clock: BundleClock, time: string): boolean {
  return Date.parse(time) < Date.parse(clock.cutoff);
}

/** `time` moved by the clock offset, as an ISO 8601 string in UTC. */
export function shiftTime(clock: BundleClock, time: string): string {
  return new Date(Date.parse(time) + clock.offsetDays * DAY_MS).toISOString();
}

/**
 * The shifted time at which each product or user first shows in the shop
 * history: its reviews before the cutoff and its User events before the
 * cutoff. One that never shows gets the shifted cutoff.
 */
export function firstSeen(
  bundle: SourceBundle,
  field: 'product_id' | 'user_id',
): (id: string) => string {
  const first = new Map<string, number>();
  const see = (id: string | undefined, time: string): void => {
    if (id === undefined) return;
    const ms = Date.parse(time);
    first.set(id, Math.min(first.get(id) ?? ms, ms));
  };
  for (const review of bundle.reviews) see(review[field], review.created_at);
  for (const event of bundle.events) {
    if (isBeforeCutoff(bundle.clock, event.timestamp)) see(event[field], event.timestamp);
  }
  return (id) => {
    const ms = first.get(id);
    return shiftTime(
      bundle.clock,
      ms === undefined ? bundle.clock.cutoff : new Date(ms).toISOString(),
    );
  };
}
