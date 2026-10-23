-- 作用：账号初始5点体力与每次普通尝试的扣返凭证，旧棋局无凭证不追扣不返还。
CREATE TABLE player_energy (
    user_id INT UNSIGNED NOT NULL,
    current INT NOT NULL DEFAULT 5,
    recovery_at DATETIME(6) NULL,
    revision INT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id),
    CONSTRAINT fk_player_energy_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE attempt_energy (
    attempt_id VARCHAR(36) NOT NULL,
    refunded INT NOT NULL DEFAULT 0,
    PRIMARY KEY (attempt_id),
    CONSTRAINT fk_attempt_energy_attempt FOREIGN KEY (attempt_id) REFERENCES game_attempts(attempt_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
