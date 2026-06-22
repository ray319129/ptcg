-- 卡匣 PTCG 資料庫初始化 schema。
-- 套用：psql "$DATABASE_URL" -f migrations/001_schema.sql

-- ---- 必要擴充 -------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pg_trgm;        -- 三元組相似度（模糊比對）
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;  -- levenshtein()
CREATE EXTENSION IF NOT EXISTS pgcrypto;       -- gen_random_uuid()

-- 1. 卡片百科（全域參考）
CREATE TABLE IF NOT EXISTS cards (
    card_id        VARCHAR(50) PRIMARY KEY,        -- 'SV8a_217/187'
    set_code       VARCHAR(10) NOT NULL,
    card_number    VARCHAR(10) NOT NULL,
    rarity         VARCHAR(10) NOT NULL,
    name_zh        VARCHAR(100) NOT NULL,
    current_price  NUMERIC(10, 2) DEFAULT 0.00,
    liquidity_score NUMERIC(3, 2) DEFAULT 1.00,
    is_meta        BOOLEAN DEFAULT FALSE,          -- meta 卡（散卡估值上修）
    updated_at     TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 模糊比對索引：對 (set_code || ' ' || card_number) 建 trigram GIN
CREATE INDEX IF NOT EXISTS idx_cards_search
    ON cards USING gin ((set_code || ' ' || card_number) gin_trgm_ops);

-- 2. 使用者庫存
CREATE TABLE IF NOT EXISTS user_inventory (
    id             SERIAL PRIMARY KEY,
    user_id        UUID NOT NULL,
    card_id        VARCHAR(50) REFERENCES cards(card_id),
    quantity       INT NOT NULL DEFAULT 1,
    is_favorite    BOOLEAN DEFAULT FALSE,
    pack_eligible  BOOLEAN DEFAULT TRUE,           -- UI「納入神秘包資格」開關
    acquired_price NUMERIC(10, 2),
    created_at     TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_inventory_user ON user_inventory(user_id);

-- 3. 價格歷史（趨勢分析 / 估值來源）
CREATE TABLE IF NOT EXISTS price_history (
    id            BIGSERIAL PRIMARY KEY,
    card_id       VARCHAR(50) REFERENCES cards(card_id),
    recorded_date DATE NOT NULL,
    price         NUMERIC(10, 2) NOT NULL,
    volume        INT DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pricehist_card_date
    ON price_history(card_id, recorded_date DESC);

-- 4. 神秘包計畫（持久化最佳化結果，供 PDF 回看）
CREATE TABLE IF NOT EXISTS pack_plans (
    plan_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL,
    total_packs   INT NOT NULL,
    pack_price    NUMERIC(10, 2) NOT NULL,
    target_margin NUMERIC(4, 3) NOT NULL,
    floor_ratio   NUMERIC(4, 3) NOT NULL,
    feasible      BOOLEAN NOT NULL,
    result        JSONB NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_packplans_user ON pack_plans(user_id, created_at DESC);
