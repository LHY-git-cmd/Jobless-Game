"""单进程双人竞速及有界匹配事务，所有状态转换经写请求或唯一调度器。"""

from copy import deepcopy
from datetime import timedelta
import secrets
from uuid import uuid4
from ..common.game_catalog import PK_PUZZLES, POLICY
from ..common.config import get_settings
from ..common.security import utc_now
from ..models.entities import User
from ..models.entities.pk import PKRoom, PKParticipant, PKSubmission, PlayerPKOccupancy
from ..models.entities.matchmaking import MatchmakingTicket
from ..repositories import progression_repository as repo
from . import auth_service
from . import progression_service as progression
from .game_rules import validate_akari,validate_sudoku
from . import arena_service as arena,arena_games
from .pk_runtime import runtime

ACTIVE = ('waiting', 'countdown', 'playing')


def members(db, room_id, present=False, lock=True):
    """房间最多两名当前成员；历史退出成员仍可读取自身结果。"""
    conditions = [PKParticipant.room_id == room_id]
    if present:
        conditions.append(PKParticipant.left_at.is_(None))
    return repo.rows(db, PKParticipant, *conditions, lock=lock, limit=50)


def notify_room(db, room):
    """仅登记通知，提交成功后才发送，失败不会泄漏未提交状态。"""
    for member in members(db, room.room_id):
        db.info.setdefault('pk_events', {})[(member.user_id, '/api/v1/rooms/' + room.room_id)] = room.revision


def notify_ticket(db, ticket):
    """票据通知不包含对手或题目，客户端GET本人快照。"""
    db.info.setdefault('pk_events', {})[(ticket.user_id, '/api/v1/matchmaking-tickets/' + ticket.ticket_id)] = 0


def touch(db, room):
    """关键状态改变统一递增房间修订号。"""
    room.revision += 1
    db.flush()
    notify_room(db, room)


def active_rooms(db):
    """使用状态索引，仅取容量边界加一，不扫描历史房间。"""
    # 两个索引各取有界集合，结算后保留席位的房间也计入容量。
    live = repo.rows(db, PKRoom, PKRoom.status.in_(ACTIVE), limit=5)
    held = repo.rows(db, PKRoom, PKRoom.lobby_expires_at.is_not(None), limit=5)
    return list({room.room_id:room for room in [*live,*held]}.values())


def waiting_tickets(db):
    """FIFO有界池，不为每个玩家启动数据库轮询。"""
    return repo.rows(db, MatchmakingTicket, MatchmakingTicket.status == 'waiting', limit=8,
                     order=(MatchmakingTicket.created_at, MatchmakingTicket.ticket_id))


def occupancy(db, uid):
    """新增占用在用户锁内建立，主键保证单账号唯一身份。"""
    row = repo.get(db, PlayerPKOccupancy, uid)
    if row is None:
        row = PlayerPKOccupancy(user_id=uid, revision=0)
        db.add(row)
        db.flush()
    return row


def require_free(db, uid):
    """三个入口共用房间/票据互斥约束，重试识别先于此检查。"""
    row = occupancy(db, uid)
    if row.room_id or row.ticket_id:
        progression.fail(409, 'pk_occupied', '你已在房间或匹配队列中。', links={
            'room': '/api/v1/rooms/' + row.room_id if row.room_id else None,
            'ticket': '/api/v1/matchmaking-tickets/' + row.ticket_id if row.ticket_id else None})
    return row


