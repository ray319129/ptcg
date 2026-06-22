// Screen 3：卡片詳情與市場趨勢。
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ReactECharts from "echarts-for-react";
import {
  getCardDetail,
  patchInventory,
  type CardDetail,
} from "../api/endpoints";
import { ApiError } from "../api/http";
import { useApp } from "../store";
import { money, rarityColor } from "../utils/format";
import "./cardDetail.css";

type Range = "1W" | "1M" | "3M" | "ALL";
const RANGE_DAYS: Record<Range, number> = { "1W": 7, "1M": 30, "3M": 90, ALL: 9999 };

export function CardDetailScreen() {
  const { cardId = "" } = useParams();
  const userId = useApp((s) => s.userId);
  const priceLang = useApp((s) => s.priceLang);
  const nav = useNavigate();
  const [data, setData] = useState<CardDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<Range>("1M");
  const [qty, setQty] = useState(0);
  const [eligible, setEligible] = useState(true);
  const [fav, setFav] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const ac = new AbortController();
    getCardDetail(cardId, userId, priceLang, ac.signal)
      .then((d) => {
        setData(d);
        setQty(d.owned_qty);
        setEligible(d.pack_eligible);
        setFav(d.is_favorite);
        setError(null);
      })
      .catch((e) => {
        if (e.name !== "AbortError")
          setError(e instanceof ApiError ? e.message : "載入失敗");
      });
    return () => ac.abort();
  }, [cardId, userId, priceLang]);

  const series = useMemo(() => {
    if (!data) return { dates: [] as string[], prices: [] as number[] };
    const cut = RANGE_DAYS[range];
    const all = data.price_history;
    const sliced = cut >= 9999 ? all : all.slice(-cut);
    return {
      dates: sliced.map((p) => p.recorded_date),
      prices: sliced.map((p) => Number(p.price)),
    };
  }, [data, range]);

  async function persist(patch: {
    quantity?: number;
    pack_eligible?: boolean;
    is_favorite?: boolean;
  }) {
    setSaving(true);
    try {
      await patchInventory(userId, cardId, patch);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "更新失敗");
    } finally {
      setSaving(false);
    }
  }

  if (error) return <div className="screen-pad"><div className="surface error-box">{error}</div></div>;
  if (!data) return <div className="screen-pad muted">載入中…</div>;

  const chartOption = {
    grid: { left: 8, right: 12, top: 16, bottom: 24, containLabel: true },
    xAxis: {
      type: "category",
      data: series.dates,
      axisLabel: { color: "#9A9AA2", fontSize: 10 },
      axisLine: { lineStyle: { color: "#2C2C34" } },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: "#9A9AA2", fontSize: 10 },
      splitLine: { lineStyle: { color: "#2C2C34" } },
    },
    tooltip: { trigger: "axis" },
    series: [
      {
        type: "line",
        data: series.prices,
        smooth: true,
        symbol: "none",
        lineStyle: { color: "#FFCB05", width: 2 },
        areaStyle: { color: "rgba(255,203,5,0.12)" },
      },
    ],
  };

  return (
    <div className="screen-pad detail">
      <header className="detail-top">
        <button className="icon-btn" onClick={() => nav(-1)}>‹</button>
        <span className="detail-name">{data.name_zh}</span>
        <button className={`icon-btn${fav ? " on" : ""}`}
          onClick={() => { const n = !fav; setFav(n); void persist({ is_favorite: n }); }}>
          ★
        </button>
      </header>

      {/* metadata badges */}
      <div className="badge-grid">
        <span className="mono badge">Set: {data.set_code}</span>
        <span className="mono badge">No: {data.card_number}</span>
        <span className="mono badge" style={{ color: rarityColor(data.rarity) }}>
          {data.rarity}
        </span>
        <span className="mono badge">流動性 {data.liquidity_score.toFixed(2)}</span>
      </div>

      {/* 估值矩陣 */}
      <section className="surface price-matrix">
        <div className="pm-main">
          <span className="muted">估計市值</span>
          <span className="pm-price">{money(data.current_price)}</span>
        </div>
        <div className="pm-sub">
          <PM label="7 日均價" v={data.avg_7d} />
          <PM label="最高成交" v={data.highest_deal} />
          <PM label="最低掛單" v={data.lowest_ask} />
        </div>
      </section>

      {/* 趨勢圖 + 區間切換 */}
      <section className="surface chart-box">
        <div className="range-tabs">
          {(["1W", "1M", "3M", "ALL"] as Range[]).map((r) => (
            <button key={r} className={`range-tab${range === r ? " on" : ""}`}
              onClick={() => setRange(r)}>{r}</button>
          ))}
        </div>
        {series.prices.length > 1 ? (
          <ReactECharts option={chartOption} style={{ height: 200 }} notMerge />
        ) : (
          <div className="muted no-data">此區間尚無價格資料</div>
        )}
      </section>

      {/* 庫存操作 */}
      <section className="surface inv-actions">
        <div className="stepper-row">
          <span>持有數量</span>
          <div className="stepper">
            <button onClick={() => {
              const n = Math.max(0, qty - 1); setQty(n); void persist({ quantity: n });
            }}>−</button>
            <span className="mono">{qty}</span>
            <button onClick={() => {
              const n = qty + 1; setQty(n); void persist({ quantity: n });
            }}>+</button>
          </div>
        </div>
        <label className="toggle-row">
          <span>納入神秘包資格</span>
          <input type="checkbox" checked={eligible} onChange={(e) => {
            setEligible(e.target.checked); void persist({ pack_eligible: e.target.checked });
          }} />
        </label>
        {saving && <span className="muted saving">儲存中…</span>}
      </section>
    </div>
  );
}

function PM({ label, v }: { label: string; v: string | null }) {
  return (
    <div className="pm-cell">
      <span className="muted">{label}</span>
      <span className="mono">{v ? money(v) : "—"}</span>
    </div>
  );
}
