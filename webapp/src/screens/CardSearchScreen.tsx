// 手動加入庫存：用卡名或卡號搜尋卡片百科 → 選數量 → 加入庫存。
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  addInventory,
  searchCards,
  type CardSearchItem,
} from "../api/endpoints";
import { ApiError } from "../api/http";
import { useApp } from "../store";
import { money, rarityColor } from "../utils/format";
import "./cardSearch.css";

export function CardSearchScreen() {
  const userId = useApp((s) => s.userId);
  const priceLang = useApp((s) => s.priceLang);
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<CardSearchItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  // 目前展開數量器的 card_id，及其待加入數量。
  const [openId, setOpenId] = useState<string | null>(null);
  const [qty, setQty] = useState(1);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  // 輸入防抖：停止打字 350ms 後才查詢。
  useEffect(() => {
    const kw = q.trim();
    if (!kw) {
      setResults([]);
      setSearched(false);
      setError(null);
      return;
    }
    const ac = new AbortController();
    const t = setTimeout(() => {
      setLoading(true);
      searchCards(kw, userId, priceLang, 20, ac.signal)
        .then((r) => {
          setResults(r);
          setError(null);
          setSearched(true);
        })
        .catch((e) => {
          if (e.name !== "AbortError")
            setError(e instanceof ApiError ? e.message : "搜尋失敗");
        })
        .finally(() => setLoading(false));
    }, 350);
    return () => {
      clearTimeout(t);
      ac.abort();
    };
  }, [q, userId, priceLang]);

  const toastTimer = useRef<number | undefined>(undefined);
  function flash(msg: string) {
    setToast(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2200);
  }

  function toggle(card: CardSearchItem) {
    if (openId === card.card_id) {
      setOpenId(null);
    } else {
      setOpenId(card.card_id);
      setQty(1);
    }
  }

  async function add(card: CardSearchItem) {
    setSaving(true);
    try {
      const res = await addInventory(userId, card.card_id, qty);
      // 更新本地持有數，讓使用者看到結果。
      setResults((rs) =>
        rs.map((r) =>
          r.card_id === card.card_id
            ? { ...r, owned_qty: res.new_quantity }
            : r,
        ),
      );
      setOpenId(null);
      flash(`已加入 ${card.name_zh} ×${qty}（持有 ${res.new_quantity}）`);
    } catch (e) {
      flash(e instanceof ApiError ? e.message : "加入失敗");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="screen-pad card-search">
      <header className="cs-header">
        <button className="icon-btn" onClick={() => nav(-1)}>
          ‹
        </button>
        <h2 className="page-title">加入卡片</h2>
      </header>

      <input
        className="search"
        autoFocus
        placeholder="搜尋卡名或卡號（如 皮卡丘 / M5_001）…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />

      {loading && <div className="muted cs-status">搜尋中…</div>}
      {error && <div className="surface error-box cs-status">{error}</div>}
      {!loading && !error && searched && results.length === 0 && (
        <div className="muted empty">查無符合的卡片</div>
      )}
      {!searched && !loading && (
        <div className="muted empty">輸入卡名或卡號開始搜尋</div>
      )}

      <div className="cs-list">
        {results.map((c) => {
          const open = openId === c.card_id;
          return (
            <div key={c.card_id} className="surface cs-card">
              <button className="cs-row" onClick={() => toggle(c)}>
                <div className="cs-thumb">
                  {c.image_url ? (
                    <img src={c.image_url} alt={c.name_zh} loading="lazy" />
                  ) : (
                    <span className="cs-noimg">無圖</span>
                  )}
                </div>
                <div className="cs-main">
                  <span className="cs-name">{c.name_zh}</span>
                  <span className="mono cs-code">
                    {c.set_code} {c.card_number}
                  </span>
                  <span
                    className="rarity-tag cs-rarity"
                    style={{ background: rarityColor(c.rarity) }}
                  >
                    {c.rarity}
                  </span>
                </div>
                <div className="cs-right">
                  <span className="mono up">{money(c.market_value)}</span>
                  {c.owned_qty > 0 && (
                    <span className="muted cs-owned">持有 ×{c.owned_qty}</span>
                  )}
                </div>
              </button>

              {open && (
                <div className="cs-add">
                  <div className="stepper">
                    <button
                      onClick={() => setQty((n) => Math.max(1, n - 1))}
                    >
                      −
                    </button>
                    <span className="mono">{qty}</span>
                    <button onClick={() => setQty((n) => Math.min(999, n + 1))}>
                      +
                    </button>
                  </div>
                  <button
                    className="chip cs-add-btn"
                    disabled={saving}
                    onClick={() => void add(c)}
                  >
                    {saving ? "加入中…" : `加入庫存 ×${qty}`}
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {toast && <div className="cs-toast">{toast}</div>}
    </div>
  );
}
