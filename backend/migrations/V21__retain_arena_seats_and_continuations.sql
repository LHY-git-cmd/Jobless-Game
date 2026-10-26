-- 作用：结算后短期保留成员席位；后继局链接使并发再战共用一局。
-- 不修改既有终盘、积分流水及历史房间；空值表示没有保留席位或续局。
ALTER TABLE pk_rooms ADD COLUMN lobby_expires_at DATETIME(6) NULL;
ALTER TABLE pk_rooms ADD COLUMN next_room_id VARCHAR(36) NULL;
CREATE INDEX ix_pk_room_lobby_expiry ON pk_rooms (lobby_expires_at);
