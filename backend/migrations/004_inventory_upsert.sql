-- 讓「掃描自動入庫」可用 upsert：同一使用者同一卡只一列，數量累加。
-- 先合併可能的重複列，再建唯一索引。
WITH dedup AS (
    SELECT user_id, card_id, SUM(quantity) AS qty,
           bool_or(is_favorite) AS fav, bool_or(pack_eligible) AS elig,
           min(id) AS keep_id
    FROM user_inventory
    GROUP BY user_id, card_id
    HAVING count(*) > 1
)
UPDATE user_inventory ui SET quantity = d.qty,
       is_favorite = d.fav, pack_eligible = d.elig
FROM dedup d
WHERE ui.id = d.keep_id;

DELETE FROM user_inventory ui
USING (
    SELECT user_id, card_id, min(id) AS keep_id
    FROM user_inventory GROUP BY user_id, card_id HAVING count(*) > 1
) d
WHERE ui.user_id = d.user_id AND ui.card_id = d.card_id AND ui.id <> d.keep_id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_user_card
    ON user_inventory(user_id, card_id);