def room_resource(db, room, uid, status=200):
    """只有playing及finished发题；任何快照都不包含对手终盘。"""
    current_members = members(db, room.room_id, True, False)
    submitted = {s.user_id for s in repo.rows(db, PKSubmission, PKSubmission.room_id == room.room_id, lock=False, limit=2)}
    base = '/api/v1/rooms/' + room.room_id
    data = {'room_id': room.room_id, 'room_code': room.room_code, 'game_id': room.game_id, 'difficulty': room.difficulty,
            'host_id':room.host_id,'source':room.source,
            'next_room_id':room.next_room_id, 'lobby_expires_at':progression.iso(room.lobby_expires_at) if room.lobby_expires_at else None,
            'status': room.status, 'revision': room.revision, 'reason': room.reason,
            'created_at': progression.iso(room.created_at), 'expires_at': progression.iso(room.expires_at),
            'starts_at': progression.iso(room.starts_at) if room.starts_at else None,
            'ends_at': progression.iso(room.ends_at) if room.ends_at else None, 'server_now': progression.iso(utc_now()),
            'members': [{'user_id': member.user_id, 'username': db.get(User, member.user_id).username,'avatar_id':db.get(User,member.user_id).avatar_id,
                         'is_me': member.user_id == uid, 'ready': member.ready, 'online': runtime.online(member.user_id),
                         'completed': member.user_id in submitted} for member in current_members],
            'links': {'self': base, 'result': base + '/result', 'readiness': base + '/members/me/readiness',
                      'submission': base + '/submissions/me', 'membership': base + '/members/me', 'continuation':base+'/continuation'}}
    if room.status in ('playing', 'finished'):
        data['puzzle'] = deepcopy(room.puzzle['puzzle'])
        if room.game_id=='mine':
            data['puzzle'].pop('mine_indices',None)
            member=next((m for m in current_members if m.user_id==uid),None)
            data['mine_board']=arena_games.public_board(member.board or {},room.puzzle['puzzle']) if member else {}
        data['level_version'] = room.puzzle['level_version']
        data['level_id'] = room.puzzle.get('level_id')
    if room.result:
        data['result'] = room.result
    headers = {'ETag': progression.etag(room.revision)}
    if status == 201:
        headers['Location'] = base
    return progression.Resource(data, status, headers)


def owned_room(db, uid, rid, require_present=False):
    """房间码不提供身份；只有成员可读，退出成员不能再提交。"""
    room = repo.get(db, PKRoom, rid)
    member = repo.get(db, PKParticipant, (rid, uid))
    if not room or not member or (require_present and member.left_at is not None):
        progression.fail(404, 'room_not_found', '房间不存在或你不是当前成员。')
    return room, member


def new_room(db, uids, now, game='akari',source='friend',previous=None):
    """唯一业务锁内检查容量和随机房间码碰撞。"""
    if len(active_rooms(db)) >= get_settings().pk_room_limit:
        progression.fail(503, 'room_capacity', '当前房间已满，请稍后再试。', headers={'Retry-After': '5'})
    for _ in range(10):
        code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
        if not repo.rows(db, PKRoom, PKRoom.room_code == code, limit=1):
            break
    else:
        progression.fail(503, 'room_capacity', '暂时无法创建房间。', headers={'Retry-After': '3'})
    room = PKRoom(room_id=str(uuid4()), room_code=code, game_id=game, difficulty='normal', status='waiting', revision=0,
                  host_id=uids[0],source=source,created_at=now, expires_at=now + timedelta(seconds=POLICY['room_wait_seconds']), puzzle=arena_games.make_puzzle(game,previous))
    db.add(room)
    db.flush()
    for uid in sorted(uids):
        arena.account(db,uid,True)
        row = occupancy(db, uid)
        row.room_id, row.ticket_id, row.revision = room.room_id, None, row.revision + 1
        db.add(PKParticipant(room_id=room.room_id, user_id=uid, ready=False, readiness_created=False, joined_at=now,
               board=arena_games.initial_board(room.puzzle['puzzle']) if game=='mine' else {}))
    db.flush()
    touch(db, room)
    return room


def create_room(db, uid, data, key, **_):
    """同键重放在已有占用检查之前，资格仍由正式成果决定。"""
    previous, key = progression.idempotent(db, uid, 'rooms', key, data)
    if previous:
        return previous
    progression.require_pk(db, uid)
    progression.limiter.check((uid, 'pk_starts'), 10)
    require_free(db, uid)
    room = new_room(db, [uid], utc_now(),data['game_id'])
    return progression.remember(db, uid, 'rooms', key, data, room_resource(db, room, uid, 201), room.room_id, 1)


