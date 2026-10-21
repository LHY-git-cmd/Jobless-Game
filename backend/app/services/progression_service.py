"""正式尝试与成长事务：服务端判题/计时、里程碑幂等、资格和外观权益。"""

from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import timedelta
import hashlib
import json
import secrets
from threading import Lock
from time import monotonic
from uuid import UUID, uuid4
from ..common.config import get_settings
from ..common.game_catalog import LEVELS, POLICY, QUALIFICATIONS, metadata
from ..common.exceptions import AppError
from ..common.security import utc_now
from ..models.entities.progression import (GameLevelVersion, PlayerProgression, PlayerLevelProgress,
    GameAttempt, GameCompletion, ProgressionGrant, PlayerQualification, ApiIdempotency)
from ..models.entities.cosmetic import PlayerCosmetic, PlayerAppearance
from ..repositories import progression_repository as repo
from . import auth_service
from .game_rules import validate_akari, validate_sudoku, stars_for

DEFAULT_APPEARANCE = {key: 'default' for key in ('theme_id', 'mine_skin_id', 'akari_skin_id', 'sudoku_skin_id')}
COSMETICS = [{'cosmetic_id': 'default', 'name': '海岛', 'kind': 'theme', 'required_stars': 0, 'asset_version': 1},
             {'cosmetic_id': 'starlight', 'name': '星光', 'kind': 'theme', 'required_stars': POLICY['theme_stars'], 'asset_version': 1}]


@dataclass
class Resource:
    """HTTP资源表示由控制器适配，业务层不依赖Response。"""
    data: dict | None
    status: int = 200
    headers: dict = field(default_factory=dict)


class WindowLimiter:
    """单进程有界滑动窗口；不持久化计时心跳。"""

    def __init__(self):
        """最多4096组短期用户操作，不形成无限用户缓存。"""
        self.entries, self.lock = OrderedDict(), Lock()

    def clear(self):
        """供隔离测试或服务重启清空本进程短期状态。"""
        with self.lock:
            self.entries.clear()

    def check(self, key, maximum, seconds=60):
        """在有界窗口内计数，超过额度明确429和Retry-After。"""
        now = monotonic()
        with self.lock:
            values = self.entries.pop(key, deque())
            while values and values[0] <= now - seconds:
                values.popleft()
            if len(values) >= maximum:
                self.entries[key] = values
                fail(429, 'rate_limited', '操作过于频繁，请稍后重试。', headers={'Retry-After': str(seconds)})
            values.append(now)
            self.entries[key] = values
            while len(self.entries) > 4096:
                self.entries.popitem(last=False)


limiter = WindowLimiter()


def fail(status, code, message, headers=None, **extensions):
    """业务错误携带稳定code，新控制器统一转Problem Details。"""
    raise AppError(status, {'code': code, 'message': message, **extensions}, headers)


def iso(value):
    """数据库无时区UTC显式转换为RFC3339 Z表示。"""
    return value.isoformat(timespec='microseconds') + 'Z'


def etag(revision):
    """强ETag仅表示当前资源修订。"""
    return f'"{revision}"'


def precondition(supplied, revision):
    """缺少条件428，旧版本412，状态冲突另用409。"""
    if supplied is None:
        fail(428, 'precondition_required', '请先读取最新状态再修改。')
    if supplied != etag(revision):
        fail(412, 'version_mismatch', '状态已更新，请刷新后重试。')


def digest(payload):
    """规范化终盘和负载摘要；灯泡顺序不影响同一次提交的身份。"""
    normalized = deepcopy(payload)
    if isinstance(normalized.get('bulbs'), list):
        normalized['bulbs'] = sorted(normalized['bulbs'])
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def idempotent(db, uid, kind, key, payload):
    """先查原结果，再检查业务当前状态；键必须是UUID。"""
    try:
        normalized_key = str(UUID(key))
    except (ValueError, TypeError, AttributeError):
        fail(422, 'idempotency_key_required', '请提供UUID格式的Idempotency-Key。')
    existing = repo.get(db, ApiIdempotency, (uid, kind, normalized_key))
    if existing:
        if existing.payload_hash != digest(payload):
            fail(409, 'idempotency_conflict', '同一幂等键不能用于不同内容。')
        return Resource(deepcopy(existing.snapshot['body']), existing.original_status, existing.snapshot['headers']), normalized_key
    return None, normalized_key


