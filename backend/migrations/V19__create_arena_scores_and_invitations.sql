-- 作用：增量扩展三模式竞技房间、成员棋盘、账号积分和定向邀请，兼容MySQL5.7。
-- 积分流水不随房间历史清理删除；积分列允许负值。
ALTER TABLE pk_rooms ADD COLUMN host_id INTEGER UNSIGNED NULL;
ALTER TABLE pk_rooms ADD COLUMN source VARCHAR(16) NOT NULL DEFAULT 'friend';
ALTER TABLE pk_participants ADD COLUMN board JSON NULL;
CREATE TABLE arena_accounts (
 user_id INTEGER UNSIGNED NOT NULL PRIMARY KEY,
 points INTEGER NOT NULL DEFAULT 100,
 revision INTEGER NOT NULL DEFAULT 0,
 KEY ix_arena_points (points,user_id),
 FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE arena_ledger (
 room_id VARCHAR(36) NOT NULL,
 user_id INTEGER UNSIGNED NOT NULL,
 delta INTEGER NOT NULL,
 balance INTEGER NOT NULL,
 created_at DATETIME(6) NOT NULL,
 PRIMARY KEY (room_id,user_id),
 KEY ix_arena_ledger_user (user_id,created_at),
 FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE arena_invitations (
 invitation_id VARCHAR(36) NOT NULL PRIMARY KEY,
 sender_id INTEGER UNSIGNED NOT NULL,
 target_id INTEGER UNSIGNED NOT NULL,
 game_id VARCHAR(16) NOT NULL,
 status VARCHAR(16) NOT NULL,
 created_at DATETIME(6) NOT NULL,
 expires_at DATETIME(6) NOT NULL,
 room_id VARCHAR(36) NULL,
 KEY ix_arena_invite_target (target_id,status,expires_at),
 KEY ix_arena_invite_sender (sender_id,status,expires_at),
 KEY ix_arena_invite_expiry (expires_at,status),
 FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY (target_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
-- 旧未完成房间属于升级前规则，明确作废，不改动既有终态及历史成绩。
UPDATE pk_rooms SET status='cancelled',reason='arena_upgrade',finished_at=UTC_TIMESTAMP(6)
 WHERE status IN ('waiting','countdown','playing');
UPDATE matchmaking_tickets SET status='cancelled' WHERE status='waiting';
UPDATE player_pk_occupancy SET room_id=NULL,ticket_id=NULL,revision=revision+1;
