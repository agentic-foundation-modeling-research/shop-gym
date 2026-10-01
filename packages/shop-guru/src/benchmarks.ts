/**
 * On-disk benchmark layout: one `benchmarks/<skill>.json` per skill under the
 * shop's output directory, each a JSON array of tasks sorted by id.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { type Task, taskSchema } from '@shop-gym/core';
import { z } from 'zod';

const BENCHMARKS_DIR = 'benchmarks';
const tasksFileSchema = z.array(taskSchema);

/** `<shopOutDir>/benchmarks`. */
export function benchmarksDir(shopOutDir: string): string {
  return path.join(shopOutDir, BENCHMARKS_DIR);
}

/**
 * Write `tasks` grouped by skill. Each skill file is merged with what is
 * already there by task id (incoming wins) so seed and explore builds can
 * land in the same directory.
 */
export async function writeBenchmarks(
  shopOutDir: string,
  tasks: readonly Task[],
): Promise<string[]> {
  const dir = benchmarksDir(shopOutDir);
  await fs.mkdir(dir, { recursive: true });
  const bySkill = new Map<string, Task[]>();
  for (const task of tasks) {
    bySkill.set(task.skill, [...(bySkill.get(task.skill) ?? []), task]);
  }
  const written: string[] = [];
  for (const [skill, incoming] of bySkill) {
    const file = path.join(dir, `${skill}.json`);
    const existing = await readTaskFile(file);
    const merged = new Map(existing.map((t) => [t.id, t]));
    for (const task of incoming) merged.set(task.id, task);
    const sorted = [...merged.values()].sort((a, b) => a.id.localeCompare(b.id));
    await fs.writeFile(file, `${JSON.stringify(sorted, null, 2)}\n`);
    written.push(file);
  }
  return written;
}

/** Read every skill file, optionally restricted to `skills`. */
export async function readBenchmarks(
  shopOutDir: string,
  skills?: readonly string[],
): Promise<Task[]> {
  const dir = benchmarksDir(shopOutDir);
  let names: string[];
  try {
    names = (await fs.readdir(dir)).filter((n) => n.endsWith('.json')).sort();
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
  const tasks: Task[] = [];
  for (const name of names) {
    const skill = name.slice(0, -'.json'.length);
    if (skills !== undefined && !skills.includes(skill)) continue;
    tasks.push(...(await readTaskFile(path.join(dir, name))));
  }
  return tasks;
}

async function readTaskFile(file: string): Promise<Task[]> {
  try {
    return tasksFileSchema.parse(JSON.parse(await fs.readFile(file, 'utf-8')));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
}
