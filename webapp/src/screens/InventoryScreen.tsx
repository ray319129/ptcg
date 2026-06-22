// 庫存清單：搜尋 / 篩選 / 點入詳情。
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  getInventory,
  inventoryCsvUrl,
  type InventoryItem,
} from "../api/endpoints";
import { ApiError } from "../api/http";
import { useApp } from "../store";
import { money, rarityColor } from "../utils/format";
import "./inventory.css";

export function InventoryScreen() {
  const userId = useApp((s) => s.userId);
  const priceLang = useApp((s) => s.priceLang);
  const nav = useNavigate();
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [q, setQ] = useState("");
  const [favOnly, setFavOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    getInventory(
      userId,
      { limit: 200, favoritesOnly: favOnly, lang: priceLang },
      ac.signal,
    )
      .then((p) => {
        setItems(p.items);
        setError(null);
      })
      .catch((e) => {
        if (e.name !== "AbortError")
          setError(e instanceof ApiError ? e.message : "載入失敗");
      })
      .finally(() => setLoading(false));
    return () => ac.abort();
  }, [userId, favOnly, priceLang]);

  const filtered = useMemo(() => {
    const kw = q.trim().toUpperCase();
    if (!kw) return items;
    return items.filter(
      (it) =>
        it.name_zh.includes(q.trim()) ||
        it.card_id.toUpperCase().includes(kw) ||
        `${it.set_code} ${it.card_number}`.toUpperCase().includes(kw),
    );
  }, [items, q]);

  return (
    <div className="screen-pad inventory">
      <div className="inv-header">
        <h2 className="page-title">庫存</h2>
        <button
          className="chip csv-btn"
          disabled={items.length === 0}
          onClick={async () => {
            try {
              const url = await inventoryCsvUrl(userId, priceLang);
              const a = document.createElement("a");
              a.href = url;
              a.download = "inventory.csv";
              a.click();
              setTimeout(() => URL.revokeObjectURL(url), 30_000);
            } catch {
              /* ignore */
            }
          }}
        >
          ⬇ 匯出 CSV
        </button>
      </div>
      <div className="inv-controls">
        <input className="search" placeholder="搜尋卡名或卡號…" value={q}
          onChange={(e) => setQ(e.target.value)} />
        <button className={`chip${favOnly ? " on" : ""}`}
          onClick={() => setFavOnly((f) => !f)}>
          ★ 最愛
        </button>
      </div>

      {loading && <div className="muted">載入中…</div>}
      {error && <div className="surface error-box">{error}</div>}
      {!loading && !error && filtered.length === 0 && (
        <div className="muted empty">沒有符合的卡片</div>
      )}

      <div className="inv-list">
        {filtered.map((it) => (
          <button key={it.card_id} className="surface inv-row"
            onClick={() => nav(`/cards/${encodeURIComponent(it.card_id)}`)}>
            <span className="rarity-tag"
              style={{ background: rarityColor(it.rarity) }}>{it.rarity}</span>
            <div className="inv-main">
              <span className="inv-name">{it.name_zh}</span>
              <span className="mono inv-code">
                {it.set_code} {it.card_number}
              </span>
            </div>
            <div className="inv-right">
              <span className="mono up">{money(it.market_value)}</span>
              <span className="muted">×{it.quantity}</span>
            </div>
            {it.is_favorite && <span className="fav">★</span>}
          </button>
        ))}
      </div>
    </div>
  );
}
