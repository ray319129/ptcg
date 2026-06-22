// Screen 4：神秘包商業決策中心。
import { useState } from "react";
import {
  optimizePacks,
  packingListPdfUrl,
  type OptimizeResponse,
  type PackDetail,
} from "../api/endpoints";
import { ApiError } from "../api/http";
import { useApp } from "../store";
import { money, rarityColor } from "../utils/format";
import "./packs.css";

export function MysteryPackScreen() {
  const userId = useApp((s) => s.userId);
  const priceLang = useApp((s) => s.priceLang);
  const [totalPacks, setTotalPacks] = useState(20);
  const [packPrice, setPackPrice] = useState(300);
  const [margin, setMargin] = useState(30); // 顯示為百分比
  const [floorRatio, setFloorRatio] = useState(50);
  const [guaranteedRarity, setGuaranteedRarity] = useState<string>(""); // "" = 不保底
  const [excludeFav, setExcludeFav] = useState(true);

  const [result, setResult] = useState<OptimizeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pdfBusy, setPdfBusy] = useState(false);

  const canGenerate = totalPacks > 0 && packPrice > 0 && margin >= 0 && margin < 100;

  async function generate() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const resp = await optimizePacks({
        user_id: userId,
        total_packs: totalPacks,
        pack_price: packPrice,
        target_margin: margin / 100,
        floor_ratio: floorRatio / 100,
        guaranteed_rarity: guaranteedRarity || null,
        exclude_favorites: excludeFav,
        lang: priceLang,
      });
      setResult(resp);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "產生策略失敗");
    } finally {
      setLoading(false);
    }
  }

  async function exportPdf() {
    if (!result?.plan_id) return;
    setPdfBusy(true);
    try {
      const url = await packingListPdfUrl(result.plan_id, userId);
      window.open(url, "_blank");
      // 釋放交給瀏覽器分頁；稍後 revoke 避免洩漏
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "匯出 PDF 失敗");
    } finally {
      setPdfBusy(false);
    }
  }

  return (
    <div className="screen-pad packs">
      <h2 className="page-title">神秘包決策中心</h2>

      {/* 參數設定 */}
      <section className="surface param-box">
        <NumField label="目標包數 (N)" value={totalPacks} min={1} max={5000}
          onChange={setTotalPacks} />
        <NumField label="每包售價 (P)" value={packPrice} min={1} max={100000}
          step={10} prefix="$" onChange={setPackPrice} />
        <SliderField label="目標毛利率 (M)" value={margin} min={0} max={90}
          suffix="%" onChange={setMargin} />
        <SliderField label="每包底價比 (防雷包)" value={floorRatio} min={0} max={100}
          suffix="%" onChange={setFloorRatio} />
        <label className="field">
          <span className="field-label">每包保底稀有度（市場保底賣法）</span>
          <select className="rarity-select" value={guaranteedRarity}
            onChange={(e) => setGuaranteedRarity(e.target.value)}>
            <option value="">不設保底</option>
            <option value="RR">保底 ≥ RR</option>
            <option value="AR">保底 ≥ AR</option>
            <option value="SR">保底 ≥ SR</option>
            <option value="SAR">保底 ≥ SAR</option>
          </select>
        </label>
        <label className="toggle-row">
          <span>排除最愛卡</span>
          <input type="checkbox" checked={excludeFav}
            onChange={(e) => setExcludeFav(e.target.checked)} />
        </label>
      </section>

      <button className="btn-gold gen-btn" disabled={!canGenerate || loading}
        onClick={generate}>
        {loading ? "運算中…" : "✨ 產生策略"}
      </button>

      {error && <div className="surface error-box mt">{error}</div>}

      {result && <ResultView result={result} onExport={exportPdf} pdfBusy={pdfBusy} />}
    </div>
  );
}

function ResultView(props: {
  result: OptimizeResponse;
  onExport: () => void;
  pdfBusy: boolean;
}) {
  const r = props.result;
  // 庫存消耗率：已配置 / (已配置 + 剩餘)，以價值計。
  const allocated = Number(r.allocated_effective_value);
  const leftover = Number(r.leftover_value);
  const consumption =
    allocated + leftover > 0 ? allocated / (allocated + leftover) : 0;

  return (
    <section className="result mt">
      {/* 可行性橫幅 */}
      <div className={`feasible-banner ${r.feasible ? "ok" : "bad"}`}>
        {r.feasible ? "✓ 方案可行" : "✗ 方案不可行"} — {r.message}
      </div>

      {/* 健康環 + 指標 */}
      <div className="surface health-box">
        <HealthRing pct={consumption} />
        <div className="metrics">
          <Metric label="實現毛利" value={`${(r.realized_margin * 100).toFixed(1)}%`} />
          <Metric label="每包期望值" value={money(r.expected_value_per_pack)} />
          <Metric label="成本預算" value={money(r.budget)} />
          <Metric label="剩餘滯銷"
            value={`${r.leftover_count} 張 / ${money(r.leftover_value)}`} />
        </div>
      </div>

      {/* 獎池摘要（跨所有包彙整） */}
      <TierSummary packs={r.packs} />

      {/* 逐包 Accordion */}
      <div className="block-title">各包明細（{r.packs.length} 包）</div>
      {r.packs.map((p) => <PackRow key={p.pack_index} pack={p} />)}

      {/* 匯出 */}
      <div className="export-row">
        <button className="surface export-btn" disabled={!r.plan_id || props.pdfBusy}
          onClick={props.onExport}>
          {props.pdfBusy ? "產生中…" : "📄 匯出出貨單 PDF"}
        </button>
      </div>
    </section>
  );
}

