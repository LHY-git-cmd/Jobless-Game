-- 作用：新增有界当前轮次、通关快照与最佳摘要；使用 MySQL JSON，不依赖窗口查询。
CREATE TABLE challenge_progress (
    user_id INT UNSIGNED NOT NULL,
    run_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    revision INT UNSIGNED NOT NULL,
    game_state JSON NOT NULL,
    total_recorded BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (user_id),
    UNIQUE KEY uq_challenge_run (run_id),
    CONSTRAINT fk_progress_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE completion_records (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    category VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    run_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    attempt_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    duration_seconds INT UNSIGNED NOT NULL,
    mine_seconds INT UNSIGNED NULL,
    akari_seconds INT UNSIGNED NULL,
    sudoku_seconds INT UNSIGNED NULL,
    completed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_completion_attempt (user_id, category, attempt_id),
    KEY ix_completion_recent (user_id, category, completed_at, id),
    CONSTRAINT fk_completion_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT ck_completion_category CHECK (category IN ('mine','akari','sudoku','total')),
    CONSTRAINT ck_completion_snapshot CHECK (
        (category = 'total' AND mine_seconds IS NOT NULL AND akari_seconds IS NOT NULL
         AND sudoku_seconds IS NOT NULL AND duration_seconds = mine_seconds + akari_seconds + sudoku_seconds)
        OR (category <> 'total' AND mine_seconds IS NULL AND akari_seconds IS NULL AND sudoku_seconds IS NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE leaderboard_entries (
    user_id INT UNSIGNED NOT NULL,
    category VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    best_record_id BIGINT UNSIGNED NOT NULL,
    best_duration_seconds INT UNSIGNED NOT NULL,
    achieved_at DATETIME(6) NOT NULL,
    PRIMARY KEY (user_id, category),
    KEY ix_leaderboard_order (category, best_duration_seconds, achieved_at, user_id),
    CONSTRAINT fk_leaderboard_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_leaderboard_best FOREIGN KEY (best_record_id) REFERENCES completion_records(id) ON DELETE CASCADE,
    CONSTRAINT ck_leaderboard_category CHECK (category IN ('mine','akari','sudoku','total'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
