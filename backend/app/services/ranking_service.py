"""挑战顺序、记录保留、幂等和排行榜事务；同步业务通过公共有界执行器运行。"""

from copy import deepcopy
from uuid import uuid4
from ..common import concurrency
from ..common.exceptions import AppError
from ..common.security import utc_now
from ..models.entities.ranking import ChallengeProgress, CompletionRecord, LeaderboardEntry
from ..repositories import ranking_repository as repository
from . import auth_service

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
    """只接受当前登录用户的当前轮次，历史成绩不能解锁新轮次。"""
    user = require_user(token, db, True)
    progress = repository.progress(db, user.id)
    if not progress or progress.run_id != str(run_id):
        raise AppError(409, "本轮已失效，请返回首页从第一关重新开始。")
    return progress


def require_previous(levels, index):
    """前序关卡必须在本轮全部保存，禁止直接请求接口跳关。"""
    if any(level["seconds"] is None for level in levels[:index]):
        raise AppError(409, "请先通关并保存前一关。")


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
    """重开先校验解锁，幂等请求不会重复递增版本或换新尝试。"""
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
        require_previous(state["levels"], index)
        # 总成绩已冻结。再次挑战必须新建完整轮次，避免改写同一轮总快照。
        if progress.total_recorded:
            raise AppError(409, "本轮已完成，请返回首页开始新一轮。")
        state["levels"][index:] = [new_level() for _ in GAMES[index:]]
        state["last_restart"] = request
        progress.game_state = state
        progress.revision += 1
        progress.updated_at = utc_now()
        db.commit()
        return state_response(progress)
    except Exception:
        db.rollback()
        raise


def save_record(db, progress, category, attempt_id, seconds, times=None):
    """同事务写快照、严格改善最佳并清理其余记录，时间相同保留先达成最佳。"""
    now = utc_now()
    record = CompletionRecord(user_id=progress.user_id, category=category, run_id=progress.run_id,
                              attempt_id=attempt_id, duration_seconds=seconds, completed_at=now,
                              mine_seconds=times[0] if times else None, akari_seconds=times[1] if times else None,
                              sudoku_seconds=times[2] if times else None)
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
    """仅完成一个当前关；三关成功保存时自动创建独立总榜快照。"""
    try:
        if payload.development and not config.dev_quick_complete_enabled:
            raise AppError(403, "开发验收通关未启用。")
        progress = require_progress(token, run_id, db)
        state = deepcopy(progress.game_state)
        index = GAMES.index(payload.category)
        level = state["levels"][index]
        if progress.revision != payload.revision or level["attempt_id"] != str(payload.attempt_id):
            raise AppError(409, "此尝试已失效，请重新开始本轮。")
        require_previous(state["levels"], index)
        if level["seconds"] is not None:
            if level["seconds"] != payload.duration_seconds or level["development"] != payload.development:
                raise AppError(409, "已接收的通关成绩不能修改。")
            db.commit()
            return state_response(progress)
        level["seconds"], level["development"] = payload.duration_seconds, payload.development
        save_record(db, progress, payload.category, level["attempt_id"], payload.duration_seconds)
        times = [item["seconds"] for item in state["levels"]]
        if all(value is not None for value in times) and not progress.total_recorded:
            save_record(db, progress, "total", progress.run_id, sum(times), times)
            progress.total_recorded = True
        progress.game_state, progress.updated_at = state, utc_now()
        db.commit()
        return state_response(progress)
    except Exception:
        db.rollback()
        raise


def record_response(record):
    """只序列化公开成绩字段，总榜明细来自原轮次快照。"""
    return {"id": record.id, "duration_seconds": record.duration_seconds, "completed_at": record.completed_at,
            "times": [record.mine_seconds, record.akari_seconds, record.sudoku_seconds] if record.category == "total" else None}


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
            "entries": [{"rank": row["rank"], "user_id": row["user_id"], "username": row["username"],
                         "duration_seconds": row["duration_seconds"], "achieved_at": row["achieved_at"],
                         "times": [row["mine_seconds"], row["akari_seconds"], row["sudoku_seconds"]] if category == "total" else None}
                        for row in rows]}


async def execute(function, *args):
    """所有同步认证、锁与 SQL 共用既有执行槽，不阻塞事件循环。"""
    return await concurrency.bounded_db_call(function, *args)
