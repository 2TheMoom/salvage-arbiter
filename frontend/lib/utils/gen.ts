const DECIMALS = 18;
const ONE = BigInt(10) ** BigInt(DECIMALS);

/** 2000000000000000 wei -> "0.002". Trims trailing zeros, keeps at most `places` decimals (rounded down). */
export function formatGen(wei: bigint, places = 6): string {
  const negative = wei < BigInt(0);
  const abs = negative ? -wei : wei;
  const whole = abs / ONE;
  const frac = (abs % ONE).toString().padStart(DECIMALS, "0").slice(0, places).replace(/0+$/, "");
  return `${negative ? "-" : ""}${whole.toString()}${frac ? "." + frac : ""}`;
}

/** "0.002" -> 2000000000000000n. Returns null for anything that is not a positive decimal with at most 18 places. */
export function parseGen(text: string): bigint | null {
  const t = text.trim();
  if (!/^\d+(\.\d{1,18})?$/.test(t)) return null;
  const [whole, frac = ""] = t.split(".");
  const wei = BigInt(whole) * ONE + BigInt(frac.padEnd(DECIMALS, "0"));
  return wei > BigInt(0) ? wei : null;
}
