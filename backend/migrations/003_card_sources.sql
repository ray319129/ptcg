-- 為接入外部卡源（Scrydex / 台灣官網）擴充 cards 欄位。
ALTER TABLE cards ADD COLUMN IF NOT EXISTS name_en       VARCHAR(150);
ALTER TABLE cards ADD COLUMN IF NOT EXISTS image_url     VARCHAR(300);  -- 本地或遠端卡圖
ALTER TABLE cards ADD COLUMN IF NOT EXISTS source        VARCHAR(20);   -- 'scrydex' | 'tw_official'
ALTER TABLE cards ADD COLUMN IF NOT EXISTS release_date  DATE;          -- 用於 2025+ 篩選
ALTER TABLE cards ADD COLUMN IF NOT EXISTS price_source  VARCHAR(20);   -- 'cardpaipai' 等在地價來源
ALTER TABLE cards ADD COLUMN IF NOT EXISTS external_id   VARCHAR(50);   -- 來源端原始 id（官網 detail id / scrydex id）

CREATE INDEX IF NOT EXISTS idx_cards_set ON cards(set_code);
CREATE INDEX IF NOT EXISTS idx_cards_release ON cards(release_date);
