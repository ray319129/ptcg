-- 雙語卡價：日文版 (pkmjp) 與繁體中文版 (pkmtw) 價格差異甚大，分開儲存。
ALTER TABLE cards ADD COLUMN IF NOT EXISTS price_jp NUMERIC(10, 2);
ALTER TABLE cards ADD COLUMN IF NOT EXISTS price_tw NUMERIC(10, 2);
-- current_price 保留為「預設顯示價」，預設採繁中版。