def join_room(db, uid, data, key, **_):
    """码猜测限流，成员关系与占用在一个事务内建立。"""
    previous, key = progression.idempotent(db, uid, 'room-memberships', key, data)
    if previous:
        return previous
    progression.require_pk(db, uid)
    progression.limiter.check((uid, 'room_join'), 10)
    row = require_free(db, uid)
    found = repo.rows(db, PKRoom, PKRoom.room_code == data['room_code'].strip().upper(), limit=1)
    if not found:
        progression.fail(404, 'room_not_found', '房间码不存在。')
    room = found[0]
    if room.expires_at <= utc_now():
        progression.fail(410, 'room_expired', '房间已过期。')
    if room.status != 'waiting' or len(members(db, room.room_id, True)) >= 2:
        progression.fail(409, 'room_unavailable', '房间已满或已经开始。')
    member = repo.get(db, PKParticipant, (room.room_id, uid))
    if member is None:
        member = PKParticipant(room_id=room.room_id, user_id=uid, ready=False, readiness_created=False, joined_at=utc_now(),
                    board=arena_games.initial_board(room.puzzle['puzzle']) if room.game_id=='mine' else {})
        db.add(member)
    else:
        member.left_at, member.ready, member.disconnected_at = None, False, None
    row.room_id, row.revision = room.room_id, row.revision + 1
    arena.account(db,uid,True)
    touch(db, room)
    resource = room_resource(db, room, uid, 201)
    resource.headers['Location'] = '/api/v1/rooms/' + room.room_id + '/members/me'
    return progression.remember(db, uid, 'room-memberships', key, data, resource, room.room_id, 1)


def get_room(db, uid, rid, **_):
    """GET纯读取，不借刷新推进倒计时、匹配或胜负。"""
    room, member = owned_room(db, uid, rid)
    if member.left_at is not None and room.status in ACTIVE:
        progression.fail(404, 'room_not_found', '你已离开本房间。')
    return room_resource(db, room, uid)


def readiness(db, uid, rid, data, match, **_):
    """双方准备后冻结题，安排统一开始时间；此时仍不能读取地图。"""
    room, member = owned_room(db, uid, rid, True)
    progression.require_pk(db,uid)
    progression.precondition(match, room.revision)
    if room.status != 'waiting' or room.expires_at <= utc_now():
        progression.fail(409, 'room_state_conflict', '房间当前不能修改准备状态。')
    created = not member.readiness_created
    member.ready, member.readiness_created = data['ready'], True
    db.flush()
    present = members(db, rid, True)
    if len(present) == 2 and all(p.ready for p in present):
        room.status = 'countdown'
        room.starts_at = utc_now() + timedelta(seconds=POLICY['countdown_seconds'])
        room.ends_at = room.starts_at + timedelta(seconds=POLICY['match_seconds'])
    touch(db, room)
    result = room_resource(db, room, uid, 201 if created else 200)
    if created:
        result.headers['Location'] = f'/api/v1/rooms/{rid}/members/me/readiness'
    return result


def release_room(db, room):
    """结算同事务释放占用，不会清除用户随后建立的其他资源。"""
    for member in members(db, room.room_id):
        row = repo.get(db, PlayerPKOccupancy, member.user_id)
        if row and row.room_id == room.room_id:
            row.room_id, row.ticket_id, row.revision = None, None, row.revision + 1


def finish(db, room, now, outcome, reason, winner=None):
    """对局结果不调用成长服务，不授星、经验或主题权益。"""
    if room.result:return
    # 调度可能稍晚执行，超时局的有效比赛用时仍固定截止于服务器ends_at。
    if reason=='match_timeout' and room.ends_at:
        now=room.ends_at
    scores=arena.settle(db,room,members(db,room.room_id),winner,outcome,now)
    room.status = 'finished' if outcome in ('win', 'draw') else 'cancelled'
    room.reason, room.finished_at = reason, now
    room.result = {'room_id': room.room_id, 'outcome': outcome, 'winner_id': winner, 'reason': reason,
                   'finished_at': progression.iso(now), 'awarded_xp': 0, 'awarded_stars': 0}
    room.result={**room.result,'scores':scores,'duration_ms':max(0,int((now-room.starts_at).total_seconds()*1000)) if room.starts_at else 0}
    present = members(db,room.room_id,True)
    if present and reason in ('valid_completion','mine_hit','match_timeout','player_left'):
        # 结果积分已经冻结，成员短期保留席位供返回或确认再战。
        room.lobby_expires_at = now + timedelta(seconds=POLICY['room_wait_seconds'])
        for member in present:
            member.ready = False
    else:
        release_room(db, room)
    touch(db, room)


