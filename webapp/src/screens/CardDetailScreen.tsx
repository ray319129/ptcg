// Screen 3：卡片詳情（目前市值 + 庫存操作；價格走勢已移除）。
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getCardDetail, patchInventory, type CardDetail } from "../api/endpoints";
import { ApiError } from "../api/http";
import { useApp } from "../store";
import { money, rarityColor } from "../utils/format";
import "./cardDetail.css";

export function CardDetailScreen() {
  const { cardId = "" } = useParams();
  const userId = useApp((s) => s.userId);
  const priceLang = useApp((s) => s.priceLang);
  const nav = useNavigate();
  const [data, setData] = useState<CardDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
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

  if (error)
    return (
      <div className="screen-pad">
        <div className="surface error-box">{error}</div>
      </div>
    );
  if (!data) return <div className="screen-pad muted">載入中…</div>;

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

      {/* 估計市值 */}
      <section className="surface price-matrix">
        <div className="pm-main">
          <span className="muted">估計市值</span>
          <span className="pm-price">{money(data.current_price)}</span>
        </div>
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
