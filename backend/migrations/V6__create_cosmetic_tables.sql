-- 作用：增量创建正式成长/资格或外观表及冻结种子，兼容MySQL5.7；不修改已执行迁移。

CREATE TABLE cosmetic_definitions (
	cosmetic_id VARCHAR(40) NOT NULL, 
	kind VARCHAR(24) NOT NULL, 
	required_stars INTEGER NOT NULL, 
	asset_version INTEGER NOT NULL, 
	enabled BOOL NOT NULL, 
	PRIMARY KEY (cosmetic_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE player_appearance (
	user_id INTEGER UNSIGNED NOT NULL, 
	configuration JSON NOT NULL, 
	revision INTEGER NOT NULL, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE player_cosmetics (
	user_id INTEGER UNSIGNED NOT NULL, 
	cosmetic_id VARCHAR(40) NOT NULL, 
	unlocked_at DATETIME(6) NOT NULL, 
	source VARCHAR(24) NOT NULL, 
	PRIMARY KEY (user_id, cosmetic_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

INSERT INTO cosmetic_definitions (cosmetic_id, kind, required_stars, asset_version, enabled) VALUES ('default', 'theme', 0, 1, 1), ('starlight', 'theme', 10, 1, 1);
