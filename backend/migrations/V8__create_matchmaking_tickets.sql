-- 作用：增量创建双人房间/匹配资源；MySQL5.7兼容，所有时间保留微秒精度。

CREATE TABLE matchmaking_tickets (
	ticket_id VARCHAR(36) NOT NULL, 
	user_id INTEGER UNSIGNED NOT NULL, 
	pool VARCHAR(32) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	created_at DATETIME(6) NOT NULL, 
	expires_at DATETIME(6) NOT NULL, 
	room_id VARCHAR(36), 
	PRIMARY KEY (ticket_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX ix_ticket_waiting ON matchmaking_tickets (status, created_at, ticket_id);

CREATE INDEX ix_ticket_expiry ON matchmaking_tickets (expires_at);

ALTER TABLE player_pk_occupancy ADD COLUMN ticket_id VARCHAR(36) NULL;

CREATE INDEX ix_pk_occupancy_ticket ON player_pk_occupancy (ticket_id);
