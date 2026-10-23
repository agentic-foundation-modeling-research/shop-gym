import type { Usage } from '@shop-gym/core';

/** Usage record with every counter at zero. */
export const ZERO_USAGE: Usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, costUsd: 0 };
