-- 卡片牌種（Pokemon / Supporter / Item / Stadium / Tool / Energy），
-- 自官方詳情頁補抓。用於神秘包「類別保底」（全圖人物 = SR/SAR 的 Supporter）。
ALTER TABLE cards ADD COLUMN IF NOT EXISTS card_type VARCHAR(20);
