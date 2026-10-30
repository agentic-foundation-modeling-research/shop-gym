/**
 * Rules every Discount code of a Dataset must follow, shared by data
 * synthesis (to reject an LLM reply) and data validation (to reject a
 * Dataset).
 */

import type { DiscountCode } from '@shop-gym/shop-backend';

/**
 * A readable problem for each rule that `codes` break: codes are unique
 * when case is ignored, percent and fixed amounts are positive, percents
 * are below 100, and minimums are not negative. The amount of a
 * free-shipping code is not used, so it is not checked.
 */
export function checkDiscountCodes(codes: readonly DiscountCode[]): string[] {
  const problems: string[] = [];
  const seen = new Set<string>();
  for (const { code, kind, amount, minimum_subtotal: minimum } of codes) {
    const key = code.toUpperCase();
    if (seen.has(key)) problems.push(`Discount code ${code} repeats a code when case is ignored`);
    seen.add(key);
    if (kind !== 'free_shipping' && !(Number(amount) > 0)) {
      problems.push(`Discount code ${code} amount ${amount} is not positive`);
    }
    if (kind === 'percentage' && Number(amount) >= 100) {
      problems.push(`Discount code ${code} percent ${amount} is not below 100`);
    }
    if (minimum !== null && !(Number(minimum) >= 0)) {
      problems.push(`Discount code ${code} minimum_subtotal ${minimum} is not zero or more`);
    }
  }
  return problems;
}
