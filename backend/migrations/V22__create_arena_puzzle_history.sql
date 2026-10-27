-- 作用：持久化账号在照明/数独竞技中各最近4局原题，换房/换对手/重启后继续去重。
-- 每账号每游戏最多一行，recent由应用限制为4条；不关联可清理的房间外键。
CREATE TABLE arena_puzzle_history (
 user_id INTEGER UNSIGNED NOT NULL,
 game_id VARCHAR(16) NOT NULL,
 recent JSON NOT NULL,
 revision INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY (user_id,game_id),
 CONSTRAINT fk_arena_puzzle_history_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
