// Screen 1：儀表板與即時投資組合。
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getPortfolioSummary, type PortfolioSummary } from "../api/endpoints";
import { ApiError } from "../api/http";
import { useApp } from "../store";
import { money, rarityColor } from "../utils/format";
import "./dashboard.css";

export function DashboardScreen() {
  const userId = useApp((s) => s.userId);
  const username = useApp((s) => s.username);
  const priceLang = useApp((s) => s.priceLang);
  const toggleTheme = useApp((s) => s.toggleTheme);
  const logout = useApp((s) => s.logout);
  const nav = useNavigate();
  const [data, setData] = useState<PortfolioSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    getPortfolioSummary(userId, priceLang, ac.signal)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if (e.name !== "AbortError")
          setError(e instanceof ApiError ? e.message : "載入失敗");
      })
      .finally(() => setLoading(false));
    return () => ac.abort();
  }, [userId, priceLang]);

  if (loading) return <div className="screen-pad muted">載入中…</div>;
  if (error)
    return (
      <div className="screen-pad">
        <div className="surface error-box">{error}</div>
      </div>
    );
  if (!data) return null;

  return (
    <div className="screen-pad dashboard">
      {/* Header */}
      <header className="dash-header">
        <div className="avatar">🧑‍💼</div>
        <span className="dash-username">{username}</span>
        <div className="spacer" />
        <button className="chip" onClick={toggleTheme}>
          TWD ◎
        </button>
        <button className="chip" onClick={logout}>
          登出
        </button>
      </header>

      {/* 資產淨值 Hero */}
      <section className="surface hero">
        <div className="hero-label">總資產淨值</div>
        <div className="hero-net">{money(data.net_worth)}</div>
      </section>

      {/* 快捷操作 */}
      <section className="quick-bar">
        <button className="surface qa" onClick={() => nav("/inventory")}>
          🔍<span>手動搜尋</span>
        </button>
        <button className="qa-main btn-gold" onClick={() => nav("/scan")}>
          📷 即時掃描
        </button>
        <button className="surface qa" onClick={() => nav("/packs")}>
          🎁<span>建立神秘包</span>
        </button>
      </section>

      {/* 統計四宮格 */}
      <section className="stat-grid">
        <StatCard label="總卡數" value={data.total_cards.toLocaleString()} />
        <StatCard
          label="SAR/UR 佔比"
          value={`${Math.round(
            (data.rarity_distribution
              .filter((r) => ["SAR", "UR"].includes(r.rarity.toUpperCase()))
              .reduce((s, r) => s + r.pct, 0)) * 100,
          )}%`}
        />
        <StatCard
          label="平均流動性"
          value={data.avg_liquidity.toFixed(2)}
        />
        <StatCard
          label="滯銷警示"
          value={String(data.dead_stock_count)}
          alert={data.dead_stock_count > 0}
        />
      </section>

      {/* 稀有度分布條 */}
      <section className="surface rarity-bar-box">
        <div className="block-title">稀有度分布</div>
        <div className="rarity-bar">
          {data.rarity_distribution.map((r) => (
            <div
              key={r.rarity}
              className="rarity-seg"
              style={{
                width: `${r.pct * 100}%`,
                background: rarityColor(r.rarity),
              }}
              title={`${r.rarity} ${Math.round(r.pct * 100)}%`}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

function StatCard(props: { label: string; value: string; alert?: boolean }) {
  return (
    <div className={`surface stat-card${props.alert ? " alert" : ""}`}>
      <div className="stat-value">{props.value}</div>
      <div className="stat-label">{props.label}</div>
    </div>
  );
}
