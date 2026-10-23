-- 作用：增量创建正式成长/资格或外观表及冻结种子，兼容MySQL5.7；不修改已执行迁移。

CREATE TABLE game_levels (
	level_id VARCHAR(40) NOT NULL, 
	game_id VARCHAR(16) NOT NULL, 
	order_index INTEGER NOT NULL, 
	PRIMARY KEY (level_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX ix_game_level_order ON game_levels (game_id, order_index);

CREATE TABLE api_idempotency (
	user_id INTEGER UNSIGNED NOT NULL, 
	resource_kind VARCHAR(24) NOT NULL, 
	`key` VARCHAR(36) NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	resource_id VARCHAR(36) NOT NULL, 
	original_status INTEGER NOT NULL, 
	snapshot JSON NOT NULL, 
	expires_at DATETIME(6) NOT NULL, 
	PRIMARY KEY (user_id, resource_kind, `key`), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX ix_api_idempotency_expiry ON api_idempotency (expires_at);

CREATE TABLE game_attempts (
	attempt_id VARCHAR(36) NOT NULL, 
	user_id INTEGER UNSIGNED NOT NULL, 
	level_id VARCHAR(40) NOT NULL, 
	level_version INTEGER NOT NULL, 
	game_id VARCHAR(16) NOT NULL, 
	mode VARCHAR(20) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	revision INTEGER NOT NULL, 
	started_at DATETIME(6) NOT NULL, 
	expires_at DATETIME(6) NOT NULL, 
	ended_at DATETIME(6), 
	board JSON NOT NULL, 
	PRIMARY KEY (attempt_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX ix_attempt_expiry ON game_attempts (expires_at);

CREATE INDEX ix_attempt_owner_active ON game_attempts (user_id, status, level_id);

CREATE TABLE game_level_versions (
	level_id VARCHAR(40) NOT NULL, 
	level_version INTEGER NOT NULL, 
	definition JSON NOT NULL, 
	PRIMARY KEY (level_id, level_version), 
	FOREIGN KEY(level_id) REFERENCES game_levels (level_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE player_level_progress (
	user_id INTEGER UNSIGNED NOT NULL, 
	level_id VARCHAR(40) NOT NULL, 
	best_stars INTEGER NOT NULL, 
	best_duration_ms INTEGER NOT NULL, 
	best_level_version INTEGER NOT NULL, 
	first_completed_at DATETIME(6) NOT NULL, 
	first_three_star_at DATETIME(6), 
	revision INTEGER NOT NULL, 
	PRIMARY KEY (user_id, level_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE player_progression (
	user_id INTEGER UNSIGNED NOT NULL, 
	xp INTEGER NOT NULL, 
	total_stars INTEGER NOT NULL, 
	revision INTEGER NOT NULL, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE player_qualifications (
	user_id INTEGER UNSIGNED NOT NULL, 
	requirement_id VARCHAR(40) NOT NULL, 
	level_version INTEGER NOT NULL, 
	attempt_id VARCHAR(36) NOT NULL, 
	completed_at DATETIME(6) NOT NULL, 
	PRIMARY KEY (user_id, requirement_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE progression_grants (
	user_id INTEGER UNSIGNED NOT NULL, 
	level_id VARCHAR(40) NOT NULL, 
	milestone VARCHAR(24) NOT NULL, 
	xp_delta INTEGER NOT NULL, 
	policy_version INTEGER NOT NULL, 
	attempt_id VARCHAR(36) NOT NULL, 
	granted_at DATETIME(6) NOT NULL, 
	PRIMARY KEY (user_id, level_id, milestone), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE game_completions (
	attempt_id VARCHAR(36) NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	duration_ms INTEGER NOT NULL, 
	stars INTEGER NOT NULL, 
	snapshot JSON NOT NULL, 
	PRIMARY KEY (attempt_id), 
	FOREIGN KEY(attempt_id) REFERENCES game_attempts (attempt_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

INSERT INTO game_levels (level_id, game_id, order_index) VALUES ('akari-001', 'akari', 1);

INSERT INTO game_level_versions (level_id, level_version, definition) VALUES ('akari-001', 1, '{"level_id":"akari-001","game_id":"akari","level_version":1,"rules_version":1,"reward_policy_version":1,"order":1,"name":"第一束光","difficulty":"beginner","minimum_level":1,"prerequisite_level_id":null,"modes":["campaign"],"t3_ms":100000,"t2_ms":200000,"puzzle":{"rows":5,"cols":5,"map":["...1.",".....","0..0.","0..0#","0..00"],"checksum":"2dc303db7952dc67d25eb46b00956b753682309c1b814fa582a352037e8e7aa8"}}');

INSERT INTO game_levels (level_id, game_id, order_index) VALUES ('akari-002', 'akari', 2);

INSERT INTO game_level_versions (level_id, level_version, definition) VALUES ('akari-002', 1, '{"level_id":"akari-002","game_id":"akari","level_version":1,"rules_version":1,"reward_policy_version":1,"order":2,"name":"墙后的光","difficulty":"beginner","minimum_level":1,"prerequisite_level_id":null,"modes":["campaign"],"t3_ms":100000,"t2_ms":200000,"puzzle":{"rows":5,"cols":5,"map":["10#.#",".2..0","1#3..","0...0","#...."],"checksum":"6ccc5354c696e32648820be5aae54ff777ba9ccd1890374c7cd761142a2e4d16"}}');

INSERT INTO game_levels (level_id, game_id, order_index) VALUES ('akari-003', 'akari', 3);

INSERT INTO game_level_versions (level_id, level_version, definition) VALUES ('akari-003', 1, '{"level_id":"akari-003","game_id":"akari","level_version":1,"rules_version":1,"reward_policy_version":1,"order":3,"name":"浅滩信号","difficulty":"beginner","minimum_level":1,"prerequisite_level_id":null,"modes":["campaign"],"t3_ms":100000,"t2_ms":200000,"puzzle":{"rows":5,"cols":5,"map":["00.0.",".....","0..2.","#.2..","#...0"],"checksum":"eeba5b9bdf92b2e023831751583db456ff8dc9a4dc447ac2343b36bf68c3d0b7"}}');

INSERT INTO game_levels (level_id, game_id, order_index) VALUES ('akari-004', 'akari', 4);

INSERT INTO game_level_versions (level_id, level_version, definition) VALUES ('akari-004', 1, '{"level_id":"akari-004","game_id":"akari","level_version":1,"rules_version":1,"reward_policy_version":1,"order":4,"name":"相邻的约定","difficulty":"normal","minimum_level":2,"prerequisite_level_id":"akari-003","modes":["campaign"],"t3_ms":144000,"t2_ms":288000,"puzzle":{"rows":6,"cols":6,"map":["#.....","..#.1.","0...1.","01#...","#.21#1","##.#.."],"checksum":"e8a73507a5cbc80d7576c0815ce18258066c241e94d478226d379fa6b6c8bb13"}}');

INSERT INTO game_levels (level_id, game_id, order_index) VALUES ('akari-005', 'akari', 5);

INSERT INTO game_level_versions (level_id, level_version, definition) VALUES ('akari-005', 1, '{"level_id":"akari-005","game_id":"akari","level_version":1,"rules_version":1,"reward_policy_version":1,"order":5,"name":"数字回廊","difficulty":"normal","minimum_level":2,"prerequisite_level_id":"akari-003","modes":["campaign"],"t3_ms":144000,"t2_ms":288000,"puzzle":{"rows":6,"cols":6,"map":["1...1.","0.#..#","..##..","..1.2#","..02#.","0#...#"],"checksum":"a37ca1ddd3658983a7e1bea62d51e40ad38217829f6a1fb37e9d2b6d2005f76e"}}');

INSERT INTO game_levels (level_id, game_id, order_index) VALUES ('akari-006', 'akari', 6);

INSERT INTO game_level_versions (level_id, level_version, definition) VALUES ('akari-006', 1, '{"level_id":"akari-006","game_id":"akari","level_version":1,"rules_version":1,"reward_policy_version":1,"order":6,"name":"灯塔小径","difficulty":"normal","minimum_level":2,"prerequisite_level_id":"akari-003","modes":["campaign"],"t3_ms":144000,"t2_ms":288000,"puzzle":{"rows":6,"cols":6,"map":[".2....","...1..",".....1","1.....","..00#0",".10#.1"],"checksum":"c893de2e5082b5ddf337875dad8bbe52a1f1c36c817ec83447dc66d798e6c775"}}');

INSERT INTO game_levels (level_id, game_id, order_index) VALUES ('akari-007', 'akari', 7);

INSERT INTO game_level_versions (level_id, level_version, definition) VALUES ('akari-007', 1, '{"level_id":"akari-007","game_id":"akari","level_version":1,"rules_version":1,"reward_policy_version":1,"order":7,"name":"交叉光影","difficulty":"normal","minimum_level":3,"prerequisite_level_id":"akari-006","modes":["campaign"],"t3_ms":196000,"t2_ms":392000,"puzzle":{"rows":7,"cols":7,"map":["..1..#.","....1..",".0.0##1","0...0.1","102#0..",".3..0.#","...0..#"],"checksum":"41abfdb250a3d40fcd30fd68774c960e39ee0cddf57762e616c98c35ba1a1298"}}');

INSERT INTO game_levels (level_id, game_id, order_index) VALUES ('akari-008', 'akari', 8);

INSERT INTO game_level_versions (level_id, level_version, definition) VALUES ('akari-008', 1, '{"level_id":"akari-008","game_id":"akari","level_version":1,"rules_version":1,"reward_policy_version":1,"order":8,"name":"深蓝回声","difficulty":"normal","minimum_level":3,"prerequisite_level_id":"akari-006","modes":["campaign"],"t3_ms":196000,"t2_ms":392000,"puzzle":{"rows":7,"cols":7,"map":["...#1..","..1....","...13.#","..##.2.","2#..31.",".2....1","......."],"checksum":"1a8e451aebfb92be60950de783d3b4d3d1089242ec7c5cd26c6cea2110315822"}}');

INSERT INTO game_levels (level_id, game_id, order_index) VALUES ('akari-009', 'akari', 9);

INSERT INTO game_level_versions (level_id, level_version, definition) VALUES ('akari-009', 1, '{"level_id":"akari-009","game_id":"akari","level_version":1,"rules_version":1,"reward_policy_version":1,"order":9,"name":"群岛之光","difficulty":"normal","minimum_level":3,"prerequisite_level_id":"akari-006","modes":["campaign"],"t3_ms":256000,"t2_ms":512000,"puzzle":{"rows":8,"cols":8,"map":["..2.....","##.3..0.","#...3...","11#..3..",".#.##..#","#.....1.",".01..1#.","...0...1"],"checksum":"ce09ebddf21fd65848d1de44e8ae8dbec07485fd710c6d4728015ad785f781b9"}}');

INSERT INTO game_levels (level_id, game_id, order_index) VALUES ('akari-010', 'akari', 10);

INSERT INTO game_level_versions (level_id, level_version, definition) VALUES ('akari-010', 1, '{"level_id":"akari-010","game_id":"akari","level_version":1,"rules_version":1,"reward_policy_version":1,"order":10,"name":"远方灯塔","difficulty":"normal","minimum_level":4,"prerequisite_level_id":"akari-009","modes":["campaign"],"t3_ms":400000,"t2_ms":800000,"puzzle":{"rows":10,"cols":10,"map":["..0......1","...1..#...","..#.#0#.0.",".1...##...","1.#.2.2...","0...#.0...","....#000..","1.2.......","#11...0..2","....1#...."],"checksum":"b397d7c638aa5027e7e3227b049f6a0e504e8dfb6d43a0a26dbd8a4892aaaffa"}}');

INSERT INTO game_levels (level_id, game_id, order_index) VALUES ('mine-beginner-001', 'mine', 1);

INSERT INTO game_level_versions (level_id, level_version, definition) VALUES ('mine-beginner-001', 1, '{"level_id":"mine-beginner-001","game_id":"mine","level_version":1,"rules_version":1,"reward_policy_version":1,"order":1,"name":"扫雷初级","difficulty":"beginner","minimum_level":1,"prerequisite_level_id":null,"modes":["qualification"],"puzzle":{"rows":10,"cols":10,"mines":10,"checksum":"8a54e0fae2c6d39d77e9b084adbbf099ef43c60ecfd6fdfe0bbe06ab1b75bbd2"}}');

INSERT INTO game_levels (level_id, game_id, order_index) VALUES ('sudoku-beginner-001', 'sudoku', 1);

INSERT INTO game_level_versions (level_id, level_version, definition) VALUES ('sudoku-beginner-001', 1, '{"level_id":"sudoku-beginner-001","game_id":"sudoku","level_version":1,"rules_version":1,"reward_policy_version":1,"order":1,"name":"数独初级","difficulty":"beginner","minimum_level":1,"prerequisite_level_id":null,"modes":["qualification"],"puzzle":{"rows":9,"cols":9,"values":[5,3,0,0,7,0,0,0,0,6,0,0,1,9,5,0,0,0,0,9,8,0,0,0,0,6,0,8,0,0,0,6,0,0,0,3,4,0,0,8,0,3,0,0,1,7,0,0,0,2,0,0,0,6,0,6,0,0,0,0,2,8,0,0,0,0,4,1,9,0,0,5,0,0,0,0,8,0,0,7,9],"checksum":"52b7f1db72a69d9a651a39656c548e6909c811af961b5dec2500465a70f7d0a2"}}');
