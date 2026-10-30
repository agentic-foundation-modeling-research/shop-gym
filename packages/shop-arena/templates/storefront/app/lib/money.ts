/** A Storefront API money amount, such as `"19.99"`, in integer cents. */
export function toCents(amount: string): number {
  return Math.round(Number.parseFloat(amount) * 100);
}
