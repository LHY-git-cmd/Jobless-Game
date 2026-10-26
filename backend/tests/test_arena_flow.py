"""作用：竞技棋盘同源、保留席位、续局确认和历史结果的HTTP回归测试。"""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase
from backend.tests import test_arena_pk as arena_fixtures
from backend.app.common.game_catalog import LEVELS
from backend.app.common.security import utc_now
from backend.app.models.entities.pk import PKRoom, PlayerPKOccupancy
from backend.app.models.entities.arena import ArenaLedger
from backend.app.services import pk_service as pk, arena_games
from backend.content_check import akari_solutions, sudoku_solutions
from sqlalchemy import select


class ArenaFlowTests(TestCase):
    """复用隔离账号夹具，不继承并重复执行旧竞技测试。"""
    setUp = arena_fixtures.ArenaPKTests.setUp
    tearDown = arena_fixtures.ArenaPKTests.tearDown
    identity = arena_fixtures.ArenaPKTests.identity
    post = arena_fixtures.ArenaPKTests.post
    room = arena_fixtures.ArenaPKTests.room
    playing = arena_fixtures.ArenaPKTests.playing

    def ended(self, game='mine'):
        """踩雷形成双方仍在场的终态，保留真实积分结算路径。"""
        rid = self.playing(game)
        if game == 'mine':
            with self.sessions() as db:
                mine = db.get(PKRoom, rid).puzzle['puzzle']['mine_indices'][0]
            self.client.put(f'/api/v1/rooms/{rid}/reveals/{mine}', json={})
        else:
            pk.maintenance(self.sessions, now=utc_now()+timedelta(minutes=11))
        return rid

    def continuation(self, rid, uid, ready=False):
        """返回房间不准备，再战只确认本人的下一局。"""
        self.identity(uid)
        return self.client.post(f'/api/v1/rooms/{rid}/continuation', json={'ready': ready})

    def test_puzzles_use_published_campaign_configuration(self):
        """三种竞技题均带正式配置来源，照明与简单数独变换后仍有唯一解。"""
        for game, level_id in [('mine','mine-v2-easy-10'), ('akari','akari-v2-010'), ('sudoku','sudoku-v2-easy-01')]:
            value = arena_games.make_puzzle(game)
            source = LEVELS[value['level_id']]
            self.assertEqual(source['game_id'], game)
            self.assertEqual(value['level_version'], source['level_version'])
            self.assertEqual(value['puzzle']['rows'], source['puzzle']['rows'])
            self.assertEqual(value['puzzle']['cols'], source['puzzle']['cols'])
            if game == 'mine':
                self.assertEqual(value['level_id'], level_id)
                self.assertEqual(value['puzzle']['mine_count'], source['mine_count'])
            elif game == 'akari':
                self.assertEqual(value['level_id'], level_id)
                self.assertEqual(len(akari_solutions(value['puzzle']['map'])), 1)
            else:
                self.assertEqual(source['difficulty'], 'easy')
                self.assertEqual(len(sudoku_solutions(value['puzzle']['values'])), 1)

    def test_rematch_changes_initial_puzzle_even_when_random_choice_repeats(self):
        """换题有确定性兜底，随机重复也不沿用上一局棋盘。"""
        from unittest.mock import patch
        for game in ('mine','akari','sudoku'):
            first = arena_games.make_puzzle(game)
            with patch.object(arena_games.secrets, 'randbelow', return_value=0):
                second = arena_games.make_puzzle(game, previous=first)
            self.assertNotEqual(first['puzzle'], second['puzzle'])

    def test_return_preserves_both_members_and_previous_result(self):
        """返回同一双人房，旧结果不可变且积分流水只有原来的两条。"""
        rid = self.ended()
        old = self.client.get(f'/api/v1/rooms/{rid}').json()['result']
        value = self.continuation(rid, 1)
        self.assertEqual(value.status_code, 200, value.text)
        next_room = value.json()
        self.assertNotEqual(next_room['room_id'], rid)
        self.assertEqual(next_room['status'], 'waiting')
        self.assertEqual(len(next_room['members']), 2)
        self.assertTrue(all(not m['ready'] for m in next_room['members']))
        self.assertEqual(self.client.get(f'/api/v1/rooms/{rid}/result').json(), old)
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(ArenaLedger)).all()), 2)
            for uid in (1,2):
                self.assertEqual(db.get(PlayerPKOccupancy, uid).room_id, next_room['room_id'])

    def test_rematch_requires_both_confirmations_and_retries_are_idempotent(self):
        """单方再战不启动；重复和双方确认共用同一新局与一次倒计时。"""
        rid = self.ended()
        first = self.continuation(rid, 1, True)
        self.assertEqual(first.status_code, 200, first.text)
        first = first.json()
        self.assertEqual(first['status'], 'waiting')
        again = self.continuation(rid, 1, True).json()
        self.assertEqual(again['room_id'], first['room_id'])
        second = self.continuation(rid, 2, True).json()
        self.assertEqual(second['room_id'], first['room_id'])
        self.assertEqual(second['status'], 'countdown')
        self.assertEqual(self.continuation(rid, 2, True).json()['starts_at'], second['starts_at'])
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(PKRoom)).all()), 2)

    def test_return_does_not_revoke_existing_rematch_confirmation(self):
        """重试返回请求不能把已经准备的本人反向取消。"""
        rid = self.ended()
        self.continuation(rid, 1, True)
        returned = self.continuation(rid, 1).json()
        self.assertTrue(next(m for m in returned['members'] if m['is_me'])['ready'])

    def test_result_keeps_opponent_occupied_until_leave_or_expiry(self):
        """结算后仍在房间，不能同时加入匹配队列；明确离开才释放。"""
        rid = self.ended()
        response = self.post('matchmaking-tickets', {'game_id':'mine','difficulty':'normal'})
        self.assertEqual(response.status_code, 409, response.text)
        self.client.delete(f'/api/v1/rooms/{rid}/members/me')
        response = self.post('matchmaking-tickets', {'game_id':'mine','difficulty':'normal'})
        self.assertEqual(response.status_code, 201, response.text)

    def test_old_page_leave_releases_its_successor_seat(self):
        """对方已返回时，本人在旧结算页退出也会退出当前续局。"""
        rid = self.ended()
        next_id = self.continuation(rid, 1).json()['room_id']
        self.identity(2)
        self.client.delete(f'/api/v1/rooms/{rid}/members/me')
        with self.sessions() as db:
            self.assertIsNone(db.get(PlayerPKOccupancy,2).room_id)
        self.identity(1)
        self.assertEqual(len(self.client.get(f'/api/v1/rooms/{next_id}').json()['members']), 1)

    def test_holding_expiry_releases_seats_without_changing_result(self):
        """结束页不能无限占房；到期只释放席位，不改写历史积分结果。"""
        rid = self.ended()
        old = deepcopy(self.client.get(f'/api/v1/rooms/{rid}/result').json())
        with self.sessions() as db:
            db.get(PKRoom,rid).lobby_expires_at = utc_now()-timedelta(seconds=1)
            db.commit()
        pk.maintenance(self.sessions)
        with self.sessions() as db:
            self.assertIsNone(db.get(PlayerPKOccupancy,2).room_id)
        self.assertEqual(self.client.get(f'/api/v1/rooms/{rid}/result').json(), old)
        self.assertEqual(self.continuation(rid,2).status_code,409)

    def test_timeout_is_draw_and_shows_timeout_reason(self):
        """十分钟双方未完成明确结算为平局，且可继续保留双方。"""
        rid = self.ended('sudoku')
        result = self.client.get(f'/api/v1/rooms/{rid}/result').json()
        self.assertEqual(result['outcome'], 'draw')
        self.assertEqual(result['reason'], 'match_timeout')
        self.assertEqual(result['duration_ms'],600000)
        self.assertTrue(all(score['delta']==0 for score in result['scores']))
        self.assertEqual(self.continuation(rid,1).status_code,200)

    def test_continuation_rejects_unfinished_or_departed_player(self):
        """未结束不能换局，已离开不能通过旧结果重新占用对手。"""
        rid = self.playing()
        self.assertEqual(self.continuation(rid,1,True).status_code,409)
        self.client.delete(f'/api/v1/rooms/{rid}/members/me')
        self.assertEqual(self.continuation(rid,1,True).status_code,404)

    def test_finished_room_releases_disconnected_seats_after_grace(self):
        """结算后关闭页面也按30秒宽限回收，避免离线账号长期被占用。"""
        rid = self.ended()
        now = utc_now()
        pk.maintenance(self.sessions,now=now)
        pk.maintenance(self.sessions,now=now+timedelta(seconds=31))
        with self.sessions() as db:
            self.assertIsNone(db.get(PlayerPKOccupancy,1).room_id)
            self.assertIsNone(db.get(PlayerPKOccupancy,2).room_id)

    def test_simultaneous_rematch_creates_one_successor(self):
        """两个并行写请求通过统一业务锁，只创建一局并完成双方准备。"""
        from concurrent.futures import ThreadPoolExecutor
        rid = self.ended()
        def confirm(uid):
            """各线程独立数据库会话与身份，不共享浏览器Cookie。"""
            with self.sessions() as db:
                return pk.dispatch(str(uid),db,'room_continue',rid=rid,data={'ready':True}).data
        with ThreadPoolExecutor(max_workers=2) as executor:
            values=list(executor.map(confirm,[1,2]))
        self.assertEqual(values[0]['room_id'],values[1]['room_id'])
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(PKRoom)).all()),2)
            self.assertEqual(db.get(PKRoom,values[0]['room_id']).status,'countdown')