def remember(db, uid, kind, key, payload, resource, resource_id, days=7):
    """创建表示和幂等凭据同事务提交，避免丢响应后重复资源。"""
    db.add(ApiIdempotency(user_id=uid, resource_kind=kind, key=key, payload_hash=digest(payload), resource_id=resource_id,
           original_status=resource.status, snapshot={'body': resource.data, 'headers': resource.headers},
           expires_at=utc_now() + timedelta(days=days)))
    return resource


def account_level(xp):
    """统一账号等级采用已冻结的有限阈值。"""
    return sum(xp >= value for value in POLICY['level_xp'])


def progression(db, uid, lock=False):
    """读取默认零进度不写库，永久摘要只在合法结算时创建。"""
    row = repo.get(db, PlayerProgression, uid, lock)
    xp, stars = (row.xp, row.total_stars) if row else (0, 0)
    level = account_level(xp)
    return {'xp': xp, 'level': level, 'total_stars': stars,
            'next_level_xp': POLICY['level_xp'][level] if level < len(POLICY['level_xp']) else None,
            'reward_policy_version': POLICY['version'], 'links': {'self': '/api/v1/me/progression'}}


def progress_rows(db, uid, lock=False):
    """关卡数有限，当前读取最多50条。"""
    return {r.level_id: r for r in repo.rows(db, PlayerLevelProgress, PlayerLevelProgress.user_id == uid, lock=lock)}


def requirements(level, summary, progress):
    """同时检查等级和指定前置，返回可直接展示的锁定原因。"""
    reasons = []
    if summary['level'] < level['minimum_level']:
        reasons.append(f"需要达到Lv.{level['minimum_level']}")
    prerequisite = level.get('prerequisite_level_id')
    if prerequisite and (prerequisite not in progress or progress[prerequisite].best_stars < 1):
        reasons.append(f"需要通过照明第{int(prerequisite[-3:])}关")
    return reasons


def eligibility(db, uid, lock=False):
    """三项AND且只认永久正式资格，不查询旧客户端成绩。"""
    completed = {r.requirement_id for r in repo.rows(db, PlayerQualification, PlayerQualification.user_id == uid, lock=lock)}
    items = [{'level_id': key, 'name': LEVELS[key]['name'], 'completed': key in completed,
              'links': {'level': '/api/v1/levels/' + key, 'play': '/journey.html?level=' + key}} for key in QUALIFICATIONS]
    return {'eligible': all(v['completed'] for v in items), 'requirements': items,
            'links': {'self': '/api/v1/me/pk-eligibility'}}


def require_pk(db, uid):
    """创建、加入、入队及实际配对都调用同一个权威资格检查。"""
    value = eligibility(db, uid, True)
    if not value['eligible']:
        fail(403, 'pk_locked', '请先完成扫雷初级、照明第1关和数独初级。', requirements=value['requirements'])


def level_definition(db, level_id, version=1):
    """尝试绑定数据库已发布的不可变版本，禁止自动回退到新题。"""
    row = repo.get(db, GameLevelVersion, (level_id, version), False)
    if row is None:
        fail(404, 'level_not_found', '关卡或版本不存在。')
    return row.definition


def mine_neighbors(index):
    """正式扫雷固定10×10，8邻域不跨边界。"""
    r, c = divmod(index, 10)
    return [a*10+b for a in range(max(0, r-1), min(10, r+2))
            for b in range(max(0, c-1), min(10, c+2)) if (a, b) != (r, c)]


