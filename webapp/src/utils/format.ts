// 顯示格式化工具。

/** 金額：$1,234（無小數，TWD 慣例）。接受字串或數字。 */
export function money(v: string | number): string {
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "$0";
  return "$" + Math.round(n).toLocaleString("en-US");
}

/** 百分比帶正負號與顏色 class。 */
export function pct(n: number): { text: string; cls: "up" | "down" } {
  const sign = n >= 0 ? "+" : "";
  return { text: `${sign}${n.toFixed(1)}%`, cls: n >= 0 ? "up" : "down" };
}

/** 稀有度 → CSS 變數色。 */
export function rarityColor(rarity: string): string {
  const key = rarity.toLowerCase();
  const known = ["sar", "ur", "sr", "ar", "rr", "r", "u", "c"];
  return known.includes(key) ? `var(--rarity-${key})` : "var(--text-secondary)";
}
