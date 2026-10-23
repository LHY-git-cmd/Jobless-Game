"""体力服务：调用方持有账号事务锁，按服务器时间恢复，不使用后台任务或客户端余额。"""
from datetime import timedelta
from ..common.security import utc_now
from ..common.exceptions import AppError
from ..models.entities.progression import PlayerEnergy,AttemptEnergy
from ..repositories import progression_repository as repo

# 所有游戏共用同一上限与自然恢复周期；改变规则需另行发布策略。
CAPACITY=5
RECOVERY_SECONDS=1800


def iso(value):
    """数据库使用无时区UTC，公开时间显式附Z，浏览器只用来显示倒计时。"""
    return value.isoformat(timespec='microseconds')+'Z'


def balance(db,uid,now=None):
    """惰性初始化及恢复，在账号锁内读取当前余额，完整时间间隔最多补到5点。"""
    now=now or utc_now()
    row=repo.get(db,PlayerEnergy,uid)
    if row is None:
        row=PlayerEnergy(user_id=uid,current=CAPACITY,recovery_at=None,revision=0);db.add(row);db.flush()
    if row.current<CAPACITY and row.recovery_at and now>=row.recovery_at:
        recovered=1+int((now-row.recovery_at).total_seconds()//RECOVERY_SECONDS)
        row.current=min(CAPACITY,row.current+recovered)
        row.recovery_at=None if row.current==CAPACITY else row.recovery_at+timedelta(seconds=recovered*RECOVERY_SECONDS)
        row.revision+=1
    if row.current>=CAPACITY:
        row.current=CAPACITY;row.recovery_at=None
    # 防御旧测试或人工修复产生的不完整状态，不改变健康的恢复周期。
    elif row.recovery_at is None:
        row.recovery_at=now+timedelta(seconds=RECOVERY_SECONDS);row.revision+=1
    return row


def snapshot(db,uid,now=None):
    """返回权威快照和修订号；满体力没有倒计时，不接受客户端时间。"""
    now=now or utc_now();row=balance(db,uid,now)
    return {'current':row.current,'capacity':CAPACITY,'revision':row.revision,
            'recovery_seconds':RECOVERY_SECONDS,'next_recovery_at':iso(row.recovery_at) if row.recovery_at else None,
            'server_now':iso(now),'links':{'self':'/api/v1/me/energy'}}


def cost(level,mode='campaign'):
    """入门免费且不产生扣费凭证；当前三款正式普通/资格棋局消耗1点。"""
    return int(mode in ('campaign','qualification') and level['game_id'] in ('mine','akari','sudoku') and not level['puzzle'].get('tutorial'))


def spend(db,uid,attempt,level):
    """付费与创建尝试在同一事务内，凭证主键阻止同一尝试重复消费。"""
    row=balance(db,uid)
    if not cost(level,attempt.mode):return
    if row.current<1:
        raise AppError(409,{'code':'energy_insufficient','message':'体力不足，请等待恢复后再开始普通关卡。','energy':snapshot(db,uid)})
    if repo.get(db,AttemptEnergy,attempt.attempt_id):return
    row.current-=1;row.revision+=1
    if row.recovery_at is None:row.recovery_at=utc_now()+timedelta(seconds=RECOVERY_SECONDS)
    db.add(AttemptEnergy(attempt_id=attempt.attempt_id,refunded=0))


def refund(db,uid,attempt):
    """仅返还该局实际扣过的1点；入门、旧局、重复终盘都不能多返。"""
    row=balance(db,uid);receipt=repo.get(db,AttemptEnergy,attempt.attempt_id)
    if receipt is None or receipt.refunded:return
    receipt.refunded=1;row.current=min(CAPACITY,row.current+1);row.revision+=1
    if row.current==CAPACITY:row.recovery_at=None
