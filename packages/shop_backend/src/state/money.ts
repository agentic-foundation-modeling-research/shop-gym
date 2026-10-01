/**
 * Integer-cent money arithmetic shared by cart and order pricing. Dataset
 * prices are decimal strings ("12.99"); all sums are done in cents so totals
 * never accumulate floating-point drift.
 */

/** Parse a fixed-decimal money string (e.g. "12.99") into integer cents. */
export function toCents(amount: string): number {
  const value = Number.parseFloat(amount);
  if (!Number.isFinite(value)) return 0;
  return Math.round(value * 100);
}

/** Render integer cents as a two-decimal money string. */
export function fromCents(cents: number): string {
  return (cents / 100).toFixed(2);
}
