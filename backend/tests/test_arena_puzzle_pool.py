"""作用：先验证每种20道独立竞技原题及双方各最近4局的持久、原题级去重。"""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from sqlalchemy import select
from backend.tests import test_arena_flow as fixtures
from backend.app.common.security import utc_now
from backend.app.models.entities.pk import PKRoom
from backend.app.models.entities import arena as entities
from backend.app.services import arena_games, arena_service, pk_service as pk
from backend.akari_content import solve as akari_solve
from backend.sudoku_content import canonical, grade, solve as sudoku_solve, solutions, verify_trace
from backend.content_check import akari_solutions, checksum

CONTENT=Path(__file__).resolve().parents[1]/'content'


def catalog():
    """只读取新冻结版本，缺少内容时测试明确失败。"""
    return json.loads((CONTENT/'arena-puzzles-v2.json').read_text(encoding='utf-8'))


def wall_identity(grid):
    """旋转和镜像相同的墙体拓扑视为同一原题，不能靠变换凑20题。"""
    wall=[''.join('.' if cell=='.' else '#' for cell in row) for row in grid]
    return min(tuple(arena_games.transformed_map(wall,turn)) for turn in range(8))


class ArenaPoolContentTests(TestCase):
    """离线独立求解与逻辑分级，审计不依赖产品自报答案。"""
    def test_twenty_distinct_originals_per_game_and_frozen_checksums(self):
        """每种20个稳定ID，题面与墙体规范化后仍独立。"""
        content=catalog()
        self.assertEqual(content['version'],2)
        self.assertEqual(content['history_limit'],4)
        for game,items in content['pools'].items():
            self.assertEqual(len(items),20,game)
            self.assertEqual(len({item['base_puzzle_id'] for item in items}),20)
            identities=[]
            for item in items:
                puzzle=item['puzzle']
                self.assertEqual((puzzle['rows'],puzzle['cols']),(10,10) if game=='akari' else (9,9))
                self.assertEqual(puzzle['checksum'],checksum({k:v for k,v in puzzle.items() if k!='checksum'}))
                identities.append(wall_identity(puzzle['map']) if game=='akari' else canonical(puzzle['values']))
            self.assertEqual(len(set(identities)),20,game)

    def test_every_original_is_unique_and_same_difficulty_as_baseline(self):
        """照明第10关层级/步数范围，数独简单单候选/隐藏单数及唯一解均通过。"""
        audit=json.loads((CONTENT/'arena-audit-v2.json').read_text(encoding='utf-8'))
        for game,items in catalog()['pools'].items():
            for item in items:
                with self.subTest(base=item['base_puzzle_id']):
                    puzzle=item['puzzle'];record=audit['puzzles'][item['base_puzzle_id']]
                    if game=='akari':
                        answers=akari_solutions(puzzle['map']);logical=akari_solve(puzzle['map'],1)
                        self.assertEqual(len(answers),1)
                        self.assertTrue(logical['solved']);self.assertEqual(logical['tier'],1)
                        self.assertTrue(29<=len(logical['trace'])<=49)
                        self.assertEqual(logical['bulbs'],answers[0]);self.assertEqual(logical,record['logic'])
                    else:
                        self.assertEqual(len(solutions(puzzle['values'])),1)
                        self.assertEqual(grade(puzzle['values']),'easy')
                        self.assertEqual(sum(bool(v) for v in puzzle['values']),25)
                        self.assertTrue(verify_trace(puzzle['values'],9,record['logic']['trace']))

    def test_selection_excludes_original_ids_and_variants_keep_identity(self):
        """随机数反复取同一位置也不能从排除集合选题，展示变换不生成新ID。"""
        for game in ('akari','sudoku'):
            items=catalog()['pools'][game];blocked={v['base_puzzle_id'] for v in items[:8]}
            for _ in range(12):
                puzzle=arena_games.make_puzzle(game,excluded=blocked)
                self.assertNotIn(puzzle['base_puzzle_id'],blocked)
                self.assertEqual(puzzle['pool_version'],2)
            only=items[0]['base_puzzle_id']
            excluded={v['base_puzzle_id'] for v in items[1:]}
            first=arena_games.make_puzzle(game,excluded=excluded)
            second=arena_games.make_puzzle(game,previous=first,excluded=excluded)
            self.assertEqual(first['base_puzzle_id'],only)
            self.assertEqual(second['base_puzzle_id'],only)
            self.assertNotEqual(first['puzzle'],second['puzzle'])
            self.assertRaises(ValueError,arena_games.make_puzzle,game,excluded={v['base_puzzle_id'] for v in items})

    def test_sudoku_originals_are_not_row_column_or_digit_relabelled_copies(self):
        """线索数量不变量各不相同，证明20题不是合法行列/宫重排和数字置换复制。"""
        signatures=[]
        for item in catalog()['pools']['sudoku']:
            values=item['puzzle']['values']
            rows=tuple(sorted(sum(bool(values[r*9+c]) for c in range(9)) for r in range(9)))
            cols=tuple(sorted(sum(bool(values[r*9+c]) for r in range(9)) for c in range(9)))
            boxes=tuple(sorted(sum(bool(values[(br+r)*9+bc+c]) for r in range(3) for c in range(3))
                               for br in range(0,9,3) for bc in range(0,9,3)))
            signatures.append((tuple(sorted((rows,cols))),boxes))
        self.assertEqual(len(set(signatures)),20)


