// 全部 API 型別與呼叫函式（對齊 backend app/schemas）。

import { apiBlobUrl, apiGet, apiPatch, apiPost } from "./http";

// ---- 帳號 -----------------------------------------------------------------
export interface AuthResult {
  user_id: string;
  username: string;
}
export const register = (username: string, password: string) =>
  apiPost<AuthResult>("/api/v1/auth/register", { username, password });
export const login = (username: string, password: string) =>
  apiPost<AuthResult>("/api/v1/auth/login", { username, password });

/** 庫存 CSV 匯出網址（blob）。 */
export const inventoryCsvUrl = (userId: string, lang: "tw" | "jp") =>
  apiBlobUrl(
    `/api/v1/inventory/export.csv?user_id=${encodeURIComponent(userId)}&lang=${lang}`,
  );

// ---- Portfolio / Dashboard -------------------------------------------------
export interface RarityRatio {
  rarity: string;
  count: number;
  pct: number;
}
export interface PortfolioSummary {
  net_worth: string;
  total_cards: number;
  rarity_distribution: RarityRatio[];
  avg_liquidity: number;
  dead_stock_count: number;
}

export const getPortfolioSummary = (
  userId: string,
  lang: "tw" | "jp" = "tw",
  signal?: AbortSignal,
) =>
  apiGet<PortfolioSummary>(
    `/api/v1/portfolio/summary?user_id=${encodeURIComponent(userId)}&lang=${lang}`,
    signal,
  );

// ---- Inventory -------------------------------------------------------------
export interface InventoryItem {
  card_id: string;
  set_code: string;
  card_number: string;
  name_zh: string;
  rarity: string;
  quantity: number;
  market_value: string;
  liquidity_score: number;
  is_favorite: boolean;
  pack_eligible: boolean;
  image_url: string | null;
}
export interface InventoryPage {
  items: InventoryItem[];
  total: number;
  limit: number;
  offset: number;
}
export const getInventory = (
  userId: string,
  opts: {
    limit?: number;
    offset?: number;
    favoritesOnly?: boolean;
    lang?: "tw" | "jp";
  } = {},
  signal?: AbortSignal,
) => {
  const q = new URLSearchParams({ user_id: userId });
  if (opts.limit) q.set("limit", String(opts.limit));
  if (opts.offset) q.set("offset", String(opts.offset));
  if (opts.favoritesOnly) q.set("favorites_only", "true");
  q.set("lang", opts.lang ?? "tw");
  return apiGet<InventoryPage>(`/api/v1/inventory?${q}`, signal);
};

export interface InventoryAddResult {
  card_id: string;
  new_quantity: number;
  name_zh: string;
  rarity: string;
  market_value: string;
}
/** 掃描自動入庫：同卡累加數量。 */
export const addInventory = (
  userId: string,
  cardId: string,
  quantity = 1,
) =>
  apiPost<InventoryAddResult>("/api/v1/inventory/add", {
    user_id: userId,
    card_id: cardId,
    quantity,
  });

export interface InventoryPatch {
  quantity?: number;
  is_favorite?: boolean;
  pack_eligible?: boolean;
}
export const patchInventory = (
  userId: string,
  cardId: string,
  patch: InventoryPatch,
) =>
  apiPatch<void>(
    `/api/v1/inventory/${encodeURIComponent(cardId)}?user_id=${encodeURIComponent(userId)}`,
    patch,
  );

// ---- Card catalog search (手動加入庫存) ------------------------------------
export interface CardSearchItem {
  card_id: string;
  set_code: string;
  card_number: string;
  rarity: string;
  name_zh: string;
  image_url: string | null;
  market_value: string;
  owned_qty: number;
}
/** 用卡名或卡號搜尋卡片百科（供手動加入庫存）。 */
export const searchCards = (
  q: string,
  userId: string,
  lang: "tw" | "jp" = "tw",
  limit = 20,
  signal?: AbortSignal,
) => {
  const params = new URLSearchParams({ q, lang, limit: String(limit) });
  if (userId) params.set("user_id", userId);
  return apiGet<CardSearchItem[]>(`/api/v1/cards/search?${params}`, signal);
};

