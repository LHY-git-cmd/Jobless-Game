"""可选真实 MySQL/Flyway 联调：仅允许显式配置的专用测试库，不创建生产表或替代数据库。

设置 TEST_DATABASE_URL（MySQL SQLAlchemy URL，数据库名以 jobless_auth_test_ 开头）
和 TEST_FLYWAY_COMMAND（Flyway 可执行文件路径）后运行本模块；未配置时明确跳过。
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
from unittest import TestCase, skipUnless
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, inspect, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from backend.app import main
from backend.app.common.database import get_db
from backend.app.common.config import get_settings
from backend.app.common.exceptions import AppError
from backend.app.services import auth_service
from backend.app.services.login_limiter import LoginRateLimiter
from backend.app.models.entities import AuthSession, User
from backend.app.models.schemas.auth import LoginRequest
from backend.app.common.security import utc_now
from backend.app.models.entities import progression, cosmetic, pk, matchmaking

ROOT = Path(__file__).resolve().parents[2]
TEST_URL = os.getenv("TEST_DATABASE_URL")
FLYWAY_COMMAND = os.getenv("TEST_FLYWAY_COMMAND")


@skipUnless(TEST_URL and FLYWAY_COMMAND, "未配置专用 TEST_DATABASE_URL 与 TEST_FLYWAY_COMMAND，真实 MySQL/Flyway 联调待完成")
class MySQLIntegrationTests(TestCase):
    """执行真实迁移、唯一键竞争、持久化会话和连接池超时。"""

    @classmethod
    def setUpClass(cls):
        """先核对专用测试库，再通过 Flyway 执行 SQL；不调用 ORM create_all。"""
        url = make_url(TEST_URL)
        if url.drivername != "mysql+pymysql" or not (url.database or "").startswith("jobless_auth_test_"):
            raise ValueError("只允许 mysql+pymysql 且数据库名以 jobless_auth_test_ 开头的专用测试库")
        cls.engine = create_engine(url, pool_size=3, max_overflow=0, pool_timeout=.2, connect_args={"connect_timeout": 3, "read_timeout": 5, "write_timeout": 5})
        expected_new = {v.__tablename__ for module in (progression, cosmetic, pk, matchmaking)
                        for v in vars(module).values() if isinstance(v, type) and hasattr(v, '__tablename__')}
        unexpected = set(inspect(cls.engine).get_table_names()) - expected_new - {"users", "auth_sessions", "flyway_schema_history", "challenge_progress", "completion_records", "leaderboard_entries", "forum_posts", "forum_comments", "forum_post_likes", "forum_comment_likes", "forum_notifications"}
        if unexpected:
            raise ValueError("测试库存在其他业务表，已停止")
        env = dict(os.environ)
        env.update({
            "FLYWAY_URL": f"jdbc:mysql://{url.host}:{url.port or 3306}/{url.database}?serverTimezone=UTC",
            "FLYWAY_USER": url.username or "",
            "FLYWAY_PASSWORD": url.password or "",
            "FLYWAY_LOCATIONS": f"filesystem:{(ROOT / 'backend/migrations').as_posix()}",
            "FLYWAY_CLEAN_DISABLED": "true",
            "FLYWAY_BASELINE_ON_MIGRATE": "false",
            "JAVA_ARGS": "-Xms32m -Xmx256m",
        })
        output_dir = ROOT / "artifacts/backend"
        output_dir.mkdir(parents=True, exist_ok=True)
        with (output_dir / "mysql-flyway.log").open("w", encoding="utf-8") as log:
            for action in ["migrate", "migrate", "info"]:
                result = subprocess.run([FLYWAY_COMMAND, "-outputType=json", action], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                log.write(result.stdout + result.stderr)
                if result.returncode:
                    raise AssertionError("Flyway 执行失败，详见本地 mysql-flyway.log；不要将凭据粘贴进报告")
                if action == "info":
                    data = json.loads(result.stdout)
                    if any(item.get("state") == "Pending" for item in data.get("migrations", [])):
                        raise AssertionError("Flyway 重跑后仍有 Pending 迁移")
        cls.sessions = sessionmaker(cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls):
        """关闭测试连接池。"""
        cls.engine.dispose()

    def setUp(self):
        self.keys = []
        def test_db():
            with self.sessions() as db:
                yield db
        main.app.dependency_overrides[get_db] = test_db
        auth_service.rate_limiter = LoginRateLimiter(100, 60)
        self.client = TestClient(main.app, headers={"Origin": "http://testserver"})

    def tearDown(self):
        """只删除本用例创建的唯一测试账号；会话由外键级联删除。"""
        self.client.close()
        main.app.dependency_overrides.clear()
        with self.sessions() as db:
            # 论坛没有删除业务；测试按外键顺序仅清理本例账号产生的隔离数据。
            from backend.app.models.entities.forum import ForumPost, ForumComment, ForumPostLike, ForumCommentLike, ForumNotification
            ids = list(db.scalars(select(User.id).where(User.username_key.in_(self.keys))))
            posts = select(ForumPost.id).where(ForumPost.user_id.in_(ids))
            comments = select(ForumComment.id).where(ForumComment.post_id.in_(posts))
            db.execute(delete(ForumNotification).where(ForumNotification.post_id.in_(posts)))
            db.execute(delete(ForumCommentLike).where(ForumCommentLike.comment_id.in_(comments)))
            db.execute(delete(ForumPostLike).where(ForumPostLike.post_id.in_(posts)))
            for comment_id in db.scalars(select(ForumComment.id).where(ForumComment.post_id.in_(posts)).order_by(ForumComment.id.desc())).all():
                db.execute(delete(ForumComment).where(ForumComment.id == comment_id))
            db.execute(delete(ForumPost).where(ForumPost.user_id.in_(ids)))
            db.execute(delete(User).where(User.username_key.in_(self.keys)))
            db.commit()

    def new_name(self):
        """生成满足 12 个字符上限的隔离测试账号。"""
        name = "qa" + uuid4().hex[:10]
        self.keys.append(name)
        return name

    def test_real_cookie_expiry_and_logout(self):
        name = self.new_name()
        response = self.client.post("/api/auth/login", json={"username": name, "password": " secret "})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["created"])
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        with self.sessions() as db:
            user = db.scalar(select(User).where(User.username_key == name))
            self.assertTrue(user.password_hash.startswith("$argon2id$"))
            db.execute(update(AuthSession).where(AuthSession.user_id == user.id).values(expires_at=utc_now() - timedelta(seconds=1)))
            db.commit()
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

        self.assertEqual(self.client.post("/api/auth/login", json={"username": name.upper(), "password": " secret "}).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_forum_v4_foreign_keys_and_concurrent_idempotency(self):
        """真实 V4 外键/唯一键及 InnoDB 并发建帖、点赞、计数和提醒一致性。"""
        from backend.app.services import forum_service as forum
        from backend.app.models.schemas.forum import PostRequest, CommentRequest
        from backend.app.models.entities.forum import ForumPost, ForumPostLike, ForumNotification
        from sqlalchemy.exc import IntegrityError
        with self.sessions() as db:
            author, _, first, _ = auth_service.login_transaction(LoginRequest(username=self.new_name(), password='test-password'), db, get_settings())
            actor, _, second, _ = auth_service.login_transaction(LoginRequest(username=self.new_name(), password='test-password'), db, get_settings())
            author_id, actor_id = author.id, actor.id
        payload = PostRequest(request_id=uuid4(), body='仅专用测试库')

        def create():
            """独立连接同时重试同一次建帖，不使用进程内锁。"""
            with self.sessions() as db:
                return forum.write_transaction(first, 'create_post', payload, None, db)
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _:create(), range(3)))
        post_id = results[0]['id']
        self.assertEqual(len({item['id'] for item in results}),1)

        def like(enabled):
            """每个点赞事务使用独立连接，依靠唯一键与内容行锁。"""
            with self.sessions() as db:
                return forum.write_transaction(second,'posts',enabled,post_id,db)
        for enabled in (True,False,False,True):
            with ThreadPoolExecutor(max_workers=3) as pool:
                outcomes=list(pool.map(like,[enabled]*3))
            self.assertTrue(all(item['like_count']==int(enabled) for item in outcomes))
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(ForumPostLike).where(ForumPostLike.post_id==post_id)).all()),1)
            self.assertEqual(len(db.scalars(select(ForumNotification).where(ForumNotification.post_id==post_id)).all()),1)
            notice=forum.read_transaction(first,'notifications',{'cursor':None,'limit':20},db)
            forum.write_transaction(first,'read',None,notice['items'][0]['id'],db)
            root=forum.write_transaction(first,'create_comment',CommentRequest(request_id=uuid4(),body='根评论'),post_id,db)
            reply=forum.write_transaction(second,'create_comment',CommentRequest(request_id=uuid4(),body='回复',reply_to_comment_id=root['id']),post_id,db)
            self.assertEqual(reply['root_comment_id'],root['id'])
            self.assertEqual(forum.read_transaction(first,'post',{'post_id':post_id},db)['comment_count'],2)
        with self.sessions() as db:
            db.add(ForumPost(user_id=author_id,request_id=str(payload.request_id),title='重复',body='b',created_at=utc_now()))
            with self.assertRaises(IntegrityError):db.commit()
            db.rollback()
            db.add(ForumPostLike(post_id=9007199254740991,user_id=actor_id,created_at=utc_now()))
            with self.assertRaises(IntegrityError):db.commit()
            db.rollback()
        self.assertGreaterEqual(len(inspect(self.engine).get_foreign_keys('forum_comments')),4)

    def test_two_connections_race_on_case_insensitive_account(self):
        name = self.new_name()
        def login_once(display, password):
            with self.sessions() as db:
                try:
                    user, created, _, _ = auth_service.login_transaction(LoginRequest(username=display, password=password), db, get_settings())
                    return user.id, created
                except AppError as error:
                    self.assertEqual(error.status_code, 401)
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(login_once, name, "first-password")
            second = pool.submit(login_once, name.upper(), "other-password")
            outcomes = [first.result(), second.result()]
        self.assertEqual(sum(outcome is not None for outcome in outcomes), 1)
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(User).where(User.username_key == name)).all()), 1)

    def test_ranking_concurrent_retry_and_retention(self):
        """真实 InnoDB 用户锁使并发重复提交只记一次，V2 快照与保留规则可读。"""
        from backend.app.services import ranking_service
        from backend.app.models.schemas.ranking import StartRequest, CompleteRequest
        from backend.app.models.entities.ranking import CompletionRecord
        name = self.new_name()
        with self.sessions() as db:
            user, _, raw, _ = auth_service.login_transaction(LoginRequest(username=name, password="test-password"), db, get_settings())
            user_id = user.id
            state = ranking_service.start_transaction(raw, StartRequest(request_id=uuid4()), db)
        payload = CompleteRequest(category="mine", revision=0, attempt_id=state["levels"][0]["attempt_id"], duration_seconds=10)

        def submit():
            """每个并发写入独立使用会话，依赖真实行锁而非进程锁。"""
            with self.sessions() as db:
                return ranking_service.complete_transaction(raw, state["run_id"], payload, db, get_settings())

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(results[0], results[1])
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(CompletionRecord).where(CompletionRecord.user_id == user_id)).all()), 1)
            self.assertEqual(ranking_service.records_transaction(raw, "mine", db)["best"]["duration_seconds"], 10)
            for category, seconds in [("akari", 20), ("sudoku", 30)]:
                idx = ranking_service.GAMES.index(category)
                payload = CompleteRequest(category=category, revision=0, attempt_id=state["levels"][idx]["attempt_id"], duration_seconds=seconds)
                state = ranking_service.complete_transaction(raw, state["run_id"], payload, db, get_settings())
            self.assertEqual(db.scalars(select(CompletionRecord).where(CompletionRecord.user_id == user_id, CompletionRecord.category == "total")).all(), [])

    def test_pool_exhaustion_returns_bounded_503(self):
        # 占满真实测试库三条连接，API 应在 pool_timeout 后返回 503。
        held = [self.engine.connect() for _ in range(3)]
        try:
            self.client.cookies.set(get_settings().session_cookie_name, "test-token")
            self.assertEqual(self.client.get("/api/auth/me").status_code, 503)
        finally:
            for connection in held:
                connection.close()

    def test_avatar_defaults_and_persistence(self):
        """真实 Flyway 新列的默认值与编号更新应在重新登录后保持。"""
        name = self.new_name()
        first = self.client.post("/api/auth/login", json={"username": name, "password": "avatar-secret"})
        self.assertEqual(first.json()["user"]["avatar_id"], 1)
        self.assertEqual(self.client.put("/api/auth/avatar", json={"avatar_id": 17}).status_code, 200)
        self.client.post("/api/auth/logout")
        again = self.client.post("/api/auth/login", json={"username": name, "password": "avatar-secret"})
        self.assertEqual(again.json()["user"]["avatar_id"], 17)

    def test_v5_real_innodb_concurrent_completions_award_once(self):
        """两个尝试并发同关结算，永久里程碑唯一键与用户锁共同防重。"""
        from backend.app.services import progression_service as service
        from backend.content_check import akari_solutions
        from threading import Barrier
        self.client.post('/api/auth/login', json={'username': self.new_name(), 'password': 'progression-test'})
        raw = self.client.cookies.get(get_settings().session_cookie_name)
        with self.sessions() as db:
            first = service.dispatch(raw, db, 'attempt_create', data={'level_id': 'akari-001', 'level_version': 1, 'mode': 'campaign'}, key=str(uuid4())).data
            original = db.get(progression.GameAttempt, first['attempt_id'])
            # 防御性竞争夹具：模拟历史版本留下同关活跃尝试；正常API不允许创建第二个。
            second_id = str(uuid4())
            clone = progression.GameAttempt(attempt_id=second_id, user_id=original.user_id, level_id=original.level_id,
                    level_version=original.level_version, game_id=original.game_id, mode=original.mode,
                    status='active', revision=0, started_at=original.started_at, expires_at=original.expires_at, board={})
            db.add(clone); db.commit()
            uid = original.user_id
        barrier = Barrier(2)
        payload = {'bulbs': akari_solutions(first['puzzle']['map'])[0]}
        def complete(attempt_id):
            """独立连接在同一屏障后结算，实际争用InnoDB锁。"""
            with self.sessions() as db:
                barrier.wait(timeout=10)
                return service.dispatch(raw, db, 'completion_put', rid=attempt_id, data=payload, received_at=utc_now()).data
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(complete, (first['attempt_id'], second_id)))
        self.assertEqual(sorted(r['awarded_xp'] for r in results), [0, 80])
        with self.sessions() as db:
            self.assertEqual(db.get(progression.PlayerProgression, uid).xp, 80)
            self.assertEqual(len(db.scalars(select(progression.ProgressionGrant).where(progression.ProgressionGrant.user_id == uid)).all()), 4)
            self.assertEqual(len(db.scalars(select(progression.PlayerQualification).where(progression.PlayerQualification.user_id == uid)).all()), 1)

    def test_v5_concurrent_create_replays_original_before_active_check(self):
        """并发同键创建只有一个资源，原始状态/位置稳定重放。"""
        from backend.app.services import progression_service as service
        from threading import Barrier
        self.client.post('/api/auth/login', json={'username': self.new_name(), 'password': 'progression-test'})
        raw = self.client.cookies.get(get_settings().session_cookie_name)
        key, barrier = str(uuid4()), Barrier(2)
        def create_one(_):
            """各自创建独立事务，认证快照早于对方提交也不能重复创建。"""
            with self.sessions() as db:
                barrier.wait(timeout=10)
                return service.dispatch(raw, db, 'attempt_create', data={'level_id': 'akari-001', 'level_version': 1, 'mode': 'campaign'}, key=key)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create_one, range(2)))
        self.assertEqual(results[0].data, results[1].data)
        self.assertEqual(results[0].headers, results[1].headers)

    def test_v10_mine_catalog_and_concurrent_reward(self):
        """真实V10/V11定义与源文件一致，同一新扫雷终盘并发重试只授予6经验。"""
        from backend.app.services import progression_service as service
        from backend.app.common.game_catalog import MINE_LEVELS
        from threading import Barrier
        from copy import deepcopy
        self.client.post('/api/auth/login', json={'username': self.new_name(), 'password': 'mine-v10-test'})
        raw = self.client.cookies.get(get_settings().session_cookie_name)
        with self.sessions() as db:
            for definition in MINE_LEVELS:
                self.assertEqual(db.get(progression.GameLevelVersion, (definition['level_id'], 1)).definition, definition)
            attempt = service.dispatch(raw, db, 'attempt_create', data={
                'level_id': 'mine-v2-easy-10', 'level_version': 1, 'mode': 'campaign'}, key=str(uuid4())).data
            row = db.get(progression.GameAttempt, attempt['attempt_id'])
            uid = row.user_id
            board = deepcopy(row.board)
            board['revealed'] = sorted(set(range(100))-set(board['mine_indices']))
            board['outcome'] = 'won'
            board['finished_at'] = utc_now().isoformat()
            row.board = board
            db.commit()
        barrier = Barrier(2)
        def complete(_):
            """各请求用独立连接竞争同一账号锁及不可变结算资源。"""
            with self.sessions() as db:
                barrier.wait(timeout=10)
                return service.dispatch(raw, db, 'completion_put', rid=attempt['attempt_id'], data={}, received_at=utc_now()).data
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(complete, range(2)))
        self.assertEqual(results[0], results[1])
        with self.sessions() as db:
            self.assertEqual((db.get(progression.PlayerProgression, uid).xp, db.get(progression.PlayerProgression, uid).total_stars), (6,3))
            self.assertEqual(len(db.scalars(select(progression.ProgressionGrant).where(progression.ProgressionGrant.user_id==uid)).all()), 3)

    def test_v12_sudoku_catalog_and_concurrent_reward(self):
        """真实V12十三题定义一致，同局重试及历史双尝试并发只授一次奖励。"""
        from backend.app.services import progression_service as service
        from backend.app.common.game_catalog import SUDOKU_LEVELS
        from backend.sudoku_content import solutions
        from threading import Barrier
        from copy import deepcopy
        self.client.post('/api/auth/login',json={'username':self.new_name(),'password':'sudoku-v12-test'})
        raw=self.client.cookies.get(get_settings().session_cookie_name)
        with self.sessions() as db:
            for definition in SUDOKU_LEVELS:
                self.assertEqual(db.get(progression.GameLevelVersion,(definition['level_id'],1)).definition,definition)
            attempt=service.dispatch(raw,db,'attempt_create',data={
                'level_id':'sudoku-v2-easy-01','level_version':1,'mode':'campaign'},key=str(uuid4())).data
            original=db.get(progression.GameAttempt,attempt['attempt_id']);uid=original.user_id;second_id=str(uuid4())
            # 防御性夹具模拟旧版本遗留的同题双活跃局，正常创建接口禁止此状态。
            db.add(progression.GameAttempt(attempt_id=second_id,user_id=uid,level_id=original.level_id,
                level_version=1,game_id='sudoku',mode='campaign',status='active',revision=0,
                started_at=original.started_at,expires_at=original.expires_at,board=deepcopy(original.board)))
            db.commit()
        barrier=Barrier(3);payload={'values':solutions(attempt['puzzle']['values'])[0]}

        def complete(rid):
            """独立连接实际争用InnoDB账号锁，收到已存在结果时读取同一快照。"""
            with self.sessions() as db:
                barrier.wait(timeout=10)
                return service.dispatch(raw,db,'completion_put',rid=rid,data=payload,received_at=utc_now()).data
        with ThreadPoolExecutor(max_workers=3) as executor:
            results=list(executor.map(complete,[attempt['attempt_id'],attempt['attempt_id'],second_id]))
        self.assertEqual(results[0],results[1])
        self.assertEqual(sorted(v['awarded_xp'] for v in (results[0],results[2])),[0,6])
        with self.sessions() as db:
            summary=db.get(progression.PlayerProgression,uid)
            self.assertEqual((summary.total_stars,summary.xp),(3,6))
            self.assertEqual(len(db.scalars(select(progression.ProgressionGrant).where(progression.ProgressionGrant.user_id==uid)).all()),3)
            self.assertIsNotNone(db.get(progression.PlayerQualification,(uid,'sudoku-beginner-001')))

    def test_v13_akari_catalog_completion_and_qualification(self):
        """真实V13发布16项冻结题目，所有尺寸可结算且重放不重复授奖。"""
        from backend.app.services import progression_service as service
        from backend.app.common.game_catalog import AKARI_LEVELS
        from backend.content_check import akari_solutions
        self.client.post('/api/auth/login',json={'username':self.new_name(),'password':'akari-v13-test'})
        raw=self.client.cookies.get(get_settings().session_cookie_name)
        with self.sessions() as db:
            for definition in AKARI_LEVELS:
                self.assertEqual(db.get(progression.GameLevelVersion,(definition['level_id'],1)).definition,definition)
            self.assertIsNotNone(db.get(progression.GameLevelVersion,('akari-001',1)))
        total_xp=0
        for level in AKARI_LEVELS:
            service.limiter.clear()
            with self.sessions() as db:
                attempt=service.dispatch(raw,db,'attempt_create',data={
                    'level_id':level['level_id'],'level_version':1,'mode':'campaign'},key=str(uuid4())).data
            payload={'bulbs':akari_solutions(level['puzzle']['map'])[0]}
            with self.sessions() as db:
                result=service.dispatch(raw,db,'completion_put',rid=attempt['attempt_id'],data=payload,received_at=utc_now()).data
                uid=db.get(progression.GameAttempt,attempt['attempt_id']).user_id
            with self.sessions() as db:
                replay=service.dispatch(raw,db,'completion_put',rid=attempt['attempt_id'],data=payload,received_at=utc_now()).data
                self.assertEqual(replay,result)
            total_xp+=result['awarded_xp']
            self.assertEqual(result['stars'],1 if level['number']==0 else 3)
        with self.sessions() as db:
            summary=db.get(progression.PlayerProgression,uid)
            self.assertEqual((summary.total_stars,summary.xp),(46,total_xp))
            self.assertIsNotNone(db.get(progression.PlayerQualification,(uid,'akari-001')))

    def test_v7_v8_cancel_pair_competition_has_one_outcome(self):
        """真实MySQL上竞争取消/配对：只能取消成功或配对成功，不能双重占用。"""
        from backend.app.services import pk_service as service
        from backend.app.common.game_catalog import QUALIFICATIONS
        from threading import Barrier
        from backend.app.services.pk_runtime import runtime
        tokens, uids = [], []
        for _ in range(2):
            self.client.post('/api/auth/login', json={'username': self.new_name(), 'password': 'pk-test-secret'})
            raw = self.client.cookies.get(get_settings().session_cookie_name)
            tokens.append(raw)
            with self.sessions() as db:
                uid = auth_service.current_session(raw, db)[1].id
                uids.append(uid)
                for key in QUALIFICATIONS:
                    db.add(progression.PlayerQualification(user_id=uid, requirement_id=key, level_version=1,
                           attempt_id=str(uuid4()), completed_at=utc_now()))
                db.commit()
        with self.sessions() as db:
            first = service.dispatch(tokens[0], db, 'ticket_create', data={'game_id': 'akari', 'difficulty': 'normal'}, key=str(uuid4())).data
        barrier = Barrier(2)
        def cancel_one():
            """取消方与第二玩家入队同时到达。"""
            with self.sessions() as db:
                barrier.wait(timeout=10)
                try:
                    return service.dispatch(tokens[0], db, 'ticket_cancel', rid=first['ticket_id']).status
                except AppError as exc:
                    return exc.status_code
        def pair_one():
            """配对事务重查双方资格及唯一占用。"""
            with self.sessions() as db:
                barrier.wait(timeout=10)
                return service.dispatch(tokens[1], db, 'ticket_create', data={'game_id': 'akari', 'difficulty': 'normal'}, key=str(uuid4())).data
        room_ids = []
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                cancelled, paired = executor.submit(cancel_one), executor.submit(pair_one)
                cancel_status, second = cancelled.result(timeout=15), paired.result(timeout=15)
            with self.sessions() as db:
                a = db.get(matchmaking.MatchmakingTicket, first['ticket_id'])
                b = db.get(matchmaking.MatchmakingTicket, second['ticket_id'])
                if a.status == 'matched':
                    room_ids = [a.room_id]
                    self.assertEqual((cancel_status, b.status, a.room_id), (409, 'matched', b.room_id))
                    self.assertEqual([db.get(pk.PlayerPKOccupancy, uid).room_id for uid in uids], [a.room_id, a.room_id])
                else:
                    self.assertEqual((cancel_status, a.status, b.status), (204, 'cancelled', 'waiting'))
                    self.assertIsNone(db.get(pk.PlayerPKOccupancy, uids[0]).ticket_id)
                    self.assertEqual(db.get(pk.PlayerPKOccupancy, uids[1]).ticket_id, b.ticket_id)
        finally:
            service.maintenance(self.sessions, restart=True)
            with self.sessions() as db:
                if room_ids:
                    db.execute(delete(pk.PKRoom).where(pk.PKRoom.room_id.in_(room_ids)))
                db.commit()
            runtime.reset()

    def test_v5_concurrent_mine_loss_is_irreversible(self):
        """两连接揭安全格/踩雷按同一账号锁串行，lost后不能继续构造won。"""
        from backend.app.services import progression_service as service
        from threading import Barrier
        self.client.post('/api/auth/login', json={'username': self.new_name(), 'password': 'mine-test-secret'})
        raw = self.client.cookies.get(get_settings().session_cookie_name)
        with self.sessions() as db:
            attempt = service.dispatch(raw, db, 'attempt_create', data={'level_id': 'mine-beginner-001', 'level_version': 1, 'mode': 'qualification'}, key=str(uuid4())).data
            row = db.get(progression.GameAttempt, attempt['attempt_id'])
            mines = set(row.board['mine_indices'])
            uid = row.user_id
        barrier = Barrier(2)
        def reveal_one(index):
            """每个动作使用独立事务，服务端雷图不下发给浏览器。"""
            with self.sessions() as db:
                barrier.wait(timeout=10)
                try:
                    return service.dispatch(raw, db, 'reveal', rid=attempt['attempt_id'], index=index).status
                except AppError as exc:
                    return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(reveal_one, (next(iter(mines)), next(iter(set(range(100))-mines)))))
        self.assertIn(201, results)
        with self.sessions() as db:
            row = db.get(progression.GameAttempt, attempt['attempt_id'])
            self.assertEqual((row.status, row.board['outcome']), ('lost', 'lost'))
            self.assertIsNone(db.get(progression.PlayerQualification, (uid, 'mine-beginner-001')))


    def test_mine_clock_pause_survives_connection_change(self):
        """真实MySQL JSON持久化暂停，换连接恢复并拒绝迟到旧修订。"""
        from backend.app.services import progression_service as service
        self.client.post('/api/auth/login',json={'username':self.new_name(),'password':'mine-clock-test'})
        raw=self.client.cookies.get(get_settings().session_cookie_name)
        with self.sessions() as db:
            first=service.dispatch(raw,db,'attempt_create',data={'level_id':'mine-v2-easy-10','level_version':1,'mode':'campaign'},key=str(uuid4())).data
        with self.sessions() as db:
            paused=service.dispatch(raw,db,'mine_clock',rid=first['attempt_id'],data={'paused':True,'revision':0,'command_id':str(uuid4())}).data
        with self.sessions() as db:
            restored=service.dispatch(raw,db,'attempt_get',rid=first['attempt_id']).data
            self.assertTrue(restored['timing']['paused'])
            self.assertEqual(restored['timing']['elapsed_ms'],paused['timing']['elapsed_ms'])
            continued=service.dispatch(raw,db,'mine_clock',rid=first['attempt_id'],data={'paused':False,'revision':restored['timing']['revision'],'command_id':str(uuid4())}).data
            self.assertFalse(continued['timing']['paused'])
        with self.sessions() as db:
            with self.assertRaises(AppError):
                service.dispatch(raw,db,'mine_clock',rid=first['attempt_id'],data={'paused':True,'revision':0,'command_id':str(uuid4())})


if __name__ == "__main__":
    import unittest
    unittest.main()
