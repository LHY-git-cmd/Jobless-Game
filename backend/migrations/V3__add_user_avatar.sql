-- 作用：为新老账号添加预设头像编号；图片保存在静态目录，不写入数据库。
-- MySQL 5.7 不依赖 CHECK，具体可选编号由应用按发布清单验证。
ALTER TABLE users ADD COLUMN avatar_id TINYINT UNSIGNED NOT NULL DEFAULT 1;