export interface BulkResult {
  affected: number;
}
/** 批次編輯選取的庫存卡（最愛 / 神秘包資格 / 刪除）。 */
export const bulkInventory = (
  userId: string,
  cardIds: string[],
  patch: { is_favorite?: boolean; pack_eligible?: boolean; delete?: boolean },
) =>
  apiPost<BulkResult>("/api/v1/inventory/bulk", {
    user_id: userId,
    card_ids: cardIds,
    ...patch,
  });

/** 一鍵清空整個收藏。 */
export const clearInventory = (userId: string) =>
  apiPost<BulkResult>("/api/v1/inventory/clear", { user_id: userId });

// ---- Card detail -----------------------------------------------------------
export interface CardDetail {
  card_id: string;
  set_code: string;
  card_number: string;
  rarity: string;
  name_zh: string;
  current_price: string;
  liquidity_score: number;
  owned_qty: number;
  is_favorite: boolean;
  pack_eligible: boolean;
}
export const getCardDetail = (
  cardId: string,
  userId?: string,
  lang: "tw" | "jp" = "tw",
  signal?: AbortSignal,
) => {
  const q = new URLSearchParams();
  if (userId) q.set("user_id", userId);
  q.set("lang", lang);
  return apiGet<CardDetail>(
    `/api/v1/cards/${encodeURIComponent(cardId)}?${q}`,
    signal,
  );
};

// ---- Mystery pack optimize -------------------------------------------------
export interface CardLine {
  card_id: string;
  name_zh: string;
  rarity: string;
  market_value: string;
}
export interface TierBreakdown {
  grand: CardLine[];
  second: CardLine[];
  base: CardLine[];
}
export interface PackDetail {
  pack_index: number;
  display_value: string;
  effective_value: string;
  tiers: TierBreakdown;
}
export interface OptimizeResponse {
  plan_id: string | null;
  feasible: boolean;
  message: string;
  budget: string;
  allocated_effective_value: string;
  expected_value_per_pack: string;
  realized_margin: number;
  floor_per_pack: string;
  total_packs: number;
  pack_price: string;
  target_margin: number;
  packs: PackDetail[];
  leftover_count: number;
  leftover_value: string;
}
export interface OptimizeRequest {
  user_id: string;
  total_packs: number;
  pack_price: number;
  target_margin: number;
  floor_ratio?: number;
  guaranteed_rarity?: string | null;
  exclude_favorites?: boolean;
  lang?: "tw" | "jp";
}
export const optimizePacks = (req: OptimizeRequest, signal?: AbortSignal) =>
  apiPost<OptimizeResponse>("/api/v1/packs/optimize", req, signal);

// ---- 影像比對掃描 ---------------------------------------------------------
export interface MatchCandidate {
  card_id: string;
  set_code: string;
  card_number: string;
  rarity: string;
  name_zh: string;
  image_url: string | null;
  market_value: string;
  in_collection_count: number;
  similarity: number;
}
export interface MatchResponse {
  success: boolean;
  best: MatchCandidate | null;
  candidates: MatchCandidate[];
  detected: boolean;
  needs_pick: boolean;
  message: string;
}
/** 上傳拍到的卡片影像，回傳最相近的卡（及候選）。lang 指定卡價語言版本。 */
export async function matchCard(
  blob: Blob,
  userId: string,
  lang: "tw" | "jp" = "tw",
  signal?: AbortSignal,
): Promise<MatchResponse> {
  const fd = new FormData();
  fd.append("image", blob, "capture.jpg");
  fd.append("user_id", userId);
  fd.append("lang", lang);
  const base = import.meta.env.VITE_API_BASE ?? "";
  const res = await fetch(`${base}/api/v1/scan/match`, {
    method: "POST",
    body: fd,
    signal,
  });
  if (!res.ok) throw new Error(`比對失敗：${res.status}`);
  return (await res.json()) as MatchResponse;
}

export const packingListPdfUrl = (planId: string, userId: string) =>
  apiBlobUrl(
    `/api/v1/packs/${encodeURIComponent(planId)}/packing-list.pdf?user_id=${encodeURIComponent(userId)}`,
  );
