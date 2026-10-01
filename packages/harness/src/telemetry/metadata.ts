/** Per-iteration sidecar written to `iters/<iterId>/metadata.json`. */

import { z } from 'zod';

export const iterationMetadataSchema = z.object({
  iterId: z.string(),
  iterKind: z.enum(['plan', 'exec']),
  runtime: z.string(),
  startedAt: z.string(),
  endedAt: z.string(),
  /** Absent for the planner iteration. */
  selectedTaskId: z.string().nullable(),
  completedTaskIds: z.array(z.string()),
  blockedTaskIds: z.array(z.string()),
  addedTaskIds: z.array(z.string()),
});

export type IterationMetadata = z.infer<typeof iterationMetadataSchema>;
