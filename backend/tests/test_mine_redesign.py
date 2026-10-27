"""作用：先验证五档扫雷的矩形边界、教学、首击安全及账号奖励契约。"""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase
from uuid import uuid4

from backend.tests import test_progression_v1 as fixture
from backend.app.common.game_catalog import LEVELS
from backend.app.common.security import utc_now
from backend.app.models.entities.progression import GameAttempt
from backend.app.services.game_rules import stars_for


IDS = ['mine-v2-tutorial', 'mine-v2-easy-10', 'mine-v2-easy-15', 'mine-v2-easy-20',
       'mine-v2-medium', 'mine-v2-hard', 'mine-v2-hell', 'mine-v2-medium-15', 'mine-v2-medium-20',
       'mine-v2-hard-15', 'mine-v2-hard-20', 'mine-v2-hell-15', 'mine-v2-hell-20']


class MineRedesign(TestCase):
    """复用隔离数据库夹具，不继承重复运行历史API测试。"""
    setUp = fixture.ProgressionAPI.setUp
    tearDown = fixture.ProgressionAPI.tearDown

    def start(self, level):
        """七项均直接开放，使用campaign请求正式星级与经验。"""
        response = self.client.post('/api/v1/attempts', headers={'Idempotency-Key': str(uuid4())},
                                   json={'level_id': level, 'level_version': 1, 'mode': 'campaign'})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def reveal(self, attempt, index):
        """每次只提交位置，不提交雷图或本地计算结果。"""
        return self.client.put(f"{attempt['links']['self']}/reveals/{index}", json={})

    def solve(self, attempt):
        """测试机读取隔离库隐藏雷区，逐格经真实路由验证通关。"""
        with self.sessions() as db:
            mines = set(db.get(GameAttempt, attempt['attempt_id']).board['mine_indices'])
        count = attempt['puzzle']['rows'] * attempt['puzzle']['cols']
        for index in sorted(set(range(count)) - mines):
            response = self.reveal(attempt, index)
            self.assertIn(response.status_code, (200, 201), response.text)
        return response.json()

    def test_catalog_and_time_boundaries(self):
        """四档普通难度均有三种尺寸，不发教学雷图；旧定义仍在内部可读。"""
        items = self.client.get('/api/v1/levels?game_id=mine').json()['items']
        self.assertEqual([v['level_id'] for v in items], IDS)
        self.assertEqual([(v['cols'], v['rows'], v['mine_count']) for v in items],
                         [(5,5,3), (10,10,10), (15,12,18), (20,15,30), (10,10,12), (10,10,15), (10,10,18),
                          (15,12,22), (20,15,36), (15,12,27), (20,15,45), (15,12,32), (20,15,54)])
        self.assertEqual([v['star_xp'] for v in items], [[2],[2,4,6],[3,6,9],[4,8,12],[3,6,9],[4,8,12],[5,10,15],
                                                     [5,10,15],[6,12,18],[6,12,18],[8,16,24],[8,16,24],[10,20,30]])
        for difficulty in ('easy','medium','hard','hell'):
            self.assertEqual([(v['cols'],v['rows']) for v in items if v['difficulty']==difficulty], [(10,10),(15,12),(20,15)])
        self.assertNotIn('puzzle', items[0])
        self.assertNotIn('mine_indices', str(items))
        level = LEVELS['mine-v2-easy-10']
        self.assertEqual([stars_for(level, v) for v in (75000,75001,150000,150001)], [3,2,2,1])
        self.assertEqual(stars_for(LEVELS[IDS[0]], 99999999), 1)
        self.assertIn('mine-beginner-001', LEVELS)

    def test_rectangular_edges_first_safe_and_victory(self):
        """两种矩形的末格可揭、首击命中原雷仍安全，全部安全格决定胜利。"""
        for level_id in IDS[2:4]:
            attempt = self.start(level_id)
            count = attempt['puzzle']['rows'] * attempt['puzzle']['cols']
            with self.sessions() as db:
                row = db.get(GameAttempt, attempt['attempt_id'])
                board = deepcopy(row.board)
                # 故意把最后一格放雷，确定性验证首击重布雷且雷数不变。
                # 原随机雷区可能已含末格；先去除再补入，避免构造重复雷而误报首击安全失败。
                original=[index for index in board['mine_indices'] if index!=count-1]
                board['mine_indices']=[*original[:len(board['mine_indices'])-1],count-1]
                row.board = board
                db.commit()
            first = self.reveal(attempt, count-1)
            self.assertEqual(first.status_code, 201, first.text)
            self.assertEqual(first.json()['board']['outcome'], 'active')
            self.assertIn(count-1, [v['index'] for v in first.json()['board']['revealed']])
            self.assertEqual(self.reveal(attempt, count).status_code, 422)
            with self.sessions() as db:
                mines = db.get(GameAttempt, attempt['attempt_id']).board['mine_indices']
                self.assertEqual(len(set(mines)), LEVELS[level_id]['mine_count'])
                self.assertNotIn(count-1, mines)
            final = self.solve(attempt)
            self.assertEqual(final['board']['outcome'], 'won')
            self.assertEqual(len(final['board']['revealed']), count-LEVELS[level_id]['mine_count'])
            self.assertIsNotNone(final['ended_at'])

    def test_reward_improvement_retry_and_frozen_terminal_time(self):
        """先一星再三星合计6经验；通关后等候/重试不会降低星级或重复发奖。"""
        first = self.start(IDS[1])
        with self.sessions() as db:
            db.get(GameAttempt, first['attempt_id']).started_at = utc_now()-timedelta(seconds=151)
            db.commit()
        self.solve(first)
        result = self.client.put(first['links']['completion'], json={})
        self.assertEqual((result.json()['stars'],result.json()['awarded_xp']), (1,2), result.text)
        second = self.start(IDS[1])
        self.solve(second)
        # 模拟75秒恰好通关后过了1小时才提交；只能使用持久化终盘时刻。
        with self.sessions() as db:
            row = db.get(GameAttempt, second['attempt_id'])
            row.started_at = utc_now()-timedelta(hours=1)
            board = deepcopy(row.board)
            row.ended_at = row.started_at+timedelta(seconds=75)
            board['finished_at'] = row.ended_at.isoformat()
            row.board = board
            db.commit()
        saved = self.client.put(second['links']['completion'], json={})
        self.assertEqual(saved.status_code, 201, saved.text)
        self.assertEqual((saved.json()['stars'],saved.json()['awarded_xp'],saved.json()['awarded_stars']), (3,4,2))
        self.assertEqual(saved.json()['duration_ms'], 75000)
        self.assertEqual(self.client.put(second['links']['completion'], json={}).json(), saved.json())
        third = self.start(IDS[1]); self.solve(third)
        self.assertEqual(self.client.put(third['links']['completion'], json={}).json()['awarded_xp'], 0)
        self.assertEqual(self.client.get('/api/v1/me/progression').json()['xp'], 6)
        self.assertEqual(self.client.get('/api/v1/me/pk-eligibility').json()['requirements'],[])

    def test_every_difficulty_xp_and_account_isolation(self):
        """各档直接三星精确给奖励，换号不能读局或继承星数。"""
        for level_id, xp in zip(IDS[1:], (6,9,12,9,12,15)):
            attempt = self.start(level_id); self.solve(attempt)
            result = self.client.put(attempt['links']['completion'], json={})
            self.assertEqual((result.json()['stars'], result.json()['awarded_xp']), (3,xp), result.text)
        self.client.cookies.set(self.settings.session_cookie_name, '2')
        self.assertEqual(self.client.get(attempt['links']['self']).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/me/progression').json()['xp'], 0)

    def test_new_large_boards_have_independent_mines_rewards_and_progress(self):
        """六个新增关卡均按自己的雷数判胜和发奖，不覆盖原10×10成绩。"""
        from backend.app.services import progression_service
        for level_id,xp in zip(IDS[7:],(15,18,18,24,24,30)):
            progression_service.limiter.clear()
            attempt=self.start(level_id)
            last=self.solve(attempt)
            self.assertEqual(last['board']['outcome'],'won')
            result=self.client.put(attempt['links']['completion'],json={})
            self.assertEqual(result.status_code,201,result.text)
            self.assertEqual((result.json()['stars'],result.json()['awarded_xp']),(3,xp))
        progress=self.client.get('/api/v1/me/level-progress?game_id=mine&limit=50').json()['items']
        self.assertEqual([v['best_stars'] for v in progress if v['level_id'] in IDS[4:7]],[0,0,0])

    def test_tutorial_requires_steps_and_rewards_once(self):
        """教学先揭0、理解数字、标记6，才允许自由排雷；误操作不使教学失败。"""
        attempt = self.start(IDS[0]); url = attempt['links']['self']
        self.assertEqual(self.reveal(attempt, 4).status_code, 409)
        self.assertEqual(self.client.put(url+'/tutorial-actions/flag', json={}).status_code, 409)
        first = self.reveal(attempt, 0)
        self.assertEqual(first.json()['board']['tutorial_step'], 1)
        self.assertEqual(self.reveal(attempt, 4).status_code, 409)
        for action, step in [('number',2), ('flag',3)]:
            response = self.client.put(url+'/tutorial-actions/'+action, json={})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['board']['tutorial_step'], step)
            replay = self.client.put(url+'/tutorial-actions/'+action, json={}).json()
            self.assertEqual((replay['board'], replay['revision']), (response.json()['board'], response.json()['revision']))
        self.assertEqual(self.reveal(attempt, 6).status_code, 409)
        self.solve(attempt)
        saved = self.client.put(attempt['links']['completion'], json={})
        self.assertEqual((saved.json()['stars'], saved.json()['awarded_xp']), (1,2), saved.text)
        self.assertFalse(self.client.get('/api/v1/me/pk-eligibility').json()['eligible'])
        again = self.start(IDS[0]); self.reveal(again,0)
        for action in ('number','flag'):
            self.client.put(again['links']['self']+'/tutorial-actions/'+action, json={})
        self.solve(again)
        self.assertEqual(self.client.put(again['links']['completion'], json={}).json()['awarded_xp'], 0)

    def test_rectangle_neighbors_do_not_wrap(self):
        """矩形最右格不会把下一行最左格当成相邻格。"""
        from backend.app.services.progression_service import mine_neighbors
        self.assertEqual(set(mine_neighbors(14,12,15)), {13,28,29})
        self.assertEqual(set(mine_neighbors(299,15,20)), {278,279,298})
