/** Task-id predicates shared by the verifier set and the owned-file table. */

/** `gen_backend` and any `backend_*` follow-up edit `artifact/backend/`. */
export function isBackendTask(taskId: string): boolean {
  return taskId === 'gen_backend' || taskId.startsWith('backend_');
}
