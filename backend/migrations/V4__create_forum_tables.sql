-- 作用：新增文字论坛与站内提醒；兼容 MySQL 5.7，不修改 V1～V3。
-- 用户外键匹配现有 users.id INT UNSIGNED，内容编号使用 BIGINT UNSIGNED。
CREATE TABLE forum_posts (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    request_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    title VARCHAR(80) NOT NULL,
    body TEXT NOT NULL,
    like_count INT UNSIGNED NOT NULL DEFAULT 0,
    comment_count INT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_forum_post_request (user_id, request_id),
    KEY ix_forum_post_author (user_id, created_at, id),
    CONSTRAINT fk_forum_post_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE forum_comments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    post_id BIGINT UNSIGNED NOT NULL,
    user_id INT UNSIGNED NOT NULL,
    request_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    root_comment_id BIGINT UNSIGNED NULL,
    reply_to_comment_id BIGINT UNSIGNED NULL,
    body TEXT NOT NULL,
    like_count INT UNSIGNED NOT NULL DEFAULT 0,
    reply_count INT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_forum_comment_request (user_id, request_id),
    KEY ix_forum_comment_page (post_id, root_comment_id, id),
    KEY ix_forum_reply_page (root_comment_id, id),
    KEY ix_forum_comment_author (user_id, created_at, id),
    CONSTRAINT fk_forum_comment_post FOREIGN KEY (post_id) REFERENCES forum_posts (id),
    CONSTRAINT fk_forum_comment_user FOREIGN KEY (user_id) REFERENCES users (id),
    CONSTRAINT fk_forum_comment_root FOREIGN KEY (root_comment_id) REFERENCES forum_comments (id),
    CONSTRAINT fk_forum_comment_target FOREIGN KEY (reply_to_comment_id) REFERENCES forum_comments (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE forum_post_likes (
    post_id BIGINT UNSIGNED NOT NULL,
    user_id INT UNSIGNED NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (post_id, user_id),
    CONSTRAINT fk_forum_post_like_post FOREIGN KEY (post_id) REFERENCES forum_posts (id),
    CONSTRAINT fk_forum_post_like_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE forum_comment_likes (
    comment_id BIGINT UNSIGNED NOT NULL,
    user_id INT UNSIGNED NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (comment_id, user_id),
    CONSTRAINT fk_forum_comment_like_comment FOREIGN KEY (comment_id) REFERENCES forum_comments (id),
    CONSTRAINT fk_forum_comment_like_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE forum_notifications (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    recipient_id INT UNSIGNED NOT NULL,
    actor_id INT UNSIGNED NOT NULL,
    kind VARCHAR(24) CHARACTER SET ascii NOT NULL,
    post_id BIGINT UNSIGNED NOT NULL,
    comment_id BIGINT UNSIGNED NULL,
    event_key VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    read_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_forum_notification_event (recipient_id, event_key),
    KEY ix_forum_notification_page (recipient_id, id),
    KEY ix_forum_notification_unread (recipient_id, read_at, id),
    CONSTRAINT fk_forum_notification_recipient FOREIGN KEY (recipient_id) REFERENCES users (id),
    CONSTRAINT fk_forum_notification_actor FOREIGN KEY (actor_id) REFERENCES users (id),
    CONSTRAINT fk_forum_notification_post FOREIGN KEY (post_id) REFERENCES forum_posts (id),
    CONSTRAINT fk_forum_notification_comment FOREIGN KEY (comment_id) REFERENCES forum_comments (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