function TierSummary({ packs }: { packs: PackDetail[] }) {
  const sum = { grand: 0, second: 0, base: 0 };
  for (const p of packs) {
    sum.grand += p.tiers.grand.length;
    sum.second += p.tiers.second.length;
    sum.base += p.tiers.base.length;
  }
  const tiers = [
    { key: "grand", icon: "🏆", label: "頭獎池", n: sum.grand },
    { key: "second", icon: "🥈", label: "二獎池", n: sum.second },
    { key: "base", icon: "🥉", label: "基底池", n: sum.base },
  ];
  return (
    <div className="tier-summary">
      {tiers.map((t) => (
        <div key={t.key} className="surface tier-chip">
          <span className="tier-icon">{t.icon}</span>
          <span className="tier-label">{t.label}</span>
          <span className="tier-n">{t.n} 張</span>
        </div>
      ))}
    </div>
  );
}

function PackRow({ pack }: { pack: PackDetail }) {
  const [open, setOpen] = useState(false);
  const all = [
    ...pack.tiers.grand.map((c) => ({ ...c, tier: "🏆" })),
    ...pack.tiers.second.map((c) => ({ ...c, tier: "🥈" })),
    ...pack.tiers.base.map((c) => ({ ...c, tier: "🥉" })),
  ];
  return (
    <div className="surface pack-row">
      <button className="pack-head" onClick={() => setOpen((o) => !o)}>
        <span>第 {pack.pack_index + 1} 包</span>
        <span className="muted">{all.length} 張</span>
        <span className="mono up">{money(pack.display_value)}</span>
        <span className="chev">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="pack-cards">
          {all.map((c, i) => (
            <div key={`${c.card_id}-${i}`} className="pack-card-line">
              <span>{c.tier}</span>
              <span className="rarity-dot"
                style={{ background: rarityColor(c.rarity) }} />
              <span className="mono pc-code">{c.card_id}</span>
              <span className="pc-name">{c.name_zh}</span>
              <span className="mono">{money(c.market_value)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function HealthRing({ pct }: { pct: number }) {
  const r = 42;
  const c = 2 * Math.PI * r;
  const off = c * (1 - pct);
  return (
    <svg width="110" height="110" viewBox="0 0 110 110" className="ring">
      <circle cx="55" cy="55" r={r} fill="none" stroke="var(--divider)"
        strokeWidth="10" />
      <circle cx="55" cy="55" r={r} fill="none" stroke="var(--brand-gold)"
        strokeWidth="10" strokeLinecap="round" strokeDasharray={c}
        strokeDashoffset={off} transform="rotate(-90 55 55)" />
      <text x="55" y="52" textAnchor="middle" className="ring-num">
        {Math.round(pct * 100)}%
      </text>
      <text x="55" y="68" textAnchor="middle" className="ring-sub">消耗率</text>
    </svg>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <div className="metric-val">{value}</div>
      <div className="metric-lab">{label}</div>
    </div>
  );
}

function NumField(props: {
  label: string; value: number; min: number; max: number; step?: number;
  prefix?: string; onChange: (n: number) => void;
}) {
  return (
    <label className="field">
      <span className="field-label">{props.label}</span>
      <div className="field-input">
        {props.prefix && <span className="field-prefix">{props.prefix}</span>}
        <input type="number" value={props.value} min={props.min} max={props.max}
          step={props.step ?? 1}
          onChange={(e) => props.onChange(Number(e.target.value))} />
      </div>
    </label>
  );
}

function SliderField(props: {
  label: string; value: number; min: number; max: number; suffix?: string;
  onChange: (n: number) => void;
}) {
  return (
    <label className="field">
      <span className="field-label">
        {props.label} <b className="field-val">{props.value}{props.suffix}</b>
      </span>
      <input type="range" value={props.value} min={props.min} max={props.max}
        onChange={(e) => props.onChange(Number(e.target.value))} />
    </label>
  );
}
