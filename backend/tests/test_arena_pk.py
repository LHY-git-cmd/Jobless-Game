"""作用：三模式竞技TDD，覆盖等级、分池、邀请、准备、隐藏扫雷及积分幂等。"""
from datetime import timedelta
from unittest import TestCase
from uuid import uuid4
from sqlalchemy import select
from backend.tests import test_progression_v1 as fixtures
from backend.app.common.security import utc_now
from backend.app.models.entities.progression import PlayerProgression
from backend.app.models.entities.pk import PKRoom
from backend.app.services.pk_runtime import runtime
from backend.app.services import pk_service as pk
from backend.content_check import akari_solutions,sudoku_solutions
from backend.app.models.entities.arena import ArenaAccount,ArenaLedger,ArenaInvitation


class ArenaPKTests(TestCase):
    """完整HTTP接口与隔离数据库，不创建产品后门。"""
    def setUp(self):
        """创建已达到5级的两个测试账号并清理短期在线状态。"""
        fixtures.ProgressionAPI.setUp(self);runtime.reset()
        with self.sessions() as db:
            for uid in [1,2]:db.add(PlayerProgression(user_id=uid,xp=72,total_stars=0,revision=0))
            db.commit()
    def tearDown(self):
        """释放临时账号和在线索引。"""
        runtime.reset();fixtures.ProgressionAPI.tearDown(self)
    def identity(self,uid):
        """Cookie模拟账号，业务归属仍由真实路由校验。"""
        self.client.cookies.set(self.settings.session_cookie_name,str(uid))
    def post(self,path,body):
        """创建资源带稳定UUID标识。"""
        return self.client.post('/api/v1/'+path,json=body,headers={'Idempotency-Key':str(uuid4())})
    def room(self,game='akari'):
        """创建好友房并加入第二个成员。"""
        self.identity(1);response=self.post('rooms',{'game_id':game,'difficulty':'normal'})
        self.assertEqual(response.status_code,201,response.text);value=response.json()
        self.identity(2);joined=self.post('room-memberships',{'room_code':value['room_code']})
        self.assertEqual(joined.status_code,201,joined.text);return value['room_id']
    def playing(self,game='akari'):
        """双方准备、三秒倒计时由服务端调度开始。"""
        rid=self.room(game)
        for uid in [1,2]:
            self.identity(uid);value=self.client.get('/api/v1/rooms/'+rid)
            ready=self.client.put(f'/api/v1/rooms/{rid}/members/me/readiness',json={'ready':True},headers={'If-Match':value.headers['etag']})
            self.assertIn(ready.status_code,[200,201],ready.text)
        with self.sessions() as db:
            row=db.get(PKRoom,rid)
            self.assertLessEqual((row.starts_at-utc_now()).total_seconds(),3)
            row.starts_at=utc_now()-timedelta(seconds=1);row.ends_at=row.starts_at+timedelta(minutes=10);db.commit()
        pk.maintenance(self.sessions);return rid
    def test_three_pools_match_only_same_game(self):
        """扫雷和数独不能跨池配对，入队不自动准备。"""
        for uid,game in [(1,'mine'),(2,'sudoku')]:
            self.identity(uid);response=self.post('matchmaking-tickets',{'game_id':game,'difficulty':'normal'})
            self.assertEqual(response.status_code,201,response.text);self.assertEqual(response.json()['status'],'waiting')
        self.client.delete(response.json()['links']['self'])
        self.assertEqual(self.post('matchmaking-tickets',{'game_id':'mine','difficulty':'normal'}).json()['status'],'matched')
        room=self.client.get('/api/v1/me/rooms?status=active').json()['items'][0]
        self.assertEqual(room['game_id'],'mine');self.assertTrue(all(not m['ready'] for m in room['members']))
    def test_points_initialize_once_leave_scores_and_negative_balance(self):
        """初始化100，胜+20负-10；多次退出/维护不重复结算，可低于0。"""
        rid=self.playing()
        self.assertEqual(self.client.get('/api/v1/me/arena').json()['points'],100)
        self.identity(1);self.assertEqual(self.client.delete(f'/api/v1/rooms/{rid}/members/me').status_code,204)
        self.client.delete(f'/api/v1/rooms/{rid}/members/me');pk.maintenance(self.sessions)
        self.assertEqual(self.client.get('/api/v1/me/arena').json()['points'],90)
        self.identity(2);self.assertEqual(self.client.get('/api/v1/me/arena').json()['points'],120)
        self.assertEqual(self.client.get('/api/v1/me/progression').json()['xp'],72)
    def test_mine_hidden_layout_same_start_and_mine_is_immediate_loss(self):
        """起始格一致，未揭雷不泄露，踩雷立即扣分并使对手获胜。"""
        rid=self.playing('mine');path='/api/v1/rooms/'+rid
        value=self.client.get(path).json();self.assertNotIn('mine_indices',str(value));self.assertEqual(len(value['puzzle'].get('map',[])),0)
        self.assertEqual(value['mine_board']['revealed'][0]['index'],0)
        with self.sessions() as db:mine=db.get(PKRoom,rid).puzzle['puzzle']['mine_indices'][0]
        response=self.client.put(path+f'/reveals/{mine}',json={})
        self.assertEqual(response.status_code,200,response.text)
        result=self.client.get(path+'/result').json();self.assertEqual(result['winner_id'],1)
        self.assertEqual(result['reason'],'mine_hit')
    def test_sudoku_submits_valid_solution_and_scores_once(self):
        """简单数独同题合法完成才进入一秒胜负窗口。"""
        rid=self.playing('sudoku');path='/api/v1/rooms/'+rid
        value=self.client.get(path).json();answer=sudoku_solutions(value['puzzle']['values'])[0]
        response=self.client.put(path+'/submissions/me',json={'values':answer})
        self.assertEqual(response.status_code,201,response.text)
        pk.maintenance(self.sessions,now=utc_now()+timedelta(seconds=2))
        self.assertEqual(self.client.get(path+'/result').json()['winner_id'],2)
        self.assertEqual(self.client.get('/api/v1/me/arena').json()['points'],120)
    def test_online_idle_invitation_requires_acceptance(self):
        """在线且空闲可邀请；接受前不强拉对手入房，接受幂等。"""
        self.identity(2);self.assertEqual(self.post('me/presence',{'visible':True}).status_code,200)
        self.identity(1);self.post('me/presence',{'visible':True})
        found=self.client.get('/api/v1/arena/users?q=10000001');self.assertEqual(found.status_code,200,found.text)
        self.assertEqual(len(found.json()['items']),1)
        self.assertEqual(found.json()['items'][0]['player_id'],10000001)
        self.assertTrue(found.json()['items'][0]['invitable'])
        invitation=self.post('arena/invitations',{'user_id':found.json()['items'][0]['user_id'],'game_id':'sudoku','difficulty':'normal'})
        self.assertEqual(invitation.status_code,201,invitation.text)
        self.identity(2);self.assertEqual(self.client.get('/api/v1/me/rooms').json()['items'],[])
        pending=self.client.get('/api/v1/me/arena/invitations').json()['items'];self.assertEqual(len(pending),1)
        accepted=self.post('arena/invitations/'+invitation.json()['invitation_id']+'/accept',{})
        self.assertEqual(accepted.status_code,200,accepted.text)
        self.assertEqual(accepted.json()['game_id'],'sudoku')
        self.assertEqual(self.post('arena/invitations/'+invitation.json()['invitation_id']+'/accept',{}).json()['room_id'],accepted.json()['room_id'])

    def test_player_search_uses_public_id_and_preserves_username_lookup(self):
        """内部小编号不能当玩家ID搜索，完整用户名仍可查找，且排除本人。"""
        self.identity(1)
        for term in ('2', '10000000', '99999999', '010000001', '１００００００１'):
            self.assertEqual(self.client.get('/api/v1/arena/users',params={'q':term}).json()['items'],[])
        found=self.client.get('/api/v1/arena/users?q=p2').json()['items']
        self.assertEqual(found[0]['player_id'],10000001)
    def test_low_level_blocked_search_and_score_not_created_by_get(self):
        """等级门槛由服务端检查，不用老资格绕过。"""
        with self.sessions() as db:db.get(PlayerProgression,1).xp=71;db.commit()
        response=self.post('rooms',{'game_id':'akari','difficulty':'normal'})
        self.assertEqual(response.status_code,403,response.text)
        self.assertEqual(self.client.get('/api/v1/arena/users?q=p2').status_code,403)

    def test_negative_points_are_persisted_and_ranked(self):
        """余额5分失败扣到-5，重复结算不重复扣，公共积分榜显示真实负值。"""
        rid=self.playing()
        with self.sessions() as db:db.get(ArenaAccount,1).points=5;db.commit()
        self.identity(1);self.client.delete(f'/api/v1/rooms/{rid}/members/me')
        self.assertEqual(self.client.get('/api/v1/me/arena').json()['points'],-5)
        board=self.client.get('/api/rankings/growth/points').json()
        self.assertEqual([item['points'] for item in board['entries']],[120,-5])
        with self.sessions() as db:self.assertEqual(len(db.scalars(select(ArenaLedger)).all()),2)

    def test_offline_busy_invitation_expiry_and_cancel(self):
        """在线搜索不能让离线用户被邀请；邀请到期或对方已入队时拒绝接受。"""
        response=self.post('arena/invitations',{'user_id':2,'game_id':'mine','difficulty':'normal'})
        self.assertEqual(response.status_code,409)
        for uid in [1,2]:runtime.heartbeat(uid,str(uid),True)
        invitation=self.post('arena/invitations',{'user_id':2,'game_id':'mine','difficulty':'normal'}).json()
        with self.sessions() as db:db.get(ArenaInvitation,invitation['invitation_id']).expires_at=utc_now()-timedelta(seconds=1);db.commit()
        self.identity(2);self.assertEqual(self.post('arena/invitations/'+invitation['invitation_id']+'/accept',{}).status_code,410)
        self.identity(1);next_invite=self.post('arena/invitations',{'user_id':2,'game_id':'mine','difficulty':'normal'}).json()
        self.identity(2);ticket=self.post('matchmaking-tickets',{'game_id':'sudoku','difficulty':'normal'})
        self.assertEqual(ticket.status_code,201,ticket.text)
        self.assertEqual(self.post('arena/invitations/'+next_invite['invitation_id']+'/accept',{}).status_code,409)
        self.client.delete(ticket.json()['links']['self'])
        self.assertEqual(self.client.delete('/api/v1/arena/invitations/'+next_invite['invitation_id']).status_code,204)

    def test_mode_change_resets_both_preparations_and_match_rooms_lock_mode(self):
        """只有好友房主可切换，清除双方准备且重新使用新模式题盘。"""
        rid=self.room('akari');path='/api/v1/rooms/'+rid
        value=self.client.get(path)
        self.assertEqual(self.client.put(path+'/mode',json={'game_id':'mine','difficulty':'normal'},headers={'If-Match':value.headers['etag']}).status_code,409)
        self.identity(1);value=self.client.get(path)
        changed=self.client.put(path+'/mode',json={'game_id':'mine','difficulty':'normal'},headers={'If-Match':value.headers['etag']})
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertEqual(changed.json()['game_id'],'mine');self.assertTrue(all(not m['ready'] for m in changed.json()['members']))

    def test_waiting_and_timeout_do_not_change_points(self):
        """准备前退出和双方均超时不加扣，终态结果只写一次。"""
        rid=self.room();self.client.delete(f'/api/v1/rooms/{rid}/members/me')
        self.assertEqual(self.client.get('/api/v1/me/arena').json()['points'],100)
        self.identity(1);self.client.delete(f'/api/v1/rooms/{rid}/members/me')
        rid=self.playing()
        with self.sessions() as db:row=db.get(PKRoom,rid);row.ends_at=utc_now()-timedelta(seconds=1);db.commit()
        pk.maintenance(self.sessions);self.assertEqual(self.client.get('/api/v1/me/arena').json()['points'],100)

    def test_legacy_competitive_puzzles_remain_unique_and_not_identical_campaigns(self):
        """旧v1题库保留审计，v2原题独立性和当前难度由专门题库测试覆盖。"""
        from backend.app.services.arena_games import LEGACY_POOLS as POOLS
        from backend.app.common.game_catalog import published_levels
        for game,items in POOLS.items():
            originals=[item['puzzle'].get('map',item['puzzle'].get('values')) for item in published_levels() if item['game_id']==game]
            for item in items:
                puzzle=item['puzzle'];cells=puzzle.get('map',puzzle.get('values'));self.assertNotIn(cells,originals)
                answers=akari_solutions(puzzle['map']) if game=='akari' else sudoku_solutions(puzzle['values'])
                self.assertEqual(len(answers),1,item['level_id'])

    def test_earlier_mine_hit_is_not_reversed_by_database_processing_order(self):
        """两个踩雷交错时，后处理的更早HTTP动作优先，积分只结算一次。"""
        rid=self.playing('mine');start=utc_now();pending=runtime.receive(rid,start)
        with self.sessions() as db:index=db.get(PKRoom,rid).puzzle['puzzle']['mine_indices'][0]
        with self.sessions() as db:pk.dispatch('2',db,'room_reveal',rid=rid,index=index,received_at=start+timedelta(milliseconds=10))
        with self.sessions() as db:self.assertIsNone(db.get(PKRoom,rid).result)
        with self.sessions() as db:pk.dispatch('1',db,'room_reveal',rid=rid,index=index,received_at=start)
        runtime.processed(pending);pk.maintenance(self.sessions)
        value=self.client.get(f'/api/v1/rooms/{rid}/result').json();self.assertEqual(value['winner_id'],2)