def voluntary_loss(db,room,uid,received_at,reason):
    """按HTTP接收先后记录即时失败；更早任务未处理时仅短暂等待其结束。"""
    prior=room.puzzle.get('pending_loss')
    event={'user_id':uid,'at':progression.iso(received_at),'reason':reason}
    if prior and prior['at']<event['at']:event=prior
    room.puzzle={**room.puzzle,'pending_loss':event}
    from datetime import datetime
    at=datetime.fromisoformat(event['at'].removesuffix('Z'))
    if runtime.has_earlier(room.room_id,at):touch(db,room);return
    opponent=next((m for m in members(db,room.room_id) if m.user_id!=event['user_id']),None)
    finish(db,room,at,'win' if opponent else 'cancelled',event['reason'],opponent.user_id if opponent else None)


def leave_room(db, uid, rid, received_at=None, **_):
    """进行中退出判负；倒计时退出回等待并清空双方准备。"""
    room, member = owned_room(db, uid, rid)
    if member.left_at:
        return progression.Resource(None, 204)
    now = received_at or utc_now()
    if room.next_room_id:
        # 旧结算页退出时，同步释放已迁移到后继局的成员席位。
        current = repo.get(db,PlayerPKOccupancy,uid)
        if current and current.room_id == room.next_room_id:
            leave_room(db,uid,room.next_room_id,received_at=now)
    member.left_at, member.ready = now, False
    row = repo.get(db, PlayerPKOccupancy, uid)
    if row and row.room_id == rid:
        row.room_id, row.revision = None, row.revision + 1
    db.flush()
    others = members(db, rid, True)
    if room.status == 'playing':
        voluntary_loss(db,room,uid,now,'player_left')
    elif room.status in ('waiting', 'countdown'):
        if not others:
            finish(db, room, now, 'cancelled', 'empty_room')
        else:
            room.status, room.starts_at, room.ends_at = 'waiting', None, None
            room.host_id=others[0].user_id
            for player in others:
                player.ready = False
            touch(db, room)
    else:
        if not others:
            room.lobby_expires_at = None
        touch(db, room)
    return progression.Resource(None, 204)


def continue_room(db, uid, rid, data, **_):
    """返回与再战共用唯一后继局；确认只作用于本人，重试不取消准备。"""
    room, _ = owned_room(db,uid,rid,True)
    progression.require_pk(db,uid)
    if not room.result:
        progression.fail(409,'result_pending','对局尚未结束。')
    if room.next_room_id:
        next_room, member = owned_room(db,uid,room.next_room_id,True)
    else:
        now = utc_now()
        if not room.lobby_expires_at or room.lobby_expires_at <= now:
            progression.fail(409,'continuation_expired','房间已结束或保留时间已到，请重新邀请或匹配。')
        present = members(db,rid,True)
        for player in present:
            row = occupancy(db,player.user_id)
            if row.room_id != rid or row.ticket_id:
                progression.fail(409,'player_unavailable','玩家已经离开或进入其他房间。')
        # 旧局先释放容量，新建失败时整笔事务回滚，不丢失原席位。
        room.lobby_expires_at = None
        db.flush()
        next_room = new_room(db,[p.user_id for p in present],now,room.game_id,'friend',room.puzzle)
        room.next_room_id = next_room.room_id
        touch(db,room)
        member = next(p for p in members(db,next_room.room_id,True) if p.user_id==uid)
    if data['ready'] and next_room.status=='waiting' and not member.ready:
        readiness(db,uid,next_room.room_id,{'ready':True},progression.etag(next_room.revision))
    return room_resource(db,next_room,uid)


def submit(db, uid, rid, data, received_at, **_):
    """布局合法才冻结提交，入口时间早于DB队列且平局窗口独立结算。"""
    room, _ = owned_room(db, uid, rid, True)
    previous = repo.get(db, PKSubmission, (rid, uid))
    fingerprint = progression.digest(data)
    if previous:
        if previous.payload_hash != fingerprint:
            progression.fail(409, 'submission_conflict', '有效提交不能修改。')
        return progression.Resource({'received_at': progression.iso(previous.received_at), 'links': {'room': '/api/v1/rooms/' + rid}})
    if room.status != 'playing' or received_at < room.starts_at or received_at > room.ends_at:
        progression.fail(409, 'room_not_playing', '当前不在可提交的比赛时间。')
    progression.limiter.check((uid, 'pk_submissions'), 30)
    progression.limiter.check((uid, 'room_submissions', rid), 60, POLICY['match_seconds'])
    valid=(room.game_id=='akari' and set(data)=={'bulbs'} and validate_akari(room.puzzle['puzzle'],data['bulbs'])) or (
        room.game_id=='sudoku' and set(data)=={'values'} and validate_sudoku(room.puzzle['puzzle'],data['values']))
    if not valid:
        progression.fail(422, 'invalid_completion', '终盘尚未满足全部规则。')
    db.add(PKSubmission(room_id=rid, user_id=uid, payload_hash=fingerprint, received_at=received_at))
    touch(db, room)
    return progression.Resource({'received_at': progression.iso(received_at), 'links': {'room': '/api/v1/rooms/' + rid}},
                                 201, {'Location': f'/api/v1/rooms/{rid}/submissions/me'})


