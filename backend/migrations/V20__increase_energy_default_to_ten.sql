-- 作用：将新建体力记录的数据库默认值提高到10；已有余额及恢复时间保持不变。
-- 体力上限由应用校验，本迁移不直接补满旧账号、不重建扣返凭证。
ALTER TABLE player_energy ALTER COLUMN current SET DEFAULT 10;
