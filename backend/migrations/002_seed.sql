-- Demo 種子資料（可重複執行：先清除 demo 使用者資料再插入）。
-- Demo 使用者 = 00000000-0000-0000-0000-000000000001（對齊前端 store.ts）

-- ---- 1. 卡片百科 ----------------------------------------------------------
INSERT INTO cards (card_id, set_code, card_number, rarity, name_zh,
                   current_price, liquidity_score, is_meta) VALUES
('SV8a_217/187','SV8a','217/187','SAR','噴火龍ex',  3200, 0.90, TRUE),
('SV8a_201/187','SV8a','201/187','UR', '超夢ex',    2600, 0.78, FALSE),
('SV8a_190/187','SV8a','190/187','SR', '莉佳',       900, 0.70, FALSE),
('SV8a_185/187','SV8a','185/187','SR', '娜娜美',      760, 0.65, FALSE),
('SV8a_178/187','SV8a','178/187','AR', '皮卡丘',      420, 0.85, TRUE),
('SV8a_165/187','SV8a','165/187','AR', '伊布',        360, 0.80, FALSE),
('SV8a_120/187','SV8a','120/187','RR', '噴火龍',      150, 0.55, FALSE),
('SV8a_140/187','SV8a','140/187','RR', '耿鬼',         95, 0.60, TRUE),
('SV8a_098/187','SV8a','098/187','RR', '水箭龜',      120, 0.28, FALSE),
('SV8a_055/187','SV8a','055/187','R',  '卡比獸',       45, 0.40, FALSE),
('SV8a_030/187','SV8a','030/187','U',  '妙蛙種子',     15, 0.25, FALSE),
('SV8a_012/187','SV8a','012/187','C',  '綠毛蟲',        8, 0.20, FALSE),
('SV8a_005/187','SV8a','005/187','C',  '獨角蟲',        6, 0.15, FALSE),
('SV8a_044/187','SV8a','044/187','U',  '走路草',       12, 0.22, FALSE)
ON CONFLICT (card_id) DO UPDATE
   SET current_price = EXCLUDED.current_price,
       liquidity_score = EXCLUDED.liquidity_score,
       is_meta = EXCLUDED.is_meta,
       name_zh = EXCLUDED.name_zh;

-- ---- 2. 使用者庫存 --------------------------------------------------------
DELETE FROM user_inventory
 WHERE user_id = '00000000-0000-0000-0000-000000000001';

INSERT INTO user_inventory (user_id, card_id, quantity, is_favorite,
                            pack_eligible, acquired_price) VALUES
('00000000-0000-0000-0000-000000000001','SV8a_217/187', 2, TRUE,  FALSE, 2800),
('00000000-0000-0000-0000-000000000001','SV8a_201/187', 1, TRUE,  FALSE, 2400),
('00000000-0000-0000-0000-000000000001','SV8a_190/187', 3, FALSE, TRUE,   850),
('00000000-0000-0000-0000-000000000001','SV8a_185/187', 4, FALSE, TRUE,   700),
('00000000-0000-0000-0000-000000000001','SV8a_178/187', 6, FALSE, TRUE,   380),
('00000000-0000-0000-0000-000000000001','SV8a_165/187', 8, FALSE, TRUE,   320),
('00000000-0000-0000-0000-000000000001','SV8a_120/187',12, FALSE, TRUE,   130),
('00000000-0000-0000-0000-000000000001','SV8a_140/187',10, FALSE, TRUE,    80),
('00000000-0000-0000-0000-000000000001','SV8a_098/187',20, FALSE, TRUE,   110),
('00000000-0000-0000-0000-000000000001','SV8a_055/187',40, FALSE, TRUE,    40),
('00000000-0000-0000-0000-000000000001','SV8a_030/187',80, FALSE, TRUE,    12),
('00000000-0000-0000-0000-000000000001','SV8a_012/187',150,FALSE, TRUE,     5),
('00000000-0000-0000-0000-000000000001','SV8a_005/187',200,FALSE, TRUE,     4),
('00000000-0000-0000-0000-000000000001','SV8a_044/187',120,FALSE, TRUE,    10);

-- ---- 3. 90 天價格歷史（上升趨勢 + 波動，今日收在 current_price） ----------
DELETE FROM price_history;

INSERT INTO price_history (card_id, recorded_date, price, volume)
SELECT c.card_id,
       d::date AS recorded_date,
       GREATEST(1, ROUND((
           c.current_price
           * (1 - 0.28 * ((CURRENT_DATE - d::date)::numeric / 89))  -- 越早越便宜
           * (1 + 0.06 * sin((CURRENT_DATE - d::date) / 6.0))       -- 短週期波動
       )::numeric, 2)) AS price,
       (5 + floor(random() * 30))::int AS volume
FROM cards c
CROSS JOIN generate_series(
        CURRENT_DATE - INTERVAL '89 days', CURRENT_DATE, INTERVAL '1 day'
     ) AS d;

-- ---- 4. 製造「今日波動 >10%」效果（壓低/拉高昨日價，今日不動）-------------
-- 上漲 spike：昨日價壓低 → 今日相對 +約22%
UPDATE price_history SET price = ROUND(price * 0.82, 2)
 WHERE recorded_date = CURRENT_DATE - 1
   AND card_id IN ('SV8a_217/187','SV8a_178/187','SV8a_190/187');

-- 下跌 spike：昨日價拉高 → 今日相對 -約15%
UPDATE price_history SET price = ROUND(price * 1.18, 2)
 WHERE recorded_date = CURRENT_DATE - 1
   AND card_id IN ('SV8a_098/187');