def mine_public(board):
    """只返回已揭格；失败后才公开雷，胜利不需要发隐藏布局。"""
    mines = set(board['mine_indices'])
    visible = [{'index': i, 'value': -1 if i in mines else sum(j in mines for j in mine_neighbors(i))} for i in board['revealed']]
    return {'revealed': visible, 'outcome': board['outcome'], **({'mines': sorted(mines)} if board['outcome'] == 'lost' else {})}


def attempt_resource(db, attempt, status=200):
    """本人尝试快照包含题目，无标准答案或扫雷种子。"""
    level = level_definition(db, attempt.level_id, attempt.level_version)
    base = '/api/v1/attempts/' + attempt.attempt_id
    data = {'attempt_id': attempt.attempt_id, 'level_id': attempt.level_id, 'level_version': attempt.level_version,
            'game_id': attempt.game_id, 'mode': attempt.mode, 'status': attempt.status, 'revision': attempt.revision,
            'started_at': iso(attempt.started_at), 'expires_at': iso(attempt.expires_at), 'server_now': iso(utc_now()),
            'puzzle': deepcopy(level['puzzle']), 'links': {'self': base, 'completion': base + '/completion'}}
    if attempt.game_id == 'mine':
        data['board'] = mine_public(attempt.board)
    headers = {'ETag': etag(attempt.revision)}
    if status == 201:
        headers['Location'] = base
    return Resource(data, status, headers)


def owned_attempt(db, uid, attempt_id):
    """账号锁先于尝试锁，外人统一404；到期只拒绝，GET不修改。"""
    attempt = repo.get(db, GameAttempt, attempt_id)
    if not attempt or attempt.user_id != uid:
        fail(404, 'attempt_not_found', '尝试不存在。')
    if attempt.status == 'expired' or (attempt.status == 'active' and attempt.expires_at <= utc_now()):
        fail(410, 'attempt_expired', '本次尝试已过期，请重新开始。')
    return attempt


def create_attempt(db, uid, data, key, **_):
    """幂等优先；同关最多一个active，总活跃关卡最多10。"""
    previous, key = idempotent(db, uid, 'attempts', key, data)
    if previous:
        return previous
    limiter.check((uid, 'starts'), 10)
    level = level_definition(db, data['level_id'], data['level_version'])
    if data['mode'] not in level['modes']:
        fail(422, 'invalid_mode', '此关卡不支持该模式。')
    reasons = requirements(level, progression(db, uid, True), progress_rows(db, uid, True))
    if reasons:
        fail(403, 'level_locked', '，'.join(reasons), requirements={'minimum_level': level['minimum_level'],
             'prerequisite_level_id': level['prerequisite_level_id']})
    active = repo.rows(db, GameAttempt, GameAttempt.user_id == uid, GameAttempt.status == 'active')
    now = utc_now()
    for attempt in active:
        if attempt.expires_at <= now:
            attempt.status, attempt.ended_at = 'expired', now
        elif attempt.level_id == level['level_id']:
            fail(409, 'attempt_active', '本关已有正在进行的尝试。', links={'attempt': '/api/v1/attempts/' + attempt.attempt_id})
    if sum(a.status == 'active' for a in active) >= 10:
        fail(409, 'attempt_limit', '正式活跃关卡已达上限。')
    board = {'mine_indices': secrets.SystemRandom().sample(range(100), 10), 'revealed': [], 'requested': [], 'outcome': 'active'} if level['game_id'] == 'mine' else {}
    attempt = GameAttempt(attempt_id=str(uuid4()), user_id=uid, level_id=level['level_id'], level_version=level['level_version'],
              game_id=level['game_id'], mode=data['mode'], status='active', revision=0, started_at=now,
              expires_at=now + timedelta(days=POLICY['attempt_days']), board=board)
    db.add(attempt)
    db.flush()
    resource = attempt_resource(db, attempt, 201)
    return remember(db, uid, 'attempts', key, data, resource, attempt.attempt_id)


