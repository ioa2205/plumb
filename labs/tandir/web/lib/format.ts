export function sum(cents: number): string {
  return `${(cents / 100).toLocaleString("en-US", { minimumFractionDigits: 0 })} so'm`;
}
