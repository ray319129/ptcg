// FastAPI 後端客戶端。型別對齊後端 app/schemas/scan.py。

export type MatchMethod =
  | "exact_regex"
  | "fuzzy_trgm"
  | "fuzzy_lev"
  | "ambiguous"
  | "not_found";

export interface MarketValue {
  estimated_price: string;
  currency: string;
  avg_7d: string | null;
  highest_deal: string | null;
  lowest_ask: string | null;
  liquidity_score: number;
  tier_strategy: string;
  is_stale: boolean;
}

export interface CardProfile {
  card_id: string;
  set_code: string;
  card_number: string;
  rarity: string;
  name_zh: string;
  market_value: MarketValue;
  in_collection_count: number;
}

export interface CardCandidate {
  card_id: string;
  set_code: string;
  card_number: string;
  rarity: string;
  name_zh: string;
  similarity: number;
}

export interface ScanResponse {
  success: boolean;
  method: MatchMethod;
  profile: CardProfile | null;
  candidates: CardCandidate[];
  message: string;
  parsed_at: string;
}

const BASE = import.meta.env.VITE_API_BASE ?? "";

/** 呼叫 /api/v1/parser/scan。clientConfidence 決定後端是否略過嚴格正則。 */
export async function scanCard(params: {
  rawText: string;
  clientConfidence: number;
  userId?: string;
  signal?: AbortSignal;
}): Promise<ScanResponse> {
  const res = await fetch(`${BASE}/api/v1/parser/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      raw_text: params.rawText,
      client_confidence: params.clientConfidence,
      user_id: params.userId ?? null,
    }),
    signal: params.signal,
  });
  if (!res.ok) {
    throw new Error(`掃描 API 失敗：${res.status} ${res.statusText}`);
  }
  return (await res.json()) as ScanResponse;
}
