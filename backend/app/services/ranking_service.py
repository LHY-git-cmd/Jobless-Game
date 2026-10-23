"""独立关卡、记录保留、幂等和排行榜事务；同步业务通过公共有界执行器运行。"""

from copy import deepcopy
from uuid import uuid4
from ..common import concurrency
from ..common.exceptions import AppError
from ..common.security import utc_now
from ..models.entities.ranking import ChallengeProgress, CompletionRecord, LeaderboardEntry
from ..repositories import ranking_repository as repository
from . import auth_service
from .progression_service import account_level

GAMES = ("mine", "akari", "sudoku")


def require_user(token, db, lock=False):
    """在同一个数据库工作线程内认证，写操作先取得固定的用户锁。"""
    current = auth_service.current_session(token, db)
    if not current:
        raise AppError(401, "请先登录。")
    user = current[1]
    if lock:
        repository.lock_user(db, user.id)
    return user


def new_level():
    """每次重开换新尝试标识，旧请求不能重新进入最近记录。"""
    return {"attempt_id": str(uuid4()), "seconds": None, "development": False}


def state_response(progress):
    """返回有限公开状态，不暴露用户凭据或内部请求标识。"""
    return {"run_id": progress.run_id, "revision": progress.revision,
            "levels": deepcopy(progress.game_state["levels"]), "total_recorded": progress.total_recorded}


def start_transaction(token, payload, db):
    """创建或幂等返回当前轮次；新请求替换旧进度但不删除历史。"""
    try:
        user = require_user(token, db, True)
        progress = repository.progress(db, user.id)
        if progress and progress.game_state["start_request_id"] == str(payload.request_id):
            db.commit()
            return state_response(progress)
        now = utc_now()
        if not progress:
            progress = ChallengeProgress(user_id=user.id)
            repository.add(db, progress)
        progress.run_id, progress.revision = str(uuid4()), 0
        progress.game_state = {"start_request_id": str(payload.request_id), "levels": [new_level() for _ in GAMES]}
        progress.total_recorded = False
        progress.created_at = progress.updated_at = now
        db.commit()
        return state_response(progress)
    except Exception:
        db.rollback()
        raise


def require_progress(token, run_id, db):
    """只接受当前登录用户的当前进度，拒绝旧轮次写入。"""
    user = require_user(token, db, True)
    progress = repository.progress(db, user.id)
    if not progress or progress.run_id != str(run_id):
        raise AppError(409, "挑战已失效，请返回首页重新选择关卡。")
    return progress


def progress_transaction(token, run_id, db):
    """恢复棋局前核对账号与当前轮次，只返回已有进度，不创建或重置挑战。"""
    try:
        result = state_response(require_progress(token, run_id, db))
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def restart_transaction(token, run_id, payload, db):
    """仅重置指定关卡，幂等请求不会重复递增版本或换新尝试。"""
    try:
        progress = require_progress(token, run_id, db)
        state = deepcopy(progress.game_state)
        request = {"request_id": str(payload.request_id), "category": payload.category, "revision": payload.revision}
        if state.get("last_restart") == request:
            db.commit()
            return state_response(progress)
        if payload.revision != progress.revision:
            raise AppError(409, "关卡状态已更新，请重新开始本轮。")
        index = GAMES.index(payload.category)
        state["levels"][index] = new_level()
        state["last_restart"] = request
        progress.game_state = state
        progress.revision += 1
        progress.updated_at = utc_now()
        db.commit()
        return state_response(progress)
    except Exception:
        db.rollback()
        raise


def save_record(db, progress, category, attempt_id, seconds):
    """同事务写快照、严格改善最佳并清理其余记录，时间相同保留先达成最佳。"""
    now = utc_now()
    record = CompletionRecord(user_id=progress.user_id, category=category, run_id=progress.run_id,
                              attempt_id=attempt_id, duration_seconds=seconds, completed_at=now)
    repository.add(db, record)
    db.flush()
    entry = repository.best(db, progress.user_id, category, lock=True)
    if not entry:
        entry = LeaderboardEntry(user_id=progress.user_id, category=category, best_record_id=record.id,
                                 best_duration_seconds=seconds, achieved_at=now)
        repository.add(db, entry)
    elif seconds < entry.best_duration_seconds:
        entry.best_record_id, entry.best_duration_seconds, entry.achieved_at = record.id, seconds, now
    db.flush()
    repository.retain_records(db, progress.user_id, category, entry.best_record_id)


def complete_transaction(token, run_id, payload, db, config):
    """任意关卡均可独立保存，不再生成整轮成绩。"""
    try:
        if payload.development and not config.dev_quick_complete_enabled:
            raise AppError(403, "开发验收通关未启用。")
        progress = require_progress(token, run_id, db)
        state = deepcopy(progress.game_state)
        index = GAMES.index(payload.category)
        level = state["levels"][index]
        # 尝试编号隔离本关重开；其他关重开后的全局版本变化不作废本关待提交成绩。
        if payload.revision > progress.revision or level["attempt_id"] != str(payload.attempt_id):
            raise AppError(409, "此尝试已失效，请重新开始本轮。")
        if level["seconds"] is not None:
            if level["seconds"] != payload.duration_seconds or level["development"] != payload.development:
                raise AppError(409, "已接收的通关成绩不能修改。")
            db.commit()
            return state_response(progress)
        level["seconds"], level["development"] = payload.duration_seconds, payload.development
        save_record(db, progress, payload.category, level["attempt_id"], payload.duration_seconds)
        progress.game_state, progress.updated_at = state, utc_now()
        db.commit()
        return state_response(progress)
    except Exception:
        db.rollback()
        raise


def record_response(record):
    """只序列化单关公开成绩字段，旧数据库快照字段不再对外展示。"""
    return {"id": record.id, "duration_seconds": record.duration_seconds, "completed_at": record.completed_at,
            "times": None}


def records_transaction(token, category, db):
    """查询自己的最佳及最近三次，重复的记录使用同一 ID。"""
    user = require_user(token, db)
    entry = repository.best(db, user.id, category)
    best = repository.record(db, entry.best_record_id) if entry else None
    return {"category": category, "best": record_response(best) if best else None,
            "recent": [record_response(record) for record in repository.recent(db, user.id, category)]}


def rankings_transaction(category, page, page_size, db):
    """在一个读取事务中计算榜单，名次跨页仍使用完整分数集合。"""
    rows, total = repository.ranking_rows(db, category, page, page_size)
    return {"category": category, "page": page, "page_size": page_size, "total": total,
            "entries": [{"rank": row["rank"], "user_id": row["user_id"], "username": row["username"], "avatar_id": row["avatar_id"],
                         "duration_seconds": row["duration_seconds"], "achieved_at": row["achieved_at"],
                         "times": None}
                        for row in rows]}


async def execute(function, *args):
    """所有同步认证、锁与 SQL 共用既有执行槽，不阻塞事件循环。"""
    return await concurrency.bounded_db_call(function, *args)


def growth_rankings_transaction(category, page, page_size, db):
    """等级使用正式成长阈值计算，同等级按经验排序；不引入独立等级或积分存储。"""
    rows, total = repository.growth_ranking_rows(db, category, page, page_size)
    return {'category': category, 'page': page, 'page_size': page_size, 'total': total,
            'entries': [{**dict(row), 'level': account_level(row['xp'])} for row in rows]}
