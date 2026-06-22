// 庫存清單：附圖、清單/圖卡切換、排序分組、多選批次編輯、一鍵清空。
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  bulkInventory,
  clearInventory,
  getInventory,
  inventoryCsvUrl,
  type InventoryItem,
} from "../api/endpoints";
import { ApiError } from "../api/http";
import { useApp } from "../store";
import { money, rarityColor } from "../utils/format";
import "./inventory.css";

type ViewMode = "list" | "grid";
type SortKey = "value" | "name" | "qty" | "rarity" | "set";
type GroupKey = "none" | "set" | "rarity";

const SORT_LABEL: Record<SortKey, string> = {
  value: "價值",
  name: "名稱",
  qty: "數量",
  rarity: "稀有度",
  set: "系列",
};
const GROUP_LABEL: Record<GroupKey, string> = {
  none: "不分組",
  set: "依系列",
  rarity: "依稀有度",
};

// 稀有度高→低排序權重；未知排最後。
const RARITY_RANK: Record<string, number> = {
  sar: 0, mur: 1, ur: 2, sr: 3, ar: 4, rr: 5, r: 6, u: 7, c: 8,
};
const rarityRank = (r: string) => RARITY_RANK[r.toLowerCase()] ?? 99;

export function InventoryScreen() {
  const userId = useApp((s) => s.userId);
  const priceLang = useApp((s) => s.priceLang);
  const nav = useNavigate();
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [q, setQ] = useState("");
  const [favOnly, setFavOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  const [view, setView] = useState<ViewMode>(
    () => (localStorage.getItem("inv_view") as ViewMode) ?? "list",
  );
  const [sort, setSort] = useState<SortKey>(
    () => (localStorage.getItem("inv_sort") as SortKey) ?? "value",
  );
  const [group, setGroup] = useState<GroupKey>(
    () => (localStorage.getItem("inv_group") as GroupKey) ?? "none",
  );

  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);

  useEffect(() => localStorage.setItem("inv_view", view), [view]);
  useEffect(() => localStorage.setItem("inv_sort", sort), [sort]);
  useEffect(() => localStorage.setItem("inv_group", group), [group]);

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
  }, [userId, favOnly, priceLang, reload]);

  function flash(msg: string) {
    setToast(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2400);
  }

  // 搜尋過濾 → 排序。
  const filtered = useMemo(() => {
    const kw = q.trim().toUpperCase();
    const base = !kw
      ? items
      : items.filter(
          (it) =>
            it.name_zh.includes(q.trim()) ||
            it.card_id.toUpperCase().includes(kw) ||
            `${it.set_code} ${it.card_number}`.toUpperCase().includes(kw),
        );
    const sorted = [...base].sort((a, b) => {
      switch (sort) {
        case "name":
          return a.name_zh.localeCompare(b.name_zh, "zh-Hant");
        case "qty":
          return b.quantity - a.quantity;
        case "rarity":
          return rarityRank(a.rarity) - rarityRank(b.rarity);
        case "set":
          return (
            a.set_code.localeCompare(b.set_code) ||
            a.card_number.localeCompare(b.card_number, undefined, {
              numeric: true,
            })
          );
        case "value":
        default:
          return Number(b.market_value) - Number(a.market_value);
      }
    });
    return sorted;
  }, [items, q, sort]);

  // 分組（含「不分組」單一群）。
  const groups = useMemo(() => {
    if (group === "none") return [{ key: "", list: filtered }];
    const map = new Map<string, InventoryItem[]>();
    for (const it of filtered) {
      const k = group === "set" ? it.set_code : it.rarity;
      const arr = map.get(k);
      if (arr) arr.push(it);
      else map.set(k, [it]);
    }
    return [...map.entries()].map(([key, list]) => ({ key, list }));
  }, [filtered, group]);

  const visibleIds = useMemo(() => filtered.map((it) => it.card_id), [filtered]);
  const allSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));

  function toggleSel(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }
  function selectAll() {
    setSelected(allSelected ? new Set() : new Set(visibleIds));
  }
  function exitSelect() {
    setSelectMode(false);
    setSelected(new Set());
  }

  async function runBulk(
    patch: { is_favorite?: boolean; pack_eligible?: boolean; delete?: boolean },
    label: string,
  ) {
    const ids = [...selected];
    if (ids.length === 0) return;
    setBusy(true);
    try {
      const res = await bulkInventory(userId, ids, patch);
      flash(`${label}：${res.affected} 張`);
      exitSelect();
      setReload((n) => n + 1);
    } catch (e) {
      flash(e instanceof ApiError ? e.message : "批次操作失敗");
    } finally {
      setBusy(false);
    }
  }

  async function doClearAll() {
    if (
      !window.confirm(
        `確定清空整個收藏嗎？共 ${items.length} 種卡片將被移除，無法復原。`,
      )
    )
      return;
    setBusy(true);
    try {
      const res = await clearInventory(userId);
      flash(`已清空 ${res.affected} 種卡片`);
      exitSelect();
      setReload((n) => n + 1);
    } catch (e) {
      flash(e instanceof ApiError ? e.message : "清空失敗");
    } finally {
      setBusy(false);
    }
  }

  function onCardClick(it: InventoryItem) {
    if (selectMode) toggleSel(it.card_id);
    else nav(`/cards/${encodeURIComponent(it.card_id)}`);
  }

  return (
    <div className="screen-pad inventory">
      <div className="inv-header">
        <h2 className="page-title">庫存</h2>
        <div className="inv-header-btns">
          <button className="chip add-btn" onClick={() => nav("/search")}>
            ＋ 加入卡片
          </button>
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
            ⬇ CSV
          </button>
          <button
            className="chip danger-btn"
            disabled={items.length === 0 || busy}
            onClick={doClearAll}
          >
            🗑 清空
          </button>
        </div>
      </div>

      <div className="inv-controls">
        <input
          className="search"
          placeholder="搜尋卡名或卡號…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button
          className={`chip${favOnly ? " on" : ""}`}
          onClick={() => setFavOnly((f) => !f)}
        >
          ★ 最愛
        </button>
      </div>

      <div className="inv-controls inv-controls-2">
        <button
          className="chip"
          onClick={() => setView((v) => (v === "list" ? "grid" : "list"))}
          title="切換顯示方式"
        >
          {view === "list" ? "▦ 圖卡" : "▤ 清單"}
        </button>
        <label className="inv-select-wrap">
          排序
          <select
            className="inv-select"
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
          >
            {(Object.keys(SORT_LABEL) as SortKey[]).map((k) => (
              <option key={k} value={k}>
                {SORT_LABEL[k]}
              </option>
            ))}
          </select>
        </label>
        <label className="inv-select-wrap">
          分組
          <select
            className="inv-select"
            value={group}
            onChange={(e) => setGroup(e.target.value as GroupKey)}
          >
            {(Object.keys(GROUP_LABEL) as GroupKey[]).map((k) => (
              <option key={k} value={k}>
                {GROUP_LABEL[k]}
              </option>
            ))}
          </select>
        </label>
        <button
          className={`chip${selectMode ? " on" : ""}`}
          onClick={() => (selectMode ? exitSelect() : setSelectMode(true))}
        >
          {selectMode ? "取消" : "☑ 選取"}
        </button>
      </div>

      {loading && <div className="muted">載入中…</div>}
      {error && <div className="surface error-box">{error}</div>}
      {!loading && !error && filtered.length === 0 && (
        <div className="muted empty">沒有符合的卡片</div>
      )}

      {groups.map(({ key, list }) => (
        <section key={key || "_all"} className="inv-group">
          {key && (
            <div className="inv-group-head">
              <span
                className="inv-group-name"
                style={
                  group === "rarity"
                    ? { color: rarityColor(key) }
                    : undefined
                }
              >
                {key}
              </span>
              <span className="muted">{list.length} 種</span>
            </div>
          )}
          <div className={view === "grid" ? "inv-grid" : "inv-list"}>
            {list.map((it) =>
              view === "grid" ? (
                <GridCard
                  key={it.card_id}
                  it={it}
                  selectMode={selectMode}
                  checked={selected.has(it.card_id)}
                  onClick={() => onCardClick(it)}
                />
              ) : (
                <ListRow
                  key={it.card_id}
                  it={it}
                  selectMode={selectMode}
                  checked={selected.has(it.card_id)}
                  onClick={() => onCardClick(it)}
                />
              ),
            )}
          </div>
        </section>
      ))}

      {selectMode && (
        <div className="inv-batchbar">
          <div className="batch-top">
            <button className="chip" onClick={selectAll}>
              {allSelected ? "取消全選" : "全選"}
            </button>
            <span className="muted">已選 {selected.size}</span>
          </div>
          <div className="batch-actions">
            <button
              className="chip"
              disabled={busy || selected.size === 0}
              onClick={() => runBulk({ is_favorite: true }, "已設為最愛")}
            >
              ★ 最愛
            </button>
            <button
              className="chip"
              disabled={busy || selected.size === 0}
              onClick={() => runBulk({ is_favorite: false }, "已取消最愛")}
            >
              ☆ 取消
            </button>
            <button
              className="chip"
              disabled={busy || selected.size === 0}
              onClick={() => runBulk({ pack_eligible: true }, "已納入神秘包")}
            >
              🎁 納入
            </button>
            <button
              className="chip"
              disabled={busy || selected.size === 0}
              onClick={() => runBulk({ pack_eligible: false }, "已排除神秘包")}
            >
              🚫 排除
            </button>
            <button
              className="chip danger-btn"
              disabled={busy || selected.size === 0}
              onClick={() => {
                if (window.confirm(`刪除選取的 ${selected.size} 張卡片？`))
                  void runBulk({ delete: true }, "已刪除");
              }}
            >
              🗑 刪除
            </button>
          </div>
        </div>
      )}

      {toast && <div className="inv-toast">{toast}</div>}
    </div>
  );
}

