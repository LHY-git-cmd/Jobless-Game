"""排行榜规则与真实 SQL 事务测试；SQLite 仅用于本地回归，不替代 MySQL/Flyway。"""

from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.common.config import Settings
from backend.app.common.database import Base
from backend.app.common.exceptions import AppError
from backend.app.common.security import utc_now
from backend.app.models.entities import User
from backend.app.models.entities.ranking import CompletionRecord, LeaderboardEntry
from backend.app.models.entities.progression import PlayerProgression
from backend.app.services.progression_service import account_level
from backend.app.models.schemas.ranking import StartRequest, RestartRequest, CompleteRequest
from backend.app.services import ranking_service as service
from backend.app import main
from backend.app.common.database import get_db
from backend.app.controllers import ranking_controller
from fastapi.testclient import TestClient


class RankingTests(TestCase):
    """通过业务层运行真实查询，覆盖保留集合、自由选关、独立重开与总榜停用。"""

    def setUp(self):
        """创建隔离的内存数据库，不连接项目或生产 MySQL。"""
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(self.engine, expire_on_commit=False)()
        self.user = User(id=1, username="玩家", username_key="玩家", password_hash="test-only", created_at=utc_now())
        self.db.add(self.user)
        self.db.commit()
        self.auth = patch.object(service.auth_service, "current_session", return_value=(None, self.user))
        self.auth.start()
        self.config = Settings()

    def tearDown(self):
        """释放数据库与认证替身。"""
        self.auth.stop()
        self.db.close()
        self.engine.dispose()

    def start(self):
        """通过正常业务建立一轮挑战。"""
        return service.start_transaction("token", StartRequest(request_id=uuid4()), self.db)

    def seed_growth(self):
        """同星、同经验跨页样例；只有真实成长摘要参与成长榜。"""
        for uid, stars, xp in [(1, 8, 90), (2, 8, 180), (3, 3, 180), (4, 2, 179)]:
            if uid != 1:
                self.db.add(User(id=uid, username=f"玩家{uid}", username_key=f"p{uid}",
                                 password_hash="test-only", created_at=utc_now()))
            self.db.add(PlayerProgression(user_id=uid, total_stars=stars, xp=xp, revision=0))
        self.db.commit()

    def complete(self, state, category, seconds, development=False):
        """按服务端给出的尝试标识提交某一关。"""
        index = service.GAMES.index(category)
        return service.complete_transaction("token", state["run_id"], CompleteRequest(
            category=category, revision=state["revision"], attempt_id=state["levels"][index]["attempt_id"],
            duration_seconds=seconds, development=development), self.db, self.config)

    def test_games_complete_in_any_order_without_total(self):
        """三关直接开放，任意顺序完成也不生成整轮成绩。"""
        state = self.start()
        state = self.complete(state, "sudoku", 245)
        state = self.complete(state, "mine", 65)
        state = self.complete(state, "akari", 130)
        self.assertFalse(state["total_recorded"])
        self.assertEqual([level["seconds"] for level in state["levels"]], [65, 130, 245])
        self.assertEqual(self.db.scalars(select(CompletionRecord).where(CompletionRecord.category == "total")).all(), [])

    def test_retention_union_and_idempotency(self):
        """保留最佳与最新三次的并集，重复上传不改变最近记录。"""
        for seconds in [40, 35, 50, 45, 60]:
            state = self.complete(self.start(), "mine", seconds)
        self.complete(state, "mine", 60)
        records = service.records_transaction("token", "mine", self.db)
        self.assertEqual(records["best"]["duration_seconds"], 35)
        self.assertEqual([row["duration_seconds"] for row in records["recent"]], [60, 45, 50])
        self.assertEqual(len(self.db.scalars(select(CompletionRecord)).all()), 4)
        self.complete(self.start(), "mine", 30)
        self.assertEqual(len(self.db.scalars(select(CompletionRecord)).all()), 3)

    def test_restart_invalidates_old_attempt_and_new_round_invalidates_old_run(self):
        """重开幂等且旧尝试不可复活，新进度使旧请求失效。"""
        state = self.complete(self.start(), "mine", 10)
        payload = RestartRequest(category="mine", revision=state["revision"], request_id=uuid4())
        restarted = service.restart_transaction("token", state["run_id"], payload, self.db)
        duplicate = service.restart_transaction("token", state["run_id"], payload, self.db)
        self.assertEqual(restarted, duplicate)
        with self.assertRaises(AppError):
            self.complete(state, "mine", 10)
        self.assertEqual(self.complete(restarted, "akari", 5)["levels"][1]["seconds"], 5)
        self.start()
        with self.assertRaises(AppError):
            self.complete(restarted, "mine", 5)

    def test_restart_only_changes_selected_game_after_all_completed(self):
        """全部通关仍可单关重开，其他成绩和尝试编号保持原样。"""
        state = self.start()
        for game in service.GAMES:
            state = self.complete(state, game, 10)
        # 模拟旧版完整通关存档；原总榜完成标记不得再阻止单关重开。
        progress = service.repository.progress(self.db, self.user.id)
        progress.total_recorded = True
        self.db.commit()
        restarted = service.restart_transaction("token", state["run_id"], RestartRequest(
            category="mine", revision=state["revision"], request_id=uuid4()), self.db)
        self.assertEqual(restarted["levels"][1:], state["levels"][1:])
        self.assertIsNone(restarted["levels"][0]["seconds"])
        self.assertNotEqual(restarted["levels"][0]["attempt_id"], state["levels"][0]["attempt_id"])

    def test_other_game_pending_completion_survives_restart(self):
        """另一关重开增加版本时，不作废本关已冻结的待提交负载。"""
        state = self.start()
        service.restart_transaction("token", state["run_id"], RestartRequest(
            category="mine", revision=state["revision"], request_id=uuid4()), self.db)
        completed = self.complete(state, "sudoku", 12)
        self.assertEqual(completed["levels"][2]["seconds"], 12)

    def test_independent_bests(self):
        """单项最佳分别更新，不生成总榜。"""
        for times in [(1, 100, 100), (100, 1, 100), (100, 100, 1)]:
            state = self.start()
            for game, seconds in zip(service.GAMES, times):
                state = self.complete(state, game, seconds)
        for game in service.GAMES:
            self.assertEqual(service.records_transaction("token", game, self.db)["best"]["duration_seconds"], 1)

    def test_ties_keep_old_best_and_rank_across_pages(self):
        """同秒不覆盖原最佳，跨页并列遵守 1、1、3。"""
        state = self.complete(self.start(), "mine", 10)
        original = service.records_transaction("token", "mine", self.db)["best"]["id"]
        self.complete(self.start(), "mine", 10)
        self.assertEqual(service.records_transaction("token", "mine", self.db)["best"]["id"], original)
        for uid, seconds in [(2, 10), (3, 20)]:
            user = User(id=uid, username=f"玩家{uid}", username_key=f"p{uid}", password_hash="test", created_at=utc_now())
            self.db.add(user)
            self.db.commit()
            with patch.object(service.auth_service, "current_session", return_value=(None, user)):
                self.complete(self.start(), "mine", seconds)
        self.assertEqual(service.rankings_transaction("mine", 2, 1, self.db)["entries"][0]["rank"], 1)
        self.assertEqual(service.rankings_transaction("mine", 3, 1, self.db)["entries"][0]["rank"], 3)

    def test_development_default_off_and_enabled(self):
        """默认拒绝开发通关，显式启用后仍只完成当前关。"""
        state = self.start()
        with self.assertRaises(AppError) as caught:
            self.complete(state, "mine", 0, True)
        self.assertEqual(caught.exception.status_code, 403)
        self.config = Settings(dev_quick_complete_enabled=True)
        state = self.complete(state, "mine", 0, True)
        self.assertIsNone(state["levels"][1]["seconds"])
        self.assertFalse(state["total_recorded"])

    def test_write_failure_rolls_back_whole_transaction(self):
        """最佳维护失败时新成绩和进度都必须回滚。"""
        state = self.start()
        with patch.object(service.repository, "retain_records", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                self.complete(state, "mine", 3)
        self.assertEqual(self.db.scalars(select(CompletionRecord)).all(), [])
        self.assertEqual(self.db.scalars(select(LeaderboardEntry)).all(), [])
        state = self.complete(state, "mine", 3)
        self.assertEqual(state["levels"][0]["seconds"], 3)

    def test_each_game_retains_only_best_and_recent(self):
        """独立关卡各自保留最佳及最近三次，无整轮记录。"""
        for times in [(10, 10, 10), (1, 100, 100), (100, 1, 100), (100, 100, 1), (80, 80, 80)]:
            state = self.start()
            for game, seconds in zip(service.GAMES, times):
                state = self.complete(state, game, seconds)
        self.assertFalse(any(record.duration_seconds == 10 for record in self.db.scalars(select(CompletionRecord).where(CompletionRecord.category == "mine"))))
        for category in service.GAMES:
            self.assertLessEqual(len(self.db.scalars(select(CompletionRecord).where(CompletionRecord.category == category)).all()), 4)


class RankingAPITests(TestCase):
    """验证真实路由、校验、同源、公开榜单与个人记录权限。"""

    def setUp(self):
        """复用隔离 SQL 测试夹具，不连接真实项目数据库。"""
        RankingTests.setUp(self)
        self.auth.stop()
        self.auth = patch.object(service.auth_service, "current_session", side_effect=lambda raw, db: (None, self.user) if raw == "test-token" else None)
        self.auth.start()
        main.app.dependency_overrides[get_db] = lambda: self.db
        self.settings_patch = patch.object(ranking_controller, "get_settings", return_value=self.config)
        self.settings_patch.start()
        self.client = TestClient(main.app, headers={"Origin": "http://testserver"})

    def tearDown(self):
        """清理全局依赖和认证覆盖，避免影响其他测试。"""
        self.client.close()
        self.settings_patch.stop()
        main.app.dependency_overrides.clear()
        RankingTests.tearDown(self)

    def test_growth_stars_are_public_and_ties_span_pages(self):
        """星数降序、同星并列，第二页名次仍从全榜计算且不泄露认证字段。"""
        RankingTests.seed_growth(self)
        self.config.progression_enabled = True
        response = self.client.get('/api/rankings/growth/stars?page_size=1&page=2')
        self.assertEqual(response.status_code, 200, response.text)
        value = response.json()
        self.assertEqual(value['total'], 4)
        self.assertEqual(value['entries'][0]['rank'], 1)
        self.assertEqual(value['entries'][0]['total_stars'], 8)
        self.assertEqual(set(value['entries'][0]), {'rank', 'user_id', 'username', 'avatar_id', 'total_stars', 'level', 'xp'})
        third = self.client.get('/api/rankings/growth/stars?page_size=1&page=3').json()
        self.assertEqual(third['entries'][0]['rank'], 3)

    def test_growth_levels_follow_authoritative_experience(self):
        """等级复用账号阈值；同等级按经验排序，相同经验并列。"""
        RankingTests.seed_growth(self)
        self.config.progression_enabled = True
        value = self.client.get('/api/rankings/growth/level').json()
        self.assertEqual([row['xp'] for row in value['entries']], [180, 180, 179, 90])
        self.assertEqual([row['rank'] for row in value['entries']], [1, 1, 3, 4])
        for row in value['entries']:
            self.assertEqual(row['level'], account_level(row['xp']))

    def test_growth_bounds_empty_board_and_disabled_feature(self):
        """未开放时不查成长表；空榜不伪造零分玩家，拒绝未知类别及无限页大小。"""
        self.config.progression_enabled = False
        with patch.object(service.repository, 'growth_ranking_rows', side_effect=AssertionError('disabled query')):
            self.assertEqual(self.client.get('/api/rankings/growth/stars').status_code, 404)
        self.config.progression_enabled = True
        self.assertEqual(self.client.get('/api/rankings/growth/stars').json()['entries'], [])
        for path in ['/api/rankings/growth/unknown', '/api/rankings/growth/stars?page=0',
                     '/api/rankings/growth/level?page_size=51']:
            self.assertEqual(self.client.get(path).status_code, 422)

    def test_public_read_and_private_write_contract(self):
        """公开榜单不要求登录，个人记录和写入必须认证及同源。"""
        self.assertEqual(self.client.get("/api/rankings/mine").json()["entries"], [])
        self.assertEqual(self.client.get("/api/rankings/total").status_code, 422)
        self.assertEqual(self.client.get("/api/records/me?category=total").status_code, 422)
        self.assertEqual(self.client.get("/api/records/me").status_code, 401)
        body = {"request_id": str(uuid4())}
        self.assertEqual(self.client.post("/api/challenges/start", json=body).status_code, 401)
        self.client.cookies.set(self.config.session_cookie_name, "test-token")
        self.assertEqual(self.client.post("/api/challenges/start", json=body, headers={"Origin": "https://other.example"}).status_code, 403)
        first = self.client.post("/api/challenges/start", json=body).json()
        second = self.client.post("/api/challenges/start", json=body).json()
        self.assertEqual(first, second)
        self.assertEqual(self.client.get("/api/challenges/config").json(), {"quick_complete_enabled": False})

    def test_resume_only_reads_own_current_run(self):
        """恢复不建新轮次；未登录、其他账号和已失效轮次均不可读取。"""
        state = service.start_transaction("test-token", StartRequest(request_id=uuid4()), self.db)
        path = f"/api/challenges/{state['run_id']}"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.client.cookies.set(self.config.session_cookie_name, "test-token")
        self.assertEqual(self.client.get(path).json(), state)
        other = User(id=2, username="其他", username_key="其他", password_hash="test-only", created_at=utc_now())
        self.db.add(other)
        self.db.commit()
        with patch.object(service.auth_service, "current_session", return_value=(None, other)):
            self.assertEqual(self.client.get(path).status_code, 409)
        self.assertEqual(self.client.get(path).json(), state)
        service.start_transaction("test-token", StartRequest(request_id=uuid4()), self.db)
        self.assertEqual(self.client.get(path).status_code, 409)

    def test_payload_bounds_and_body_limit(self):
        """限制类别、页大小和实际请求字节，错误响应不回显任意输入。"""
        self.assertEqual(self.client.get("/api/rankings/unknown").status_code, 422)
        self.assertEqual(self.client.get("/api/rankings/total?page_size=100").status_code, 422)
        self.assertEqual(self.client.post("/api/challenges/start", content=b"x" * 4200).status_code, 413)
        payload = {"category": "mine", "revision": 0, "attempt_id": str(uuid4()), "duration_seconds": -1}
        self.assertEqual(self.client.post(f"/api/challenges/{uuid4()}/complete", json=payload).status_code, 422)
        payload["duration_seconds"] = True
        self.assertEqual(self.client.post(f"/api/challenges/{uuid4()}/complete", json=payload).status_code, 422)
