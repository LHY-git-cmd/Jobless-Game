"""正式成长API的TDD契约：SQLite功能验证；InnoDB竞争另行验收。"""

from datetime import timedelta
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend.app import main
from backend.app.common.database import Base, get_db
from backend.app.common.config import get_settings
from backend.app.common.security import utc_now
from backend.app.models.entities import User
from backend.app.services import auth_service
from backend.app.common.game_catalog import LEVELS
from backend.content_check import akari_solutions, sudoku_solutions


class ProgressionAPI(TestCase):
    """使用真实路由与事务，在隔离库内核对不可伪造成长。"""

    def setUp(self):
        """仅创建隔离SQLite；正式表仍由Flyway管理。"""
        from backend.app.models.entities.progression import GameLevel, GameLevelVersion
        self.engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        with self.sessions() as db:
            for uid in (1, 2):
                db.add(User(id=uid, username=f'p{uid}', username_key=f'p{uid}', password_hash='test', created_at=utc_now()))
            for item in LEVELS.values():
                db.add(GameLevel(level_id=item['level_id'], game_id=item['game_id'], order_index=item['order']))
                db.add(GameLevelVersion(level_id=item['level_id'], level_version=1, definition=item))
            db.commit()
        def dependency():
            """每请求独立会话，模拟生产释放语义。"""
            with self.sessions() as db:
                yield db
        main.app.dependency_overrides[get_db] = dependency
        self.auth = patch.object(auth_service, 'current_session', side_effect=lambda token, db:
                                 (None, db.get(User, int(token))) if token in ('1', '2') else None)
        self.auth.start()
        self.settings = get_settings()
        self.saved = {k: getattr(self.settings, k) for k in ('progression_enabled', 'cosmetics_enabled', 'pk_rooms_enabled', 'matchmaking_enabled')}
        for key in self.saved:
            setattr(self.settings, key, True)
        from backend.app.services import progression_service
        progression_service.limiter.clear()
        self.client = TestClient(main.app, headers={'Origin': 'http://testserver'})
        self.client.cookies.set(self.settings.session_cookie_name, '1')

    def tearDown(self):
        """还原全局依赖与开关，不影响其他API回归。"""
        self.client.close()
        self.auth.stop()
        main.app.dependency_overrides.clear()
        for key, value in self.saved.items():
            setattr(self.settings, key, value)
        self.engine.dispose()

    def create(self, level='akari-001', key=None):
        """仅使用稳定关卡ID与服务器版本，不传用时或奖励。"""
        return self.client.post('/api/v1/attempts', headers={'Idempotency-Key': key or str(uuid4())},
                                json={'level_id': level, 'level_version': 1, 'mode': 'campaign' if level.startswith('akari') else 'qualification'})

    def answer(self, attempt):
        """只在测试机离线求解绑定题，产品无一键通关入口。"""
        puzzle = attempt['puzzle']
        return {'bulbs': akari_solutions(puzzle['map'])[0]} if attempt['game_id'] == 'akari' else {'values': sudoku_solutions(puzzle['values'])[0]}

    def test_metadata_no_puzzle_and_attempt_idempotency_precedes_conflict(self):
        """目录不发题；同键重试优先于已有活跃尝试判断。"""
        data = self.client.get('/api/v1/levels?game_id=akari').json()
        self.assertEqual(len(data['items']), 10)
        self.assertNotIn('puzzle', data['items'][0])
        key = str(uuid4())
        first = self.create(key=key)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(self.create(key=key).json(), first.json())
        self.assertEqual(self.create('akari-002', key).status_code, 409)
        self.assertEqual(self.create().status_code, 409)
        self.assertIn('Location', first.headers)
        self.assertIn('ETag', first.headers)

    def test_completion_snapshot_and_no_reward_repetition(self):
        """相同终盘返回原快照；新尝试再次通关不奖励。"""
        attempt = self.create().json()
        url = attempt['links']['completion']
        payload = self.answer(attempt)
        first = self.client.put(url, json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json()['awarded_xp'], 80)
        again = self.client.put(url, json={'bulbs': list(reversed(payload['bulbs']))})
        self.assertEqual(again.status_code, 200)
        self.assertEqual(first.json(), again.json())
        self.assertEqual(self.client.put(url, json={'bulbs': []}).status_code, 409)
        second = self.create().json()
        result = self.client.put(second['links']['completion'], json=self.answer(second))
        self.assertEqual(result.json()['awarded_xp'], 0)
        self.assertEqual(self.client.get('/api/v1/me/progression').json()['xp'], 80)
        eligibility = self.client.get('/api/v1/me/pk-eligibility').json()
        self.assertFalse(eligibility['eligible'])
        self.assertEqual([r['completed'] for r in eligibility['requirements']], [False, True, False])

    def test_server_time_partial_stars_and_unlock(self):
        """服务器时间决定星级；前三关一星足够解锁第二组。"""
        from backend.app.models.entities.progression import GameAttempt
        self.assertEqual(self.create('akari-004').status_code, 403)
        for level in ('akari-001', 'akari-002', 'akari-003'):
            attempt = self.create(level).json()
            with self.sessions() as db:
                row = db.get(GameAttempt, attempt['attempt_id'])
                row.started_at = utc_now() - timedelta(milliseconds=LEVELS[level]['t2_ms'] + 1000)
                db.commit()
            result = self.client.put(attempt['links']['completion'], json=self.answer(attempt)).json()
            self.assertEqual((result['stars'], result['awarded_xp']), (1, 40))
        self.assertEqual(self.create('akari-004').status_code, 201)
        self.assertEqual(self.client.get('/api/v1/me/progression').json()['level'], 2)

    def test_bad_input_auth_origin_body_limit_and_foreign_attempt(self):
        """保护DTO、所有权、同源和新增v1体积，不回显终盘。"""
        attempt = self.create().json()
        url = attempt['links']['completion']
        for payload in ({'bulbs': []}, {'bulbs': [True]}, {'bulbs': [0, 0]}, {**self.answer(attempt), 'duration_ms': 0}):
            self.assertEqual(self.client.put(url, json=payload).status_code, 422)
        self.assertEqual(self.client.put(url, json=self.answer(attempt), headers={'Origin': 'https://evil.invalid'}).status_code, 403)
        self.assertEqual(self.client.put(url, content='x'*4097, headers={'Content-Type': 'application/json'}).status_code, 413)
        self.client.cookies.set(self.settings.session_cookie_name, '2')
        self.assertEqual(self.client.get(attempt['links']['self']).status_code, 404)
        self.client.cookies.clear()
        response = self.client.get('/api/v1/me/progression')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers['content-type'], 'application/problem+json')
        self.assertIn('request_id', response.json())

    def test_expiry_abandon_preconditions_and_read_only_get(self):
        """GET不改状态；放弃要求ETag；过期不能领奖。"""
        from backend.app.models.entities.progression import GameAttempt
        response = self.create()
        attempt = response.json()
        url = attempt['links']['self']
        self.assertEqual(self.client.patch(url, json={'status': 'abandoned'}).status_code, 428)
        self.assertEqual(self.client.patch(url, json={'status': 'abandoned'}, headers={'If-Match': '"bad"'}).status_code, 412)
        self.assertEqual(self.client.patch(url, json={'status': 'abandoned'}, headers={'If-Match': response.headers['etag']}).status_code, 200)
        self.assertEqual(self.client.put(attempt['links']['completion'], json=self.answer(attempt)).status_code, 409)
        new = self.create().json()
        with self.sessions() as db:
            row = db.get(GameAttempt, new['attempt_id'])
            row.expires_at = utc_now() - timedelta(seconds=1)
            db.commit()
        self.assertEqual(self.client.get(new['links']['self']).status_code, 410)
        with self.sessions() as db:
            self.assertEqual(db.get(GameAttempt, new['attempt_id']).status, 'active')

    def test_mine_hides_mines_replay_and_sudoku_qualification(self):
        """正式扫雷只能服务器揭格；数独保留给定盘，资格不发经验。"""
        from backend.app.models.entities.progression import GameAttempt
        attempt = self.create('mine-beginner-001').json()
        self.assertNotIn('mine_indices', str(attempt))
        self.assertEqual(self.client.put(attempt['links']['completion'], json={}).status_code, 422)
        with self.sessions() as db:
            mines = set(db.get(GameAttempt, attempt['attempt_id']).board['mine_indices'])
        for index in set(range(100)) - mines:
            response = self.client.put(f"{attempt['links']['self']}/reveals/{index}", json={})
            self.assertIn(response.status_code, (200, 201), response.text)
        self.assertEqual(response.json()['board']['outcome'], 'won')
        self.assertEqual(self.client.put(attempt['links']['completion'], json={}).status_code, 201)
        sudoku = self.create('sudoku-beginner-001').json()
        result = self.client.put(sudoku['links']['completion'], json=self.answer(sudoku))
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()['awarded_xp'], 0)
        self.assertEqual(self.client.get('/api/v1/me/progression').json()['xp'], 0)

    def test_transaction_failure_rolls_back_rewards(self):
        """快照写入前失败必须回滚资格、进度和经验。"""
        from backend.app.services import progression_service as service
        from backend.app.models.entities.progression import PlayerProgression
        attempt = self.create().json()
        with patch.object(service, 'grant_cosmetics', side_effect=RuntimeError('test-only')):
            with self.assertRaises(RuntimeError):
                self.client.put(attempt['links']['completion'], json=self.answer(attempt))
        with self.sessions() as db:
            self.assertIsNone(db.get(PlayerProgression, 1))
        self.assertEqual(self.client.put(attempt['links']['completion'], json=self.answer(attempt)).status_code, 201)

    def test_cosmetic_precondition_ownership_and_persistence(self):
        """默认外观可用，锁定主题不能靠参数装备。"""
        value = self.client.get('/api/v1/me/appearance')
        payload = {key: 'default' for key in ('theme_id', 'mine_skin_id', 'akari_skin_id', 'sudoku_skin_id')}
        self.assertEqual(self.client.put('/api/v1/me/appearance', json=payload).status_code, 428)
        locked = self.client.put('/api/v1/me/appearance', headers={'If-Match': value.headers['etag']}, json={**payload, 'theme_id': 'starlight'})
        self.assertEqual(locked.status_code, 403)
        self.assertEqual(self.client.put('/api/v1/me/appearance', headers={'If-Match': value.headers['etag']}, json=payload).status_code, 200)

    def test_star_improvement_and_version_change_never_reaward(self):
        """先一星再三星累计80经验；新题版本保留最高星和永久里程碑。"""
        from copy import deepcopy
        from backend.app.models.entities.progression import GameAttempt, GameLevelVersion
        attempt = self.create().json()
        with self.sessions() as db:
            db.get(GameAttempt, attempt['attempt_id']).started_at = utc_now()-timedelta(milliseconds=LEVELS['akari-001']['t2_ms']+1000)
            db.commit()
        first = self.client.put(attempt['links']['completion'], json=self.answer(attempt)).json()
        self.assertEqual((first['stars'], first['awarded_xp'], first['awarded_stars']), (1, 40, 1))
        next_attempt = self.create().json()
        second = self.client.put(next_attempt['links']['completion'], json=self.answer(next_attempt)).json()
        self.assertEqual((second['awarded_xp'], second['awarded_stars']), (40, 2))
        with self.sessions() as db:
            revised = deepcopy(LEVELS['akari-001']); revised['level_version'] = 2
            db.add(GameLevelVersion(level_id='akari-001', level_version=2, definition=revised)); db.commit()
        versioned = self.client.post('/api/v1/attempts', headers={'Idempotency-Key': str(uuid4())},
                    json={'level_id': 'akari-001', 'level_version': 2, 'mode': 'campaign'}).json()
        third = self.client.put(versioned['links']['completion'], json=self.answer(versioned)).json()
        self.assertEqual((third['awarded_xp'], third['awarded_stars'], third['progression']['xp']), (0, 0, 80))

    def test_legacy_client_reported_completions_do_not_grant_qualifications(self):
        """旧挑战即使三关全完成，也不能兑换正式成长或PK资格。"""
        state = self.client.post('/api/challenges/start', json={'request_id': str(uuid4())}).json()
        for index, category in enumerate(('mine', 'akari', 'sudoku')):
            response = self.client.post(f"/api/challenges/{state['run_id']}/complete", json={
                'category': category, 'revision': state['revision'], 'attempt_id': state['levels'][index]['attempt_id'],
                'duration_seconds': 1, 'development': False})
            self.assertEqual(response.status_code, 200, response.text)
            state = response.json()
        value = self.client.get('/api/v1/me/pk-eligibility').json()
        self.assertFalse(any(item['completed'] for item in value['requirements']))
        self.assertEqual(self.client.get('/api/v1/me/progression').json()['xp'], 0)

    def test_feature_disabled_and_cursor_pages(self):
        """关闭开关不触库上线新能力，分页不会重复关卡或无限返回。"""
        all_ids, cursor = [], None
        while True:
            page = self.client.get('/api/v1/me/level-progress?limit=2'+('&cursor='+cursor if cursor else '')).json()
            self.assertLessEqual(len(page['items']), 2)
            all_ids.extend(item['level_id'] for item in page['items'])
            cursor = page['next_cursor']
            if not cursor:
                break
        self.assertEqual(len(all_ids), len(set(all_ids)))
        from backend.app.common.game_catalog import published_levels
        self.assertEqual(len(all_ids), len(published_levels()))
        self.settings.progression_enabled = False
        response = self.client.get('/api/v1/me/progression')
        self.assertEqual((response.status_code, response.json()['code']), (404, 'feature_disabled'))

    def test_lost_mine_exposes_terminal_time_and_cannot_be_revived(self):
        """失败尝试返回停止时刻，重复揭同雷仍为原终态，完成不能获资格。"""
        from backend.app.models.entities.progression import GameAttempt
        attempt = self.create('mine-beginner-001').json()
        with self.sessions() as db:
            index = db.get(GameAttempt, attempt['attempt_id']).board['mine_indices'][0]
        path = f"{attempt['links']['self']}/reveals/{index}"
        lost = self.client.put(path, json={}).json()
        self.assertEqual(lost['status'], 'lost')
        self.assertIsNotNone(lost['ended_at'])
        repeat = self.client.put(path, json={}).json()
        self.assertEqual(repeat['ended_at'], lost['ended_at'])
        self.assertEqual(self.client.put(attempt['links']['completion'], json={}).status_code, 409)
