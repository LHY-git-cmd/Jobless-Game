-- 作用：星数榜与等级/经验榜的有限分页和跨页名次查询索引，兼容 MySQL 5.7。
-- 仅增加索引，不修改已有成长数据，也不创建竞技积分。
CREATE INDEX ix_progression_stars ON player_progression (total_stars, user_id);
CREATE INDEX ix_progression_xp ON player_progression (xp, user_id);