def result(db, uid, rid, **_):
    """读取已经提交的结果，不触发结算。"""
    room, _ = owned_room(db, uid, rid)
    if room.result is None:
        progression.fail(404, 'result_pending', '比赛尚未结算。')
    return progression.Resource(deepcopy(room.result))


def my_rooms(db, uid, **_):
    """占用主键提供常数时间恢复入口。"""
    row = repo.get(db, PlayerPKOccupancy, uid, False)
    if not row or not row.room_id:
        return progression.Resource({'items': []})
    return progression.Resource({'items': [get_room(db, uid, row.room_id).data]})


def ticket_resource(ticket, status=200):
    """有限票据表示，成功配对后链接到权威房间。"""
    base = '/api/v1/matchmaking-tickets/' + ticket.ticket_id
    return progression.Resource({'ticket_id': ticket.ticket_id, 'status': ticket.status, 'room_id': ticket.room_id,
           'game_id':ticket.pool.split(':')[0],'created_at':progression.iso(ticket.created_at),
           'expires_at': progression.iso(ticket.expires_at), 'server_now': progression.iso(utc_now()),
           'links': {'self': base, 'room': '/api/v1/rooms/' + ticket.room_id if ticket.room_id else None}},
           status, {'Location': base} if status == 201 else {})


def release_ticket(db, ticket, status):
    """等待票终态化并同事务释放对应占用，重放取消安全。"""
    ticket.status = status
    row = repo.get(db, PlayerPKOccupancy, ticket.user_id)
    if row and row.ticket_id == ticket.ticket_id:
        row.ticket_id, row.revision = None, row.revision + 1
    notify_ticket(db, ticket)


def pair(db, now):
    """按到达事件运行FIFO配对，重新核对双方资格/占用/过期，再原子建房。"""
    waiting = []
    for ticket in waiting_tickets(db):
        if ticket.expires_at <= now:
            release_ticket(db, ticket, 'expired')
            continue
        try:
            progression.require_pk(db, ticket.user_id)
        except progression.AppError:
            release_ticket(db, ticket, 'cancelled')
            continue
        row = occupancy(db, ticket.user_id)
        if row.ticket_id != ticket.ticket_id or row.room_id:
            release_ticket(db, ticket, 'cancelled')
            continue
        waiting.append(ticket)
    while len(waiting) >= 2 and len(active_rooms(db)) < get_settings().pk_room_limit:
        match=next(((a,b) for i,a in enumerate(waiting) for b in waiting[i+1:] if a.pool==b.pool),None)
        if match is None:break
        first, second = match;waiting.remove(first);waiting.remove(second)
        if first.user_id == second.user_id:
            release_ticket(db, second, 'cancelled')
            continue
        room = new_room(db, [first.user_id, second.user_id], now,first.pool.split(':')[0],'match')
        for ticket in (first, second):
            ticket.status, ticket.room_id = 'matched', room.room_id
            notify_ticket(db, ticket)
        db.flush()


