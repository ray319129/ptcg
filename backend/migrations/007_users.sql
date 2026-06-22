-- 使用者帳號（讓資料綁定帳號、長期保存）。
CREATE TABLE IF NOT EXISTS users (
    user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username      VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(200) NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
