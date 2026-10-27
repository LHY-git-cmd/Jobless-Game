"""竞技账户、用户搜索和邀请业务；通过PK统一事务/锁执行，在线状态只读有界内存。"""
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import or_,select
from ..common.security import utc_now
from ..models.entities import User
from ..models.entities.user import PLAYER_ID_OFFSET
from ..models.entities.arena import ArenaAccount,ArenaLedger,ArenaInvitation,ArenaPuzzleHistory
from ..models.entities.pk import PlayerPKOccupancy
from ..repositories import progression_repository as repo
from . import progression_service as growth
from .pk_runtime import runtime

RECENT_PUZZLES=4


def recent_puzzle_ids(db,uids,game):
    """按双方主键各读一行，取该游戏最近4局原题的并集，不扫描历史对局。"""
    blocked=set()
    if game not in ('akari','sudoku'):
        return blocked
    for uid in sorted(set(uids)):
        row=repo.get(db,ArenaPuzzleHistory,(uid,game))
        if row:
            blocked.update(item['base_puzzle_id'] for item in row.recent[-RECENT_PUZZLES:])
    return blocked


def record_puzzle_start(db,room,uids):
    """正式开局与双方近期记录同事务；房间标记及局ID使重复调度不重复追加。"""
    identity=room.puzzle.get('base_puzzle_id')
    if room.game_id not in ('akari','sudoku') or not identity or room.puzzle.get('history_recorded'):
        return
    for uid in sorted(set(uids)):
        row=repo.get(db,ArenaPuzzleHistory,(uid,room.game_id))
        if row is None:
            row=ArenaPuzzleHistory(user_id=uid,game_id=room.game_id,recent=[],revision=0)
            db.add(row)
        if any(item['room_id']==room.room_id for item in row.recent):
            continue
        row.recent=[*row.recent,{'room_id':room.room_id,'base_puzzle_id':identity}][-RECENT_PUZZLES:]
        row.revision+=1
    # 生产autoflush=False，先把有界JSON历史写入当前事务，再允许后续当前读。
    db.flush()
    room.puzzle={**room.puzzle,'history_recorded':True}


def account(db,uid,initialize=False):
    """仅写操作初始化100积分；GET不建账户，等级资格始终由成长摘要确认。"""
    row=repo.get(db,ArenaAccount,uid,initialize)
    if row is None and initialize:
        row=ArenaAccount(user_id=uid,points=100,revision=0);db.add(row);db.flush()
    return {'user_id':uid,'points':row.points if row else 100,'initialized':row is not None,
            'eligible':growth.eligibility(db,uid)['eligible'],'minimum_level':5}


def settle(db,room,members,winner,outcome,now):
    """房间终态和每人唯一积分流水在同一事务提交，允许负分，重复结算不重奖。"""
    values=[]
    for member in sorted(members,key=lambda item:item.user_id):
        previous=repo.get(db,ArenaLedger,(room.room_id,member.user_id))
        if previous:
            values.append({'user_id':member.user_id,'delta':previous.delta,'points':previous.balance});continue
        account(db,member.user_id,True);row=repo.get(db,ArenaAccount,member.user_id)
        delta=(20 if member.user_id==winner else -10) if outcome=='win' else 0
        row.points+=delta;row.revision+=1
        db.add(ArenaLedger(room_id=room.room_id,user_id=member.user_id,delta=delta,balance=row.points,created_at=now))
        values.append({'user_id':member.user_id,'delta':delta,'points':row.points})
    return values


def free(db,uid):
    """账号空闲为未排队且未占用房间，不能通过前端状态绕过。"""
    row=repo.get(db,PlayerPKOccupancy,uid,False)
    return row is None or not (row.room_id or row.ticket_id)


def presence(db,uid,visible,token):
    """认证后更新该会话可见心跳，响应不包含他人信息。"""
    runtime.heartbeat(uid,token,visible);return growth.Resource({'online':runtime.available(uid)})


def search(db,uid,query,**_):
    """精确八位玩家ID或用户名查找最多10人，转换后仍走主键索引。"""
    growth.require_pk(db,uid);growth.limiter.check((uid,'arena_search'),30)
    term=query.strip();conditions=[User.username_key==term.casefold()]
    # 仅八位ASCII数字可以定位公开编号；邀请流程仍使用查找结果中的内部主键。
    if len(term)==8 and term.isascii() and term.isdigit() and int(term)>=10000000:
        conditions.append(User.id==int(term)-PLAYER_ID_OFFSET)
    users=db.scalars(select(User).where(or_(*conditions),User.id!=uid).limit(10)).all()
    return growth.Resource({'items':[{'user_id':u.id,'player_id':u.player_id,'username':u.username,'avatar_id':u.avatar_id,
        'online':runtime.available(u.id),'idle':free(db,u.id),
        'eligible':growth.eligibility(db,u.id)['eligible'],
        'invitable':runtime.available(u.id) and free(db,u.id) and growth.eligibility(db,u.id)['eligible']} for u in users]})


