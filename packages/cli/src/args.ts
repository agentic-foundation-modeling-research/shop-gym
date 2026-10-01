/**
 * Thin wrapper over `node:util` `parseArgs` that turns parse failures into
 * `CliError`s and adds typed accessors for integers and enumerations.
 */

import { type ParseArgsConfig, parseArgs } from 'node:util';

import { CliError } from './context.js';

type OptionsConfig = NonNullable<ParseArgsConfig['options']>;

export interface ParsedArgs {
  readonly values: Record<string, string | boolean | undefined>;
  readonly positionals: readonly string[];
}

/**
 * Parse `argv` against `options`; positionals are always allowed.
 *
 * @throws CliError on unknown options, missing values, or type mismatches.
 */
export function parse(argv: readonly string[], options: OptionsConfig): ParsedArgs {
  try {
    const { values, positionals } = parseArgs({
      args: [...argv],
      options,
      allowPositionals: true,
      strict: true,
    });
    return { values: values as Record<string, string | boolean | undefined>, positionals };
  } catch (error) {
    if (error instanceof TypeError) {
      throw new CliError(error.message);
    }
    throw error;
  }
}

/** The string value of `--name`, or `undefined` when absent. */
export function stringOption(args: ParsedArgs, name: string): string | undefined {
  const value = args.values[name];
  return typeof value === 'string' ? value : undefined;
}

/** `true` when `--name` was passed. */
export function flag(args: ParsedArgs, name: string): boolean {
  return args.values[name] === true;
}

/**
 * `--name` as a positive integer.
 *
 * @throws CliError when the value is not a positive integer.
 */
export function integerOption(args: ParsedArgs, name: string): number | undefined {
  const raw = stringOption(args, name);
  if (raw === undefined) {
    return undefined;
  }
  return parseInteger(`--${name}`, raw);
}

export function parseInteger(label: string, raw: string): number {
  if (!/^\d+$/.test(raw) || Number(raw) === 0) {
    throw new CliError(`${label} must be a positive integer, got ${JSON.stringify(raw)}`);
  }
  return Number(raw);
}

/**
 * `--name` restricted to `allowed`.
 *
 * @throws CliError listing the allowed values when the value is not one of them.
 */
export function enumOption<T extends string>(
  args: ParsedArgs,
  name: string,
  allowed: readonly T[],
): T | undefined {
  const raw = stringOption(args, name);
  if (raw === undefined) {
    return undefined;
  }
  return parseEnum(`--${name}`, raw, allowed);
}

export function parseEnum<T extends string>(label: string, raw: string, allowed: readonly T[]): T {
  const match = allowed.find((value) => value === raw);
  if (match === undefined) {
    throw new CliError(`${label} must be one of ${allowed.join(', ')}, got ${JSON.stringify(raw)}`);
  }
  return match;
}