class ArenaPoolHistoryTests(TestCase):
    """真实路由、生产autoflush=False会话及隔离数据库，不暴露测试后门。"""
    tearDown=fixtures.ArenaFlowTests.tearDown
    identity=fixtures.ArenaFlowTests.identity
    post=fixtures.ArenaFlowTests.post
    room=fixtures.ArenaFlowTests.room
    playing=fixtures.ArenaFlowTests.playing
    continuation=fixtures.ArenaFlowTests.continuation

    def setUp(self):
        """复用账号与业务夹具，并显式采用生产的手动flush约束。"""
        fixtures.ArenaFlowTests.setUp(self)
        self.sessions.configure(autoflush=False)

    def history(self,uid,game):
        """从独立新会话读取，不能被ORM缓存伪装成持久化成功。"""
        with self.sessions() as db:
            row=db.get(entities.ArenaPuzzleHistory,(uid,game))
            return deepcopy(row.recent) if row else []

    def seed(self,uid,game,ids):
        """建立最近局夹具，后续选题仍走正式API和状态机。"""
        with self.sessions() as db:
            row=db.get(entities.ArenaPuzzleHistory,(uid,game))
            recent=[{'room_id':'old-'+str(i),'base_puzzle_id':identity} for i,identity in enumerate(ids)]
            if row:row.recent=recent
            else:db.add(entities.ArenaPuzzleHistory(user_id=uid,game_id=game,recent=recent,revision=0))
            db.commit()

    def countdown(self,rid):
        """双方准备完成仍不记历史，倒计时阶段不向客户端返回题目或原题ID。"""
        for uid in (1,2):
            self.identity(uid);value=self.client.get('/api/v1/rooms/'+rid)
            response=self.client.put(f'/api/v1/rooms/{rid}/members/me/readiness',json={'ready':True},headers={'If-Match':value.headers['etag']})
            self.assertIn(response.status_code,(200,201),response.text)
            self.assertNotIn('puzzle',response.json());self.assertNotIn('base_puzzle_id',response.json())

    def start(self,rid):
        """只推进隔离数据库中的开局时间，不修改服务端实际游戏规则。"""
        with self.sessions() as db:
            row=db.get(PKRoom,rid);row.starts_at=utc_now()-timedelta(seconds=1);row.ends_at=row.starts_at+timedelta(minutes=10);db.commit()
        pk.maintenance(self.sessions)
        return self.client.get('/api/v1/rooms/'+rid).json()

    def close(self,rid):
        """双方明确离开，允许下一轮重新匹配，不直接清空占用表。"""
        for uid in (1,2):
            self.identity(uid);self.client.delete(f'/api/v1/rooms/{rid}/members/me')

    def test_cancelled_countdown_does_not_consume_recent_history(self):
        """创建、读取和取消倒计时都不算见过该原题。"""
        rid=self.room('akari');self.countdown(rid)
        self.assertEqual(self.history(1,'akari'),[]);self.assertEqual(self.history(2,'akari'),[])
        self.client.delete(f'/api/v1/rooms/{rid}/members/me')
        self.assertEqual(self.history(2,'akari'),[])

    def test_actual_start_records_both_players_once_and_preserves_frozen_puzzle(self):
        """转playing与两人历史同事务，重复维护或GET不换题、不重复记录。"""
        rid=self.room('sudoku');self.countdown(rid);value=self.start(rid)
        identity=value['base_puzzle_id']
        for uid in (1,2):
            self.assertEqual(self.history(uid,'sudoku'),[{'room_id':rid,'base_puzzle_id':identity}])
        pk.maintenance(self.sessions)
        self.assertEqual(self.client.get('/api/v1/rooms/'+rid).json()['puzzle'],value['puzzle'])
        self.assertEqual(len(self.history(1,'sudoku')),1)
        self.assertNotIn('solution',str(value));self.assertNotIn('trace',str(value))

    def test_final_ready_rechecks_union_of_both_histories(self):
        """房主创建后对手才加入，也必须避开双方各4局，而非只看创建者。"""
        for game in ('akari','sudoku'):
            ids=[v['base_puzzle_id'] for v in catalog()['pools'][game]]
            rid=self.room(game)
            self.seed(1,game,ids[:4]);self.seed(2,game,ids[4:8])
            self.countdown(rid);value=self.start(rid)
            self.assertNotIn(value['base_puzzle_id'],ids[:8])
            for uid in (1,2):
                history=self.history(uid,game)
                self.assertEqual(len(history),4);self.assertEqual(history[-1]['base_puzzle_id'],value['base_puzzle_id'])
            self.close(rid)

    def test_repeated_new_rooms_rematch_and_restart_keep_last_four(self):
        """新建房间/再战换题均按账号记录，重启不会丢失，记录长度不无限增长。"""
        previous=[]
        for _ in range(6):
            rid=self.playing('akari')
            value=self.client.get('/api/v1/rooms/'+rid).json();identity=value['base_puzzle_id']
            self.assertNotIn(identity,previous[-4:]);previous.append(identity)
            self.close(rid)
        self.assertEqual([v['base_puzzle_id'] for v in self.history(1,'akari')],previous[-4:])
        pk.maintenance(self.sessions,restart=True)
        self.assertEqual([v['base_puzzle_id'] for v in self.history(2,'akari')],previous[-4:])
        self.assertEqual(self.history(1,'sudoku'),[])

    def test_start_failure_rolls_back_both_history_and_room_status(self):
        """第二个成员记录失败时，第一人的记录和开局状态也回滚。"""
        rid=self.room('akari');self.countdown(rid)
        with self.sessions() as db:
            row=db.get(PKRoom,rid);row.starts_at=utc_now()-timedelta(seconds=1);row.ends_at=utc_now()+timedelta(minutes=10);db.commit()
        original=arena_service.record_puzzle_start
        def broken(db,room,uids):
            """模拟持久写入之后、事务提交之前的故障。"""
            original(db,room,uids)
            raise RuntimeError('isolated rollback')
        with patch.object(arena_service,'record_puzzle_start',side_effect=broken):
            self.assertRaises(RuntimeError,pk.maintenance,self.sessions)
        with self.sessions() as db:self.assertEqual(db.get(PKRoom,rid).status,'countdown')
        self.assertEqual(self.history(1,'akari'),[]);self.assertEqual(self.history(2,'akari'),[])

    def test_rematch_filters_original_id_and_old_snapshot_stays_immutable(self):
        """再战按原题去重，不借旋转/换数字重复上一局；旧局保持原题面和结果。"""
        for game in ('akari','sudoku'):
            rid=self.playing(game)
            old=self.client.get('/api/v1/rooms/'+rid).json()
            pk.maintenance(self.sessions,now=utc_now()+timedelta(minutes=11))
            result=self.client.get('/api/v1/rooms/'+rid+'/result').json()
            value=self.continuation(rid,1,True)
            self.assertEqual(value.status_code,200,value.text)
            value=self.continuation(rid,2,True)
            next_id=value.json()['room_id'];new=self.start(next_id)
            self.assertNotEqual(new['base_puzzle_id'],old['base_puzzle_id'])
            self.assertEqual(self.client.get('/api/v1/rooms/'+rid).json()['puzzle'],old['puzzle'])
            self.assertEqual(self.client.get('/api/v1/rooms/'+rid+'/result').json(),result)
            self.close(next_id)

    def test_different_opponent_uses_their_history_without_touching_former_opponent(self):
        """账号3加入账号1的新房时，近期去重读取1和3的历史，账号2保持原样。"""
        from backend.app.models.entities import User
        from backend.app.models.entities.progression import PlayerProgression
        ids=[v['base_puzzle_id'] for v in catalog()['pools']['sudoku']]
        with self.sessions() as db:
            db.add(User(id=3,username='p3',username_key='p3',password_hash='test',created_at=utc_now()));db.flush()
            db.add(PlayerProgression(user_id=3,xp=72,total_stars=0,revision=0));db.commit()
        self.seed(1,'sudoku',ids[:4]);self.seed(3,'sudoku',ids[4:8]);self.seed(2,'sudoku',ids[8:12])
        former=self.history(2,'sudoku')
        with pk.runtime.lock,self.sessions() as db:
            room=pk.new_room(db,[1,3],utc_now(),'sudoku');rid=room.room_id;pk.committed(db)
        for uid in (1,3):
            with pk.runtime.lock,self.sessions() as db:
                room=pk.get_room(db,uid,rid)
                pk.readiness(db,uid,rid,{'ready':True},room.headers['ETag']);pk.committed(db)
        value=self.start(rid)
        self.assertNotIn(value['base_puzzle_id'],ids[:8])
        self.assertEqual(self.history(2,'sudoku'),former)
        self.assertEqual(self.history(3,'sudoku')[-1]['base_puzzle_id'],value['base_puzzle_id'])
