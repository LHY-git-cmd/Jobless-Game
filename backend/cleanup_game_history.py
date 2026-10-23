"""单次有界清理正式游戏历史：30天结果、7天墓碑、24小时匹配票；永久成长/资格不删除。

运行 python -m backend.cleanup_game_history；沿用明确配置的项目库，发布前备份后由维护任务按需调用。
"""
import argparse
from datetime import timedelta
from sqlalchemy import delete, select
from .app.common.database import SessionLocal, engine
from .app.common.game_catalog import POLICY
from .app.common.security import utc_now
from .app.models.entities.progression import GameAttempt, GameCompletion, ApiIdempotency
from .app.models.entities.pk import PKRoom, PKSubmission, PKParticipant
from .app.models.entities.matchmaking import MatchmakingTicket
from .app.models.entities.arena import ArenaInvitation
from .app.repositories.progression_repository import lock_users


def attempt_batch(db, batch_size, now):
    """先回收墓碑，再转换旧终态，最后标记过期活跃尝试；不访问权益表。"""
    plans = [('purge', GameAttempt.status == 'tombstone', GameAttempt.ended_at <= now-timedelta(days=POLICY['tombstone_days'])),
             ('tombstone', GameAttempt.status.in_(('completed', 'abandoned', 'lost', 'expired')), GameAttempt.ended_at <= now-timedelta(days=POLICY['history_days'])),
             ('expire', GameAttempt.status == 'active', GameAttempt.expires_at <= now)]
    for action, state, deadline in plans:
        candidates = list(db.scalars(select(GameAttempt).where(state, deadline).limit(batch_size)))
        if not candidates:
            continue
        lock_users(db, [row.user_id for row in candidates])
        ids = [row.attempt_id for row in candidates]
        rows = list(db.scalars(select(GameAttempt).where(GameAttempt.attempt_id.in_(ids), state, deadline)
                              .with_for_update().execution_options(populate_existing=True)))
        ids = [row.attempt_id for row in rows]
        if action in ('purge', 'tombstone'):
            db.execute(delete(GameCompletion).where(GameCompletion.attempt_id.in_(ids)))
        if action == 'purge':
            db.execute(delete(GameAttempt).where(GameAttempt.attempt_id.in_(ids)))
        else:
            for row in rows:
                row.status = 'tombstone' if action == 'tombstone' else 'expired'
                row.ended_at, row.revision = now, row.revision+1
                if action == 'tombstone':
                    row.board = {}
        return len(rows)
    return 0


def other_batch(db, batch_size, now):
    """按父子次序清理房间/票据/幂等凭据，查询均走过期或终态索引。"""
    expired_invites=list(db.scalars(select(ArenaInvitation.invitation_id).where(
        ArenaInvitation.expires_at<=now-timedelta(days=1)).limit(batch_size)))
    if expired_invites:
        db.execute(delete(ArenaInvitation).where(ArenaInvitation.invitation_id.in_(expired_invites)));return len(expired_invites)
    ids = list(db.scalars(select(PKRoom.room_id).where(PKRoom.status.in_(('finished', 'cancelled', 'expired')),
                  PKRoom.finished_at <= now-timedelta(days=POLICY['history_days'])).limit(batch_size)))
    if ids:
        db.execute(delete(PKSubmission).where(PKSubmission.room_id.in_(ids)))
        db.execute(delete(PKParticipant).where(PKParticipant.room_id.in_(ids)))
        db.execute(delete(PKRoom).where(PKRoom.room_id.in_(ids)))
        return len(ids)
    ids = list(db.scalars(select(MatchmakingTicket.ticket_id).where(MatchmakingTicket.status != 'waiting',
                         MatchmakingTicket.expires_at <= now-timedelta(days=1)).limit(batch_size)))
    if ids:
        db.execute(delete(MatchmakingTicket).where(MatchmakingTicket.ticket_id.in_(ids)))
        return len(ids)
    rows = list(db.scalars(select(ApiIdempotency).where(ApiIdempotency.expires_at <= now).limit(batch_size)))
    for row in rows:
        db.delete(row)
    return len(rows)


def clean_history(sessions=SessionLocal, batch_size=200, max_batches=10, now=None):
    """每批最多200个历史主资源，单次默认10批；不启动后台常驻任务。"""
    if not 1 <= batch_size <= 200 or not 1 <= max_batches <= 10:
        raise ValueError('清理上限：batch_size≤200，max_batches≤10')
    total, now = 0, now or utc_now()
    for _ in range(max_batches):
        with sessions() as db:
            try:
                count = attempt_batch(db, batch_size, now)
                if not count:
                    count = other_batch(db, batch_size, now)
                db.commit()
            except Exception:
                db.rollback()
                raise
        total += count
        if count == 0:
            break
    return total


def main():
    """参数显式有界，控制台仅输出最终处理数量。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch-size', type=int, default=200)
    parser.add_argument('--max-batches', type=int, default=10)
    args = parser.parse_args()
    try:
        print(f'Processed history resources: {clean_history(batch_size=args.batch_size, max_batches=args.max_batches)}')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