def get_attempt(db, uid, rid, **_):
    """恢复前核验正式凭据，客户端存档不是奖励凭据。"""
    return attempt_resource(db, owned_attempt(db, uid, rid))


def abandon_attempt(db, uid, rid, match, **_):
    """只允许放弃活跃尝试；同版本放弃后的网络重放也安全。"""
    attempt = owned_attempt(db, uid, rid)
    if attempt.status == 'abandoned' and match == etag(attempt.revision - 1):
        return attempt_resource(db, attempt)
    precondition(match, attempt.revision)
    if attempt.status != 'active':
        fail(409, 'attempt_terminal', '本次尝试已结束。')
    attempt.status, attempt.ended_at = 'abandoned', utc_now()
    attempt.revision += 1
    return attempt_resource(db, attempt)


def reveal(db, uid, rid, index, **_):
    """用户锁串行揭格，重放已处理索引不会再次展开或恢复lost棋局。"""
    attempt = owned_attempt(db, uid, rid)
    if attempt.game_id != 'mine' or not 0 <= index < 100:
        fail(422, 'invalid_cell', '揭格位置不合法。')
    board = deepcopy(attempt.board)
    if index in board['requested'] or index in board['revealed']:
        return attempt_resource(db, attempt)
    if attempt.status != 'active' or board['outcome'] != 'active':
        fail(409, 'attempt_terminal', '本次扫雷已结束。')
    board['requested'].append(index)
    mines, revealed = set(board['mine_indices']), set(board['revealed'])
    if index in mines:
        revealed.add(index)
        board['outcome'], attempt.status, attempt.ended_at = 'lost', 'lost', utc_now()
    else:
        pending = [index]
        while pending:
            cell = pending.pop()
            if cell in revealed or cell in mines:
                continue
            revealed.add(cell)
            neighbors = mine_neighbors(cell)
            if not mines.intersection(neighbors):
                pending.extend(n for n in neighbors if n not in revealed)
        if len(revealed) == 90:
            board['outcome'] = 'won'
    board['revealed'] = sorted(revealed)
    attempt.board = board
    attempt.revision += 1
    result = attempt_resource(db, attempt, 201)
    result.headers['Location'] = f'/api/v1/attempts/{rid}/reveals/{index}'
    return result


def grant_cosmetics(db, uid, summary):
    """结算同事务永久授予主题，后续提高门槛不收回已拥有权益。"""
    unlocked = []
    for item in COSMETICS:
        if summary.total_stars >= item['required_stars'] and not repo.get(db, PlayerCosmetic, (uid, item['cosmetic_id'])):
            db.add(PlayerCosmetic(user_id=uid, cosmetic_id=item['cosmetic_id'], unlocked_at=utc_now(), source='stars'))
            unlocked.append(item['cosmetic_id'])
    return unlocked