def create_ticket(db, uid, data, key, **_):
    """最多8张等待票、每人一张，幂等重试优先于占用检查。"""
    previous, key = progression.idempotent(db, uid, 'matchmaking-tickets', key, data)
    if previous:
        return previous
    progression.require_pk(db, uid)
    progression.limiter.check((uid, 'pk_starts'), 10)
    row = require_free(db, uid)
    if len(waiting_tickets(db)) >= get_settings().pk_ticket_limit:
        progression.fail(503, 'ticket_capacity', '匹配队列已满，请稍后重试。', headers={'Retry-After': '5'})
    now = utc_now()
    ticket = MatchmakingTicket(ticket_id=str(uuid4()), user_id=uid, pool=data['game_id']+':normal', status='waiting',
               created_at=now, expires_at=now + timedelta(seconds=POLICY['ticket_seconds']))
    db.add(ticket)
    row.ticket_id, row.revision = ticket.ticket_id, row.revision + 1
    db.flush()
    pair(db, now)
    db.flush()
    notify_ticket(db, ticket)
    return progression.remember(db, uid, 'matchmaking-tickets', key, data, ticket_resource(ticket, 201), ticket.ticket_id, 1)


def owned_ticket(db, uid, rid):
    """外人票据统一404，过期终态仍保留24小时可恢复查询。"""
    ticket = repo.get(db, MatchmakingTicket, rid)
    if ticket is None or ticket.user_id != uid:
        progression.fail(404, 'ticket_not_found', '匹配票不存在。')
    return ticket


def get_ticket(db, uid, rid, **_):
    """纯读取已提交票状态，不通过GET匹配玩家。"""
    return ticket_resource(owned_ticket(db, uid, rid))


def cancel_ticket(db, uid, rid, **_):
    """取消和配对受同一事务互斥；已配对需使用房间退出。"""
    ticket = owned_ticket(db, uid, rid)
    if ticket.status == 'matched':
        progression.fail(409, 'ticket_matched', '已经配对，请从房间退出。', links={'room': '/api/v1/rooms/' + ticket.room_id})
    if ticket.status == 'waiting':
        release_ticket(db, ticket, 'cancelled')
    return progression.Resource(None, 204)


def my_ticket(db, uid, **_):
    """主键恢复当前等待票，无票返回404。"""
    row = repo.get(db, PlayerPKOccupancy, uid, False)
    if row is None or not row.ticket_id:
        progression.fail(404, 'ticket_not_found', '当前没有匹配票。')
    return get_ticket(db, uid, row.ticket_id)


def lock_active_users(db, actor=None):
    """统一按用户ID锁定有界活跃占用，取消和配对遵守同一顺序。"""
    active = repo.rows(db, PlayerPKOccupancy, (PlayerPKOccupancy.room_id.is_not(None) | PlayerPKOccupancy.ticket_id.is_not(None)), lock=False, limit=17)
    repo.lock_users(db, [r.user_id for r in active] + ([actor] if actor is not None else []))


def committed(db):
    """提交成功再更新队列索引/事件，通知故障不回滚已确认结果。"""
    db.flush()
    waiting_ids = [t.ticket_id for t in waiting_tickets(db)]
    events = db.info.pop('pk_events', {})
    db.commit()
    runtime.waiting_ids = waiting_ids
    for (uid, resource), revision in events.items():
        runtime.publish(uid, resource, revision)


ACTIONS = {'room_create': create_room, 'room_join': join_room, 'room_get': get_room, 'room_ready': readiness,
           'room_leave': leave_room, 'room_submit': submit, 'room_result': result, 'my_rooms': my_rooms,
           'ticket_create': create_ticket, 'ticket_get': get_ticket, 'ticket_cancel': cancel_ticket, 'my_ticket': my_ticket}
READ_ACTIONS = {'room_get', 'room_result', 'my_rooms', 'ticket_get', 'my_ticket'}


def reveal_mine(db,uid,rid,index,received_at,**_):
    """每次揭格只更新本人成员棋盘，踩雷立即判负，全部安全格形成有效完成。"""
    room,member=owned_room(db,uid,rid,True)
    if room.game_id!='mine' or room.status!='playing' or not room.starts_at<=received_at<=room.ends_at:
        progression.fail(409,'room_not_playing','当前不能排雷。')
    if not 0<=index<100:progression.fail(422,'invalid_cell','格子位置无效。')
    if repo.get(db,PKSubmission,(rid,uid)):return room_resource(db,room,uid)
    progression.limiter.check((uid,'arena_reveals',rid),240,60)
    member.board=arena_games.reveal(member.board or {},room.puzzle['puzzle'],index)
    if member.board['outcome']=='lost':
        voluntary_loss(db,room,uid,received_at,'mine_hit')
    elif member.board['outcome']=='won' and not repo.get(db,PKSubmission,(rid,uid)):
        db.add(PKSubmission(room_id=rid,user_id=uid,payload_hash='mine-complete',received_at=received_at));touch(db,room)
    else:touch(db,room)
    return room_resource(db,room,uid)


