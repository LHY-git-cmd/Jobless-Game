"""作用：TDD验证13关目录、教学动作、暂停、判题、补奖和旧资格兼容。"""
from datetime import timedelta
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4
from backend.tests import test_progression_v1 as fixture
from backend.app.services import progression_service as service
from backend.app.common.game_catalog import LEVELS
from backend.app.common.security import utc_now
from backend.app.models.entities.progression import GameAttempt
from backend.sudoku_content import solutions


class SudokuAPI(TestCase):
    """真实路由及事务使用隔离SQLite，生产迁移另行验收。"""
    setUp = fixture.ProgressionAPI.setUp
    tearDown = fixture.ProgressionAPI.tearDown

    def start(self, level='sudoku-v2-easy-01'):
        """显式创建正式数独，不传时间和奖励。"""
        service.limiter.clear()
        response=self.client.post('/api/v1/attempts',headers={'Idempotency-Key':str(uuid4())},json={
            'level_id':level,'level_version':1,'mode':'campaign'})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def answer(self, attempt):
        """仅测试机离线求解；产品页面及API不包含答案。"""
        return {'values':solutions(attempt['puzzle']['values'],attempt['puzzle']['rows'])[0]}

    def clock(self, attempt, paused):
        """按时钟修订号提交暂停意图。"""
        return self.client.put(attempt['links']['self']+'/clock',json={
            'paused':paused,'revision':attempt['timing']['revision'],'command_id':str(uuid4())})

    def test_catalog_boundaries_and_no_answers(self):
        """13关公开参数完整，所有档位自由选，目录不发题。"""
        items=self.client.get('/api/v1/levels?game_id=sudoku').json()['items']
        self.assertEqual(len(items),13)
        self.assertEqual([sum(v['difficulty']==d for v in items) for d in ('tutorial','easy','medium','hard','hell')],[1,3,3,3,3])
        self.assertNotIn('values',str(items)); self.assertNotIn('solution',str(items))
        from backend.app.services.game_rules import stars_for
        for difficulty,seconds in [('easy',300),('medium',600),('hard',1200),('hell',2100)]:
            level=next(v for v in items if v['difficulty']==difficulty)
            self.assertEqual([stars_for(level,t) for t in (seconds*1000,seconds*1000+1,seconds*2000,seconds*2000+1)],[3,2,2,1])
        self.assertIn('sudoku-beginner-001',LEVELS)

    def test_all_twelve_rewards_and_repeat(self):
        """全部普通题独立结算，重复三星0奖励，新简单第1题授永久资格。"""
        total=0
        for difficulty,xp in [('easy',6),('medium',9),('hard',12),('hell',15)]:
            for number in range(1,4):
                attempt=self.start(f'sudoku-v2-{difficulty}-{number:02}')
                result=self.client.put(attempt['links']['completion'],json=self.answer(attempt))
                self.assertEqual(result.status_code,201,result.text)
                self.assertEqual((result.json()['stars'],result.json()['awarded_xp']),(3,xp))
                self.assertEqual(self.client.put(attempt['links']['completion'],json=self.answer(attempt)).json(),result.json())
                total+=xp
        self.assertEqual(self.client.get('/api/v1/me/progression').json()['xp'],total)
        self.assertTrue(self.client.get('/api/v1/me/pk-eligibility').json()['requirements'][2]['completed'])
        repeated=self.start(); result=self.client.put(repeated['links']['completion'],json=self.answer(repeated)).json()
        self.assertEqual((result['awarded_stars'],result['awarded_xp']),(0,0))

    def test_pause_improvement_strict_payload_and_isolation(self):
        """长暂停不计时，暂停禁止提交；低星升高星补差，外人不能访问。"""
        attempt=self.start(); url=attempt['links']['completion']; answer=self.answer(attempt)
        bad=answer['values'][:]; bad[0]=bad[1]
        self.assertEqual(self.client.put(url,json={'values':bad}).status_code,422)
        self.assertEqual(self.client.put(url,json={'values':answer['values'][:16]}).status_code,422)
        self.assertEqual(self.client.put(url,json={**answer,'duration_ms':1}).status_code,422)
        self.assertEqual(self.client.put(url,json={'values':[True]*81}).status_code,422)
        with self.sessions() as db:
            db.get(GameAttempt,attempt['attempt_id']).started_at=utc_now()-timedelta(seconds=601); db.commit()
        low=self.client.put(url,json=answer).json(); self.assertEqual((low['stars'],low['awarded_xp']),(1,2))
        attempt=self.start(); start=utc_now()
        with self.sessions() as db:
            db.get(GameAttempt,attempt['attempt_id']).started_at=start; db.commit()
        with patch.object(service,'utc_now',return_value=start+timedelta(seconds=200)):
            paused=self.clock(attempt,True).json()
        self.assertEqual(self.client.put(attempt['links']['completion'],json=self.answer(attempt)).status_code,409)
        with patch.object(service,'utc_now',return_value=start+timedelta(seconds=2000)):
            resumed=self.clock(paused,False).json()
        # 控制开始时间与累计暂停，真实入口的接收时间仍由服务端提供。
        with self.sessions() as db:
            row=db.get(GameAttempt,attempt['attempt_id']); row.started_at=utc_now()-timedelta(seconds=2050); db.commit()
        result=self.client.put(attempt['links']['completion'],json=self.answer(attempt))
        self.assertEqual((result.json()['stars'],result.json()['awarded_xp'],result.json()['awarded_stars']),(3,4,2),result.text)
        frozen=result.json()['duration_ms']
        self.assertEqual(self.clock(resumed,True).json()['timing']['elapsed_ms'],frozen)
        self.client.cookies.set(self.settings.session_cookie_name,'2')
        self.assertEqual(self.client.get(attempt['links']['self']).status_code,404)
        self.assertEqual(self.clock(resumed,True).status_code,404)

    def test_tutorial_requires_verified_actions(self):
        """教学必须实际完成填数、擦除、笔记、列及宫定位，不能直接提交答案。"""
        attempt=self.start('sudoku-v2-tutorial'); base=attempt['links']['self']+'/sudoku-tutorial-actions/'
        self.assertEqual(self.client.put(attempt['links']['completion'],json=self.answer(attempt)).status_code,409)
        self.assertEqual(self.client.put(base+'note',json={'index':1,'value':2}).status_code,409)
        self.assertEqual(self.client.put(attempt['links']['self']+'/tutorial-actions/number',json={}).status_code,422)
        for action,index,value,step in [('row',1,2,1),('erase',1,0,2),('note',1,2,3),('column',6,1,4),('box',1,2,5)]:
            response=self.client.put(base+action,json={'index':index,'value':value})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['board']['tutorial_step'],step)
            repeat=self.client.put(base+action,json={'index':index,'value':value})
            self.assertEqual(repeat.json()['revision'],response.json()['revision'])
        saved=self.client.put(attempt['links']['completion'],json=self.answer(attempt))
        self.assertEqual((saved.json()['stars'],saved.json()['awarded_xp']),(1,2),saved.text)
        self.assertFalse(self.client.get('/api/v1/me/pk-eligibility').json()['requirements'][2]['completed'])