def complete_attempt(db, uid, rid, data, received_at, **_):
    """判题、里程碑、资格、外观和不可变快照在一个事务内提交。"""
    attempt = owned_attempt(db, uid, rid)
    fingerprint = digest(data)
    existing = repo.get(db, GameCompletion, rid)
    if existing:
        if existing.payload_hash != fingerprint:
            fail(409, 'completion_conflict', '已经确认的终盘不能覆盖。')
        return Resource(deepcopy(existing.snapshot))
    if attempt.status != 'active':
        fail(409, 'attempt_terminal', '本次尝试已结束。')
    limiter.check((uid, 'submissions'), 30)
    level = level_definition(db, attempt.level_id, attempt.level_version)
    valid = (attempt.game_id == 'akari' and set(data) == {'bulbs'} and validate_akari(level['puzzle'], data['bulbs'])) or (
             attempt.game_id == 'sudoku' and set(data) == {'values'} and validate_sudoku(level['puzzle'], data['values'])) or (
             attempt.game_id == 'mine' and not data and attempt.board['outcome'] == 'won')
    if not valid:
        fail(422, 'invalid_completion', '终盘尚未满足全部规则。')
    duration = max(0, int((received_at - attempt.started_at).total_seconds() * 1000))
    current = stars_for(level, duration) if attempt.mode == 'campaign' else 0
    summary = repo.get(db, PlayerProgression, uid)
    if summary is None:
        summary = PlayerProgression(user_id=uid, xp=0, total_stars=0, revision=0)
        db.add(summary)
    progress = repo.get(db, PlayerLevelProgress, (uid, attempt.level_id))
    previous = progress.best_stars if progress else 0
    old_progress = progress_rows(db, uid, True)
    before = {key for key, item in LEVELS.items() if not requirements(item, progression(db, uid, True), old_progress)}
    if progress is None:
        progress = PlayerLevelProgress(user_id=uid, level_id=attempt.level_id, best_stars=0, best_duration_ms=duration,
                   best_level_version=attempt.level_version, first_completed_at=received_at, revision=0)
        db.add(progress)
    elif progress.best_level_version != attempt.level_version:
        progress.best_duration_ms, progress.best_level_version = duration, attempt.level_version
    else:
        progress.best_duration_ms = min(progress.best_duration_ms, duration)
    awarded_xp = 0
    rewards = POLICY['milestone_xp']
    milestones = [('completion', rewards['completion'])] + [(f'star-{star}', rewards['star'] + (rewards['three_star_bonus'] if star == 3 else 0)) for star in range(1, current+1)]
    if attempt.mode == 'campaign':
        for milestone, amount in milestones:
            if not repo.get(db, ProgressionGrant, (uid, attempt.level_id, milestone)):
                db.add(ProgressionGrant(user_id=uid, level_id=attempt.level_id, milestone=milestone, xp_delta=amount,
                       policy_version=level['reward_policy_version'], attempt_id=rid, granted_at=received_at))
                awarded_xp += amount
    progress.best_stars = max(previous, current)
    if current == 3 and progress.first_three_star_at is None:
        progress.first_three_star_at = received_at
    progress.revision += 1
    summary.xp += awarded_xp
    summary.total_stars += progress.best_stars - previous
    summary.revision += 1
    if attempt.level_id in QUALIFICATIONS and not repo.get(db, PlayerQualification, (uid, attempt.level_id)):
        db.add(PlayerQualification(user_id=uid, requirement_id=attempt.level_id, level_version=attempt.level_version,
               attempt_id=rid, completed_at=received_at))
    newly_cosmetics = grant_cosmetics(db, uid, summary)
    attempt.status, attempt.ended_at = 'completed', received_at
    attempt.revision += 1
    db.flush()
    updated = progression(db, uid, True)
    after_progress = progress_rows(db, uid, True)
    after = {key for key, item in LEVELS.items() if not requirements(item, updated, after_progress)}
    base = f'/api/v1/attempts/{rid}/completion'
    snapshot = {'attempt_id': rid, 'level_id': attempt.level_id, 'level_version': attempt.level_version,
                'duration_ms': duration, 'stars': current, 'previous_best_stars': previous, 'best_stars': progress.best_stars,
                'awarded_stars': progress.best_stars - previous, 'awarded_xp': awarded_xp, 'progression': updated,
                'newly_unlocked_level_ids': sorted(after - before), 'newly_unlocked_cosmetic_ids': newly_cosmetics,
                'reward_policy_version': level['reward_policy_version'],
                'links': {'self': base, 'progression': '/api/v1/me/progression'}}
    db.add(GameCompletion(attempt_id=rid, payload_hash=fingerprint, duration_ms=duration, stars=current, snapshot=snapshot))
    return Resource(snapshot, 201, {'Location': base})


def get_completion(db, uid, rid, **_):
    """丢响应后可读稳定快照，不重新判题或发奖。"""
    owned_attempt(db, uid, rid)
    result = repo.get(db, GameCompletion, rid, False)
    if result is None:
        fail(404, 'completion_not_found', '尚无已确认结果。')
    return Resource(deepcopy(result.snapshot))


