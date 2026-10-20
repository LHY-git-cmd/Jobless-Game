"""排行榜 SQL 与锁操作；所有事务边界由 Service 控制。"""

from sqlalchemy import delete, func, select
from ..models.entities import User
from ..models.entities.ranking import ChallengeProgress, CompletionRecord, LeaderboardEntry


def add(db, entity):
    """暂存进度、快照或摘要实体，不自行提交事务。"""
    db.add(entity)


def record(db, record_id):
    """按最佳摘要引用查询不可变快照。"""
    return db.get(CompletionRecord, record_id)


def lock_user(db, user_id):
    """以用户行为固定锁顺序，串行化同用户的建轮、重开和提交。"""
    return db.scalar(select(User.id).where(User.id == user_id).with_for_update())


def progress(db, user_id):
    """锁后强制刷新进度，避免会话缓存读到并发请求前的状态。"""
    return db.scalar(select(ChallengeProgress).where(ChallengeProgress.user_id == user_id)
                     .with_for_update().execution_options(populate_existing=True))


def best(db, user_id, category, lock=False):
    """写事务使用当前锁定读，避免认证查询建立的 RR 旧快照覆盖新最佳。"""
    query = select(LeaderboardEntry).where(LeaderboardEntry.user_id == user_id, LeaderboardEntry.category == category)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def recent(db, user_id, category, lock=False):
    """使用索引读取最近三次，清理使用锁定读看到等待用户锁前后的全部提交。"""
    query = select(CompletionRecord).where(CompletionRecord.user_id == user_id, CompletionRecord.category == category)\
        .order_by(CompletionRecord.completed_at.desc(), CompletionRecord.id.desc()).limit(3)
    return db.scalars(query.with_for_update() if lock else query).all()


def retain_records(db, user_id, category, best_id):
    """删除最佳与最近三次并集之外的记录，不会删除仍被摘要引用的最佳。"""
    keep = {best_id, *(row.id for row in recent(db, user_id, category, lock=True))}
    db.execute(delete(CompletionRecord).where(CompletionRecord.user_id == user_id, CompletionRecord.category == category,
                                            CompletionRecord.id.not_in(keep)))


def ranking_rows(db, category, page, page_size):
    """先按索引取有限页，再统计更快人数，避免为每页物化整个排行榜。"""
    ranked = select(LeaderboardEntry.user_id, LeaderboardEntry.best_record_id,
                    LeaderboardEntry.best_duration_seconds.label("duration_seconds"), LeaderboardEntry.achieved_at)\
        .where(LeaderboardEntry.category == category)\
        .order_by(LeaderboardEntry.best_duration_seconds, LeaderboardEntry.achieved_at, LeaderboardEntry.user_id)\
        .offset((page - 1) * page_size).limit(page_size).subquery()
    rank = select(func.count() + 1).select_from(LeaderboardEntry).where(
        LeaderboardEntry.category == category, LeaderboardEntry.best_duration_seconds < ranked.c.duration_seconds
    ).correlate(ranked).scalar_subquery().label("rank")
    rows = db.execute(select(ranked, rank, User.username, User.avatar_id, CompletionRecord.mine_seconds,
                             CompletionRecord.akari_seconds, CompletionRecord.sudoku_seconds)
                      .join(User, User.id == ranked.c.user_id)
                      .join(CompletionRecord, CompletionRecord.id == ranked.c.best_record_id)
                      .order_by(ranked.c.duration_seconds, ranked.c.achieved_at, ranked.c.user_id)).mappings().all()
    total = db.scalar(select(func.count()).select_from(LeaderboardEntry).where(LeaderboardEntry.category == category))
    return rows, total