def change_mode(db,uid,rid,data,match,**_):
    """好友房主更换模式后重置双方准备；匹配房或开局后不可更改。"""
    room,_=owned_room(db,uid,rid,True);progression.precondition(match,room.revision)
    if room.status!='waiting' or room.source!='friend' or room.host_id!=uid:
        progression.fail(409,'mode_locked','当前不能更换模式。')
    room.game_id=data['game_id'];room.puzzle=arena_games.make_puzzle(room.game_id)
    for member in members(db,rid,True):
        member.ready=False;member.board=arena_games.initial_board(room.puzzle['puzzle']) if room.game_id=='mine' else {}
    touch(db,room);return room_resource(db,room,uid)


def arena_state(db,uid,last_room=None,**_):
    """单次读取本人大厅快照，账号、房间、排队和邀请共用事务，避免五路并发抢执行槽。"""
    value=arena.account(db,uid);own=my_rooms(db,uid).data['items'];room_value=None
    if own:room_value=get_room(db,uid,own[0]['room_id'])
    elif last_room:
        try:room_value=get_room(db,uid,last_room)
        except progression.AppError as error:
            if error.status_code!=404:raise
    row=repo.get(db,PlayerPKOccupancy,uid,False)
    ticket=get_ticket(db,uid,row.ticket_id).data if row and row.ticket_id else None
    return progression.Resource({'account':value,'eligibility':progression.eligibility(db,uid),
        'room':{**room_value.data,'etag':room_value.headers.get('ETag')} if room_value else None,
        'ticket':ticket,'invitations':arena.invitations(db,uid).data['items']})


ACTIONS.update({'room_reveal':reveal_mine,'room_mode':change_mode,'room_continue':continue_room,
    'arena_state':arena_state,
    'arena_get':lambda db,uid,**kwargs:progression.Resource(arena.account(db,uid)),
    'arena_search':arena.search,'arena_invites':arena.invitations,'invite_create':arena.create_invitation,
    'invite_accept':lambda db,uid,**kwargs:arena.respond_invitation(db,uid,accept=True,**kwargs),
    'invite_cancel':arena.respond_invitation})
READ_ACTIONS.update({'arena_get','arena_search','arena_invites','arena_state'})


def dispatch(token, db, action, **kwargs):
    """单进程互斥保证全局容量，数据库唯一占用保证持久一致性。"""
    with runtime.lock:
        try:
            current = auth_service.current_session(token, db)
            if not current:
                progression.fail(401, 'unauthenticated', '请先登录。')
            uid = current[1].id
            if action not in READ_ACTIONS:
                # 所有竞技写事务先按同一顺序锁住有界活跃用户及本次邀请双方。
                extra=[uid]
                if action=='invite_create':extra.append(kwargs['data']['user_id'])
                if action in ('invite_accept','invite_cancel'):
                    from ..models.entities.arena import ArenaInvitation
                    invitation=repo.get(db,ArenaInvitation,kwargs['rid'],False)
                    if invitation:extra.extend([invitation.sender_id,invitation.target_id])
                active=repo.rows(db,PlayerPKOccupancy,(PlayerPKOccupancy.room_id.is_not(None)|PlayerPKOccupancy.ticket_id.is_not(None)),lock=False,limit=17)
                repo.lock_users(db,sorted({*extra,*(row.user_id for row in active)}))
                lock_active_users(db, uid)
            response = ACTIONS[action](db, uid, **kwargs)
            if action in ('room_leave','ticket_cancel'):
                # 退出释放容量就是一次配对事件，等待队列无需定时重复查资格。
                db.flush()
                pair(db, utc_now())
            if action not in READ_ACTIONS:
                committed(db)
            else:
                db.commit()
            return response
        except Exception:
            db.info.pop('pk_events', None)
            db.rollback()
            raise