function Thumb({ it }: { it: InventoryItem }) {
  return (
    <div className="inv-thumb">
      {it.image_url ? (
        <img src={it.image_url} alt={it.name_zh} loading="lazy" />
      ) : (
        <span className="inv-noimg">無圖</span>
      )}
    </div>
  );
}

function ListRow({
  it,
  selectMode,
  checked,
  onClick,
}: {
  it: InventoryItem;
  selectMode: boolean;
  checked: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className={`surface inv-row${checked ? " sel" : ""}`}
      onClick={onClick}
    >
      {selectMode && (
        <span className={`inv-check${checked ? " on" : ""}`}>
          {checked ? "✓" : ""}
        </span>
      )}
      <Thumb it={it} />
      <div className="inv-main">
        <span className="inv-name">{it.name_zh}</span>
        <span className="mono inv-code">
          {it.set_code} {it.card_number}
        </span>
        <span
          className="rarity-tag inv-rarity"
          style={{ background: rarityColor(it.rarity) }}
        >
          {it.rarity}
        </span>
      </div>
      <div className="inv-right">
        <span className="mono up">{money(it.market_value)}</span>
        <span className="muted">×{it.quantity}</span>
      </div>
      {it.is_favorite && <span className="fav">★</span>}
    </button>
  );
}

function GridCard({
  it,
  selectMode,
  checked,
  onClick,
}: {
  it: InventoryItem;
  selectMode: boolean;
  checked: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className={`surface inv-cell${checked ? " sel" : ""}`}
      onClick={onClick}
    >
      <div className="inv-cell-img">
        {it.image_url ? (
          <img src={it.image_url} alt={it.name_zh} loading="lazy" />
        ) : (
          <span className="inv-noimg">無圖</span>
        )}
        {selectMode && (
          <span className={`inv-check${checked ? " on" : ""}`}>
            {checked ? "✓" : ""}
          </span>
        )}
        {it.is_favorite && <span className="cell-fav">★</span>}
        <span className="cell-qty">×{it.quantity}</span>
      </div>
      <div className="inv-cell-info">
        <span className="inv-name">{it.name_zh}</span>
        <span className="mono up">{money(it.market_value)}</span>
      </div>
    </button>
  );
}
