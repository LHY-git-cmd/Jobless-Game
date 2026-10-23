-- 作用：为有界历史清理补充终态/时间索引；不修改已执行的V5～V8。
CREATE INDEX ix_attempt_retention ON game_attempts (status, ended_at);
CREATE INDEX ix_pk_room_retention ON pk_rooms (status, finished_at);