def representation(db,item):
    """邀请只返回双方公开资料及本人有权进入的房间链接。"""
    sender=db.get(User,item.sender_id);target=db.get(User,item.target_id)
    status='expired' if item.status=='pending' and item.expires_at<=utc_now() else item.status
    return {'invitation_id':item.invitation_id,'sender_id':item.sender_id,'target_id':item.target_id,
        'sender_name':sender.username,'sender_avatar_id':sender.avatar_id,'target_name':target.username,
        'target_avatar_id':target.avatar_id,'game_id':item.game_id,'status':status,
        'expires_at':growth.iso(item.expires_at),'room_id':item.room_id}


def invitations(db,uid,**_):
    """有索引、最多20条待处理邀请；GET不写过期状态。"""
    rows=db.scalars(select(ArenaInvitation).where(or_(ArenaInvitation.sender_id==uid,ArenaInvitation.target_id==uid),
        ArenaInvitation.status=='pending',ArenaInvitation.expires_at>utc_now()).order_by(ArenaInvitation.created_at.desc()).limit(20)).all()
    return growth.Resource({'items':[representation(db,item) for item in rows]})


def create_invitation(db,uid,data,key,**_):
    """发送时复核在线/等级/占用，持久化邀请并通知对方；不代替接受入房。"""
    previous,key=growth.idempotent(db,uid,'arena-invites',key,data)
    if previous:return previous
    target=data['user_id'];growth.require_pk(db,uid)
    if target==uid or db.get(User,target) is None:growth.fail(404,'user_not_found','未找到可邀请玩家。')
    repo.lock_users(db,sorted([uid,target]));growth.require_pk(db,target)
    if not runtime.available(target) or not free(db,target) or not free(db,uid):
        growth.fail(409,'player_unavailable','玩家不在线或正在匹配、对局。')
    growth.limiter.check((uid,'arena_invite'),10)
    active=db.scalars(select(ArenaInvitation.target_id).where(ArenaInvitation.status=='pending',
        ArenaInvitation.expires_at>utc_now()).limit(33)).all()
    if len(active)>=32 or active.count(target)>=8:
        growth.fail(503,'invitation_capacity','当前邀请较多，请稍后重试。',headers={'Retry-After':'5'})
    pending=db.scalar(select(ArenaInvitation.invitation_id).where(ArenaInvitation.sender_id==uid,
        ArenaInvitation.status=='pending',ArenaInvitation.expires_at>utc_now()).limit(1))
    if pending:growth.fail(409,'invitation_pending','请先取消当前邀请。')
    now=utc_now();item=ArenaInvitation(invitation_id=str(uuid4()),sender_id=uid,target_id=target,
        game_id=data['game_id'],status='pending',created_at=now,expires_at=now+timedelta(seconds=60))
    db.add(item);db.flush()
    db.info.setdefault('pk_events',{})[(target,'/api/v1/me/arena/invitations')]=0
    return growth.remember(db,uid,'arena-invites',key,data,growth.Resource(representation(db,item),201),item.invitation_id,1)


def respond_invitation(db,uid,rid,accept=False,**_):
    """接受和取消共用PK事务锁，重复接受返回原房间，竞争失败不能占用两局。"""
    item=repo.get(db,ArenaInvitation,rid)
    if item is None or uid not in [item.sender_id,item.target_id]:growth.fail(404,'invitation_not_found','邀请不存在。')
    if accept and uid!=item.target_id:growth.fail(403,'invitation_owner','仅被邀请玩家可以接受。')
    from . import pk_service as pk
    if accept and item.status=='accepted':return pk.get_room(db,uid,item.room_id)
    if not accept:
        if item.status=='pending':item.status='cancelled' if uid==item.sender_id else 'declined'
        else:
            if item.status=='accepted':growth.fail(409,'invitation_accepted','已接受邀请，请从房间退出。')
        for who in [item.sender_id,item.target_id]:db.info.setdefault('pk_events',{})[(who,'/api/v1/me/arena/invitations')]=0
        return growth.Resource(None,204)
    if item.status!='pending' or item.expires_at<=utc_now():growth.fail(410,'invitation_expired','邀请已失效。')
    repo.lock_users(db,sorted([item.sender_id,item.target_id]))
    for who in [item.sender_id,item.target_id]:
        growth.require_pk(db,who)
        if not runtime.available(who) or not free(db,who):growth.fail(409,'player_unavailable','玩家不在线或已被占用。')
    room=pk.new_room(db,[item.sender_id,item.target_id],utc_now(),item.game_id,'friend')
    item.status='accepted';item.room_id=room.room_id
    for who in [item.sender_id,item.target_id]:db.info.setdefault('pk_events',{})[(who,'/api/v1/me/arena/invitations')]=0
    return pk.room_resource(db,room,uid)
