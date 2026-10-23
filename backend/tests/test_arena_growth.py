"""作用：先验证72经验解锁、首次三星当局翻倍及历史奖励不补发。"""
from datetime import timedelta
from unittest import TestCase
from uuid import uuid4
from backend.tests import test_progression_v1 as fixture
from backend.app.common.game_catalog import LEVELS,LEVEL_VERSIONS
from backend.app.common.security import utc_now
from backend.app.models.entities.progression import GameAttempt,PlayerProgression
from backend.app.services import progression_service as service
from backend.content_check import akari_solutions


class ArenaGrowthTests(TestCase):
    """真实路由和临时SQLite；时间只修改本例隔离数据库。"""
    setUp=fixture.ProgressionAPI.setUp
    tearDown=fixture.ProgressionAPI.tearDown

    def finish(self,stars,version=None):
        """服务端绑定版本，按实际时限产生一、二或三星。"""
        service.limiter.clear();level=LEVELS['akari-v2-001']
        version=version or level['level_version'];definition=LEVEL_VERSIONS[(level['level_id'],version)]
        attempt=self.client.post('/api/v1/attempts',headers={'Idempotency-Key':str(uuid4())},json={
            'level_id':level['level_id'],'level_version':version,'mode':'campaign'}).json()
        duration=1000 if stars==3 else definition['t3_ms']+5000 if stars==2 else definition['t2_ms']+5000
        with self.sessions() as db:
            db.get(GameAttempt,attempt['attempt_id']).started_at=utc_now()-timedelta(milliseconds=duration);db.commit()
        payload={'bulbs':akari_solutions(attempt['puzzle']['map'])[0]}
        response=self.client.put(attempt['links']['completion'],json=payload)
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(self.client.put(attempt['links']['completion'],json=payload).json(),response.json())
        return response.json()

    def test_monotonic_levels_and_server_gate(self):
        """全部等级边界一致；71经验不解锁，72解锁，90满级。"""
        for xp,level in [(0,1),(17,1),(18,2),(35,2),(36,3),(53,3),(54,4),(71,4),(72,5),(89,5),(90,6),(999,6)]:
            self.assertEqual(service.account_level(xp),level)
        for xp in [71,72]:
            with self.sessions() as db:
                row=db.get(PlayerProgression,1)
                if row:row.xp=xp
                else:db.add(PlayerProgression(user_id=1,xp=xp,total_stars=0,revision=0))
                db.commit()
            value=self.client.get('/api/v1/me/pk-eligibility').json()
            self.assertEqual(value['eligible'],xp>=72)
            self.assertEqual(value['minimum_level'],5)
            self.assertEqual(value['requirements'],[])

    def test_direct_three_stars_doubles_actual_award_once(self):
        """直接三星新增6+6，重复三星不发，不修改闯关星数。"""
        first=self.finish(3)
        self.assertEqual((first['awarded_xp'],first['base_awarded_xp'],first['first_three_star_bonus']),(12,6,6))
        self.assertEqual(first['awarded_stars'],3)
        self.assertEqual(self.finish(3)['awarded_xp'],0)

    def test_two_then_three_only_doubles_current_increment(self):
        """先二星得4，再首次三星得4，累计8；不能按整关累计翻倍。"""
        self.assertEqual(self.finish(2)['awarded_xp'],4)
        last=self.finish(3)
        self.assertEqual((last['awarded_xp'],last['base_awarded_xp'],last['first_three_star_bonus']),(4,2,2))
        self.assertEqual(self.client.get('/api/v1/me/progression').json()['xp'],8)

    def test_existing_three_stars_not_backfilled(self):
        """旧版本三星不追补，后续新版本也不重复获得首次三星奖励。"""
        old=self.finish(3,version=2)
        self.assertEqual(old['awarded_xp'],6)
        latest=self.finish(3)
        self.assertEqual(latest['awarded_xp'],0)

    def test_one_then_three_doubles_four_increment(self):
        """一星后首次三星应新增8，累计10。"""
        self.assertEqual(self.finish(1)['awarded_xp'],2)
        self.assertEqual(self.finish(3)['awarded_xp'],8)

    def test_latest_sudoku_and_mine_also_double_first_three(self):
        """三款普通游戏使用同一凭据规则，不仅照明有双倍；重复结算都幂等。"""
        from backend.content_check import sudoku_solutions
        for key in ['sudoku-v2-easy-01','mine-v2-easy-10']:
            service.limiter.clear();level=LEVELS[key]
            attempt=self.client.post('/api/v1/attempts',headers={'Idempotency-Key':str(uuid4())},json={
                'level_id':key,'level_version':level['level_version'],'mode':'campaign'}).json()
            if level['game_id']=='mine':
                with self.sessions() as db:mines=set(db.get(GameAttempt,attempt['attempt_id']).board['mine_indices'])
                for index in sorted(set(range(100))-mines):
                    response=self.client.put(attempt['links']['self']+f'/reveals/{index}',json={})
                    self.assertIn(response.status_code,[200,201],response.text)
                payload={}
            else:payload={'values':sudoku_solutions(attempt['puzzle']['values'])[0]}
            result=self.client.put(attempt['links']['completion'],json=payload)
            self.assertEqual(result.status_code,201,result.text)
            self.assertEqual((result.json()['awarded_xp'],result.json()['first_three_star_bonus']),(12,6))
            self.assertEqual(self.client.put(attempt['links']['completion'],json=payload).json(),result.json())
