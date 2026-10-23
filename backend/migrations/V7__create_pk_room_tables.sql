-- 作用：增量创建双人房间/匹配资源；MySQL5.7兼容，所有时间保留微秒精度。

CREATE TABLE pk_rooms (
	room_id VARCHAR(36) NOT NULL, 
	room_code VARCHAR(8) NOT NULL, 
	game_id VARCHAR(16) NOT NULL, 
	difficulty VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	revision INTEGER NOT NULL, 
	created_at DATETIME(6) NOT NULL, 
	expires_at DATETIME(6) NOT NULL, 
	starts_at DATETIME(6), 
	ends_at DATETIME(6), 
	finished_at DATETIME(6), 
	puzzle JSON NOT NULL, 
	result JSON, 
	reason VARCHAR(32), 
	PRIMARY KEY (room_id), 
	UNIQUE (room_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX ix_pk_room_status_expiry ON pk_rooms (status, expires_at);

CREATE TABLE pk_participants (
	room_id VARCHAR(36) NOT NULL, 
	user_id INTEGER UNSIGNED NOT NULL, 
	ready BOOL NOT NULL, 
	readiness_created BOOL NOT NULL, 
	joined_at DATETIME(6) NOT NULL, 
	left_at DATETIME(6), 
	disconnected_at DATETIME(6), 
	PRIMARY KEY (room_id, user_id), 
	FOREIGN KEY(room_id) REFERENCES pk_rooms (room_id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE pk_submissions (
	room_id VARCHAR(36) NOT NULL, 
	user_id INTEGER UNSIGNED NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	received_at DATETIME(6) NOT NULL, 
	PRIMARY KEY (room_id, user_id), 
	FOREIGN KEY(room_id) REFERENCES pk_rooms (room_id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE player_pk_occupancy (
	user_id INTEGER UNSIGNED NOT NULL, 
	room_id VARCHAR(36), 
	revision INTEGER NOT NULL, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX ix_pk_occupancy_room ON player_pk_occupancy (room_id);