def list_progress(db, uid, game_id=None, cursor=None, limit=20, **_):
    """稳定ID游标；少量关卡也遵守有限页大小和恢复链接。"""
    progress = progress_rows(db, uid)
    summary = progression(db, uid)
    attempts = repo.rows(db, GameAttempt, GameAttempt.user_id == uid, GameAttempt.status == 'active',
                         GameAttempt.expires_at > utc_now(), lock=False, limit=10)
    active = {a.level_id: a for a in attempts}
    candidates = [item for key, item in sorted(LEVELS.items()) if (not game_id or item['game_id'] == game_id) and (not cursor or key > cursor)]
    items = []
    for item in candidates[:limit]:
        key = item['level_id']
        row, attempt = progress.get(key), active.get(key)
        reasons = requirements(item, summary, progress)
        items.append({'level_id': key, 'best_stars': row.best_stars if row else 0, 'best_duration_ms': row.best_duration_ms if row else None,
                      'unlocked': not reasons, 'locked_reasons': reasons, 'current_attempt': '/api/v1/attempts/' + attempt.attempt_id if attempt else None})
    next_cursor = items[-1]['level_id'] if len(candidates) > limit else None
    return Resource({'items': items, 'next_cursor': next_cursor, 'links': {'self': '/api/v1/me/level-progress'}})


def appearance(db, uid, **_):
    """缺省外观不写库，ETag 0可用于第一次完整装配。"""
    row = repo.get(db, PlayerAppearance, uid, False)
    return Resource({**(deepcopy(row.configuration) if row else DEFAULT_APPEARANCE), 'revision': row.revision if row else 0},
                    headers={'ETag': etag(row.revision if row else 0)})


def put_appearance(db, uid, data, match, **_):
    """永久所有权校验后整行替换，不允许锁定主题或未知皮肤。"""
    row = repo.get(db, PlayerAppearance, uid)
    precondition(match, row.revision if row else 0)
    if data['theme_id'] != 'default' and not repo.get(db, PlayerCosmetic, (uid, data['theme_id'])):
        fail(403, 'cosmetic_locked', '该主题尚未解锁。')
    if row is None:
        row = PlayerAppearance(user_id=uid, configuration=data, revision=0)
        db.add(row)
    row.configuration, row.revision = data, row.revision + 1
    db.flush()
    return appearance(db, uid)


def cosmetics(db, uid, **_):
    """目录附带可访问素材链接，门槛由服务端返回。"""
    owned = {r.cosmetic_id for r in repo.rows(db, PlayerCosmetic, PlayerCosmetic.user_id == uid, lock=False)} | {'default'}
    return Resource({'items': [{**item, 'owned': item['cosmetic_id'] in owned,
             'locked_reason': None if item['cosmetic_id'] in owned else f"累计{item['required_stars']}星解锁",
             'asset_url': '/journey.css?v=1'} for item in COSMETICS], 'appearance': appearance(db, uid).data})


ACTIONS = {'attempt_create': create_attempt, 'attempt_get': get_attempt, 'attempt_abandon': abandon_attempt,
           'reveal': reveal, 'completion_put': complete_attempt, 'completion_get': get_completion,
           'level_progress': list_progress, 'appearance_get': appearance, 'appearance_put': put_appearance,
           'cosmetics': cosmetics}
READ_ACTIONS = {'attempt_get', 'completion_get', 'level_progress', 'appearance_get', 'cosmetics', 'progression', 'eligibility'}


def dispatch(token, db, action, **kwargs):
    """认证及固定用户锁与全部业务同线程，异常全回滚，成功才返回。"""
    try:
        current = auth_service.current_session(token, db)
        if not current:
            fail(401, 'unauthenticated', '请先登录。')
        uid = current[1].id
        if action not in READ_ACTIONS:
            repo.lock_users(db, [uid])
        if action == 'progression':
            result = Resource(progression(db, uid))
        elif action == 'eligibility':
            result = Resource(eligibility(db, uid))
        else:
            result = ACTIONS[action](db, uid, **kwargs)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