def advance_room(db, room, now, restart):
    """唯一调度器处理倒计时、平局、超时和断线；GET不调用此函数。"""
    if room.result:
        if room.lobby_expires_at and (restart or room.lobby_expires_at<=now):
            room.lobby_expires_at = None
            release_room(db,room)
            touch(db,room)
        elif room.lobby_expires_at:
            changed = False
            for member in members(db,room.room_id,True):
                if runtime.online(member.user_id):
                    if member.disconnected_at:
                        member.disconnected_at = None
                        changed = True
                elif member.disconnected_at is None:
                    member.disconnected_at = now
                    changed = True
                elif member.disconnected_at + timedelta(seconds=POLICY['reconnect_seconds']) <= now:
                    # 结果仍可读；退出的成员不再占用席位，也不能被对方拉入续局。
                    member.left_at, member.ready = now, False
                    row = repo.get(db,PlayerPKOccupancy,member.user_id)
                    if row and row.room_id==room.room_id:
                        row.room_id, row.revision = None, row.revision+1
                    changed = True
            if changed:
                db.flush()
                if not members(db,room.room_id,True):
                    room.lobby_expires_at = None
                touch(db,room)
        return
    if restart:
        finish(db, room, now, 'cancelled', 'server_restart')
        return
    if room.status == 'waiting' and room.expires_at <= now:
        finish(db, room, now, 'cancelled', 'waiting_timeout')
        room.status = 'expired'
        return
    if room.status == 'countdown' and room.starts_at <= now:
        room.status = 'playing'
        touch(db, room)
    if room.status != 'playing':
        return
    if room.puzzle.get('pending_loss'):
        from datetime import datetime
        event=room.puzzle['pending_loss'];at=datetime.fromisoformat(event['at'].removesuffix('Z'))
        if runtime.has_earlier(room.room_id,at):return
        voluntary_loss(db,room,event['user_id'],at,event['reason']);return
    submissions = repo.rows(db, PKSubmission, PKSubmission.room_id == room.room_id, limit=2, order=PKSubmission.received_at)
    deadline = min(room.ends_at, submissions[0].received_at + timedelta(milliseconds=POLICY['draw_ms'])) if submissions else room.ends_at
    if now >= deadline and not runtime.has_pending(room.room_id, deadline):
        valid = [s for s in submissions if s.received_at <= deadline]
        finish(db, room, now, 'draw' if len(valid) != 1 else 'win',
               'valid_completion' if valid else 'match_timeout', valid[0].user_id if len(valid) == 1 else None)
        return
    present = members(db, room.room_id, True)
    changed = False
    for member in present:
        if runtime.online(member.user_id):
            if member.disconnected_at:
                member.disconnected_at, changed = None, True
        elif member.disconnected_at is None:
            member.disconnected_at, changed = now, True
    disconnected = [m for m in present if m.disconnected_at and now >= m.disconnected_at + timedelta(seconds=POLICY['reconnect_seconds'])]
    if len(disconnected) == 2:
        finish(db, room, now, 'cancelled', 'both_offline')
    elif len(disconnected) == 1 and len(present) == 2:
        other = next(m for m in present if m.user_id != disconnected[0].user_id)
        # 双方都已掉线但宽限起点略有差异时不让先后顺序产生获胜者。
        if other.disconnected_at is None:
            finish(db, room, now, 'win', 'opponent_disconnected', other.user_id)
    elif changed:
        touch(db, room)


def maintenance(sessions, now=None, restart=False):
    """一次处理≤4房间/8票；同一个调度任务调用，不扫描历史或常驻新服务。"""
    now = now or utc_now()
    with runtime.lock, sessions() as db:
        try:
            lock_active_users(db)
            from ..models.entities.arena import ArenaInvitation
            expired=repo.rows(db,ArenaInvitation,ArenaInvitation.status=='pending',
                *([] if restart else [ArenaInvitation.expires_at<=now]),limit=32)
            for item in expired:
                item.status='cancelled' if restart else 'expired'
                for who in [item.sender_id,item.target_id]:db.info.setdefault('pk_events',{})[(who,'/api/v1/me/arena/invitations')]=0
            freed_room = False
            for room in active_rooms(db):
                advance_room(db, room, now, restart)
                freed_room |= room.status not in ACTIVE and room.lobby_expires_at is None
            expired_any = False
            for ticket in waiting_tickets(db):
                if restart or ticket.expires_at <= now:
                    release_ticket(db, ticket, 'cancelled' if restart else 'expired')
                    expired_any = True
            db.flush()
            if not restart and (expired_any or freed_room):
                pair(db, now)
            committed(db)
        except Exception:
            db.rollback()
            raise
