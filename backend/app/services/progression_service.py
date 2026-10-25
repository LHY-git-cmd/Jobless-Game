"""正式尝试与成长事务：服务端判题/计时、里程碑幂等、资格和外观权益。"""

from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import json
import secrets
from threading import Lock
from time import monotonic
from uuid import UUID, uuid4
from ..common.config import get_settings
from ..common.game_catalog import LEVELS, POLICY, QUALIFICATIONS, metadata, published_levels
from ..common.exceptions import AppError
from ..common.security import utc_now
from ..models.entities.progression import (GameLevelVersion, PlayerProgression, PlayerLevelProgress,
    GameAttempt, GameCompletion, ProgressionGrant, PlayerQualification, ApiIdempotency)
from ..models.entities.cosmetic import PlayerCosmetic, PlayerAppearance
from ..repositories import progression_repository as repo
from . import auth_service,energy_service
from .game_rules import validate_akari, validate_sudoku, stars_for, elapsed_ms, reward_milestones

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
    """含保留的旧版记录，最多100条覆盖当前有限目录，避免新增16关后丢摘要。"""
    return {r.level_id: r for r in repo.rows(db, PlayerLevelProgress, PlayerLevelProgress.user_id == uid, lock=lock, limit=100)}


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
    """竞技仅由统一账号等级解锁；旧资格凭据保留但不再作为前置。"""
    summary=progression(db,uid,lock)
    return {'eligible': summary['level']>=5, 'minimum_level':5,'level':summary['level'],'required_xp':72,'requirements':[],
            'links': {'self': '/api/v1/me/pk-eligibility'}}


def require_pk(db, uid):
    """创建、加入、入队及实际配对都调用同一个权威资格检查。"""
    value = eligibility(db, uid, True)
    if not value['eligible']:
        fail(403, 'pk_locked', '账号达到5级（72经验）后解锁竞技。', minimum_level=5,level=value['level'],requirements=[])


def level_definition(db, level_id, version=1):
    """尝试绑定数据库已发布的不可变版本，禁止自动回退到新题。"""
    row = repo.get(db, GameLevelVersion, (level_id, version), False)
    if row is None:
        fail(404, 'level_not_found', '关卡或版本不存在。')
    return row.definition


def mine_neighbors(index, rows=10, cols=10):
    """按尝试绑定的行列计算八邻域，默认值兼容旧10×10棋局。"""
    r, c = divmod(index, cols)
    return [a*cols+b for a in range(max(0, r-1), min(rows, r+2))
            for b in range(max(0, c-1), min(cols, c+2)) if (a, b) != (r, c)]


def mine_public(board):
    """只返回已揭格；失败后才公开雷，胜利不需要发隐藏布局。"""
    mines = set(board['mine_indices'])
    visible = [{'index': i, 'value': -1 if i in mines else sum(j in mines for j in mine_neighbors(i, board.get('rows',10), board.get('cols',10)))} for i in board['revealed']]
    return {'revealed': visible, 'outcome': board['outcome'],
            **({'tutorial_step': board['tutorial_step']} if 'tutorial_step' in board else {}),
            **({'mines': sorted(mines)} if board['outcome'] == 'lost' else {})}


def mine_timing(attempt,now=None):
    """活动时长排除暂停区间，旧棋局缺少时钟字段时默认连续计时。"""
    board=attempt.board
    terminal=attempt.ended_at
    if board.get('finished_at'):
        terminal=datetime.fromisoformat(board['finished_at'])
    paused_at=datetime.fromisoformat(board['clock_paused_at']) if board.get('clock_paused_at') else None
    end=terminal or paused_at or now or utc_now()
    elapsed=max(0,elapsed_ms(attempt.started_at,end)-board.get('clock_paused_ms',0))
    return {'elapsed_ms':elapsed,'paused':bool(paused_at and not terminal),
            'paused_ms':board.get('clock_paused_ms',0),'revision':board.get('clock_revision',0)}


def mine_clock(db,uid,rid,data,**_):
    """比较交换阻止旧标签页迟到暂停；同编号重试不重复累计暂停时长。"""
    attempt=owned_attempt(db,uid,rid)
    if attempt.game_id!='mine' and not attempt.board.get('clock_enabled'):
        fail(422,'invalid_clock','此游戏不支持暂停计时。')
    if attempt.status!='active' or attempt.board['outcome']!='active':
        return attempt_resource(db,attempt)
    board=deepcopy(attempt.board)
    if board.get('clock_command')==data['command_id']:
        return attempt_resource(db,attempt)
    if data['revision']!=board.get('clock_revision',0):
        fail(409,'clock_conflict','计时状态已更新，请同步后重试。')
    now=utc_now()
    if data['paused']:
        if not board.get('clock_paused_at'):
            board['clock_paused_at']=now.isoformat()
    elif board.get('clock_paused_at'):
        board['clock_paused_ms']=board.get('clock_paused_ms',0)+elapsed_ms(datetime.fromisoformat(board['clock_paused_at']),now)
        board['clock_paused_at']=None
    # 即使重复“继续”也推进版本，拦截刷新前在途的离页暂停请求。
    board['clock_revision']=board.get('clock_revision',0)+1
    board['clock_command']=data['command_id'];attempt.board=board;attempt.revision+=1
    return attempt_resource(db,attempt)


def attempt_resource(db, attempt, status=200):
    """本人尝试快照包含题目，无标准答案或扫雷种子。"""
    level = level_definition(db, attempt.level_id, attempt.level_version)
    base = '/api/v1/attempts/' + attempt.attempt_id
    data = {'attempt_id': attempt.attempt_id, 'level_id': attempt.level_id, 'level_version': attempt.level_version,
            'game_id': attempt.game_id, 'mode': attempt.mode, 'status': attempt.status, 'revision': attempt.revision,
            'started_at': iso(attempt.started_at), 'expires_at': iso(attempt.expires_at), 'server_now': iso(utc_now()),
            'ended_at': iso(attempt.ended_at) if attempt.ended_at else None,
            'puzzle': deepcopy(level['puzzle']), 'links': {'self': base, 'completion': base + '/completion'}}
    data['energy']=energy_service.snapshot(db,attempt.user_id)
    data['reward']={'timed_stars':not (level.get('game_id')=='akari' and level.get('rules_version',1)>=2 and level.get('reward_policy_version',1)<2),
        't3_ms':level.get('t3_ms',0),'t2_ms':level.get('t2_ms',0),'max_stars':level.get('max_stars',3),
        'first_three_star_double':bool(level.get('first_three_star_double'))}
    if attempt.game_id == 'mine':
        data['board'] = mine_public(attempt.board)
        data['timing'] = mine_timing(attempt)
    elif attempt.board.get('clock_enabled'):
        data['board'] = {k:deepcopy(v) for k,v in attempt.board.items() if k in ('outcome','tutorial_step','tutorial_values','tutorial_notes')}
        data['timing'] = mine_timing(attempt)
    headers = {'ETag': etag(attempt.revision)}
    if status == 201:
        headers['Location'] = base
    return Resource(data, status, headers)


def owned_attempt(db, uid, attempt_id):
    """账号锁先于尝试锁，外人统一404；到期只拒绝，GET不修改。"""
    attempt = repo.get(db, GameAttempt, attempt_id)
    if not attempt or attempt.user_id != uid:
        fail(404, 'attempt_not_found', '尝试不存在。')
    if attempt.status in ('expired', 'tombstone') or (attempt.status == 'active' and attempt.expires_at <= utc_now()):
        fail(410, 'attempt_expired', '本次尝试已过期，请重新开始。')
    return attempt


def create_attempt(db, uid, data, key, _kind='attempts', **_):
    """幂等优先；同关最多一个active，总活跃关卡最多10。"""
    previous, key = idempotent(db, uid, _kind, key, data)
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
    board = {}
    if level['game_id'] == 'mine':
        puzzle = level['puzzle']
        rows, cols, count = puzzle['rows'], puzzle['cols'], puzzle.get('mine_count', 10)
        board = {'rows': rows, 'cols': cols,
                 'mine_indices': [6,18,24] if puzzle.get('tutorial') else secrets.SystemRandom().sample(range(rows*cols), count),
                 'revealed': [], 'requested': [], 'outcome': 'active'}
        if puzzle.get('tutorial'):
            board['tutorial_step'] = 0
    elif level['game_id'] == 'sudoku' and level.get('rules_version',1) >= 2:
        board = {'outcome':'active','clock_enabled':True}
        if level['puzzle'].get('tutorial'):
            board.update(tutorial_step=0,tutorial_values=deepcopy(level['puzzle']['values']),tutorial_notes=[0]*16)
    elif level['game_id'] == 'akari' and level.get('rules_version',1) >= 2:
        # 新照明沿用已存在的权威时钟；旧尝试继续保持原有连续计时语义。
        board = {'outcome':'active','clock_enabled':True}
    attempt = GameAttempt(attempt_id=str(uuid4()), user_id=uid, level_id=level['level_id'], level_version=level['level_version'],
              game_id=level['game_id'], mode=data['mode'], status='active', revision=0, started_at=now,
              expires_at=now + timedelta(days=POLICY['attempt_days']), board=board)
    db.add(attempt)
    db.flush()
    energy_service.spend(db,uid,attempt,level)
    db.flush()
    resource = attempt_resource(db, attempt, 201)
    return remember(db, uid, _kind, key, data, resource, attempt.attempt_id)


def restart_attempt(db,uid,rid,data,key,**_):
    """检查和重开在同一账号事务内；任何不足或创建失败都回滚原局的放弃。"""
    payload={'attempt_id':rid}
    previous,key=idempotent(db,uid,'attempt-restarts',key,payload)
    if previous:return previous
    old=owned_attempt(db,uid,rid)
    # 踩雷失败属于可重玩的终态，保留原失败记录，复用原子创建与体力扣费逻辑。
    if old.status not in ('active','completed','abandoned','expired','lost'):
        fail(409,'attempt_terminal','当前尝试无法重新开始。')
    # 使用当前发布版本，旧成绩继续保留同一关卡身份。
    level=LEVELS.get(old.level_id)
    if level is None:fail(404,'level_not_found','关卡不存在。')
    # 两个标签页同时重开同一旧局时，后到请求只能取得冲突，不能再创建并收费。
    other_active=repo.rows(db,GameAttempt,GameAttempt.user_id==uid,GameAttempt.level_id==old.level_id,
                           GameAttempt.status=='active',GameAttempt.attempt_id!=old.attempt_id,
                           GameAttempt.expires_at>utc_now(),lock=True,limit=1)
    if other_active:fail(409,'restart_conflict','本关已在其他页面重新开始，请刷新后继续。')
    if old.status=='active':
        old.status='abandoned';old.ended_at=utc_now();old.revision+=1;db.flush()
    # 重开内部创建使用独立键空间，不能命中客户端曾用过的普通开局UUID。
    resource=create_attempt(db,uid,{'level_id':old.level_id,'level_version':level['level_version'],'mode':old.mode},key,_kind='restart-created')
    return remember(db,uid,'attempt-restarts',key,payload,resource,resource.data['attempt_id'])


def get_attempt(db, uid, rid, **_):
    """恢复前核验正式凭据，客户端存档不是奖励凭据。"""
    return attempt_resource(db, owned_attempt(db, uid, rid))


def get_energy(db,uid,**_):
    """读取并结算账号自然恢复；dispatch会对该账号加锁后再提交。"""
    return Resource(energy_service.snapshot(db,uid))


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


def reveal(db, uid, rid, index, received_at=None, **_):
    """用户锁串行揭格，重放已处理索引不会再次展开或恢复lost棋局。"""
    attempt = owned_attempt(db, uid, rid)
    level = level_definition(db, attempt.level_id, attempt.level_version)
    puzzle = level['puzzle']
    rows, cols = puzzle['rows'], puzzle['cols']
    if attempt.game_id != 'mine' or not 0 <= index < rows*cols:
        fail(422, 'invalid_cell', '揭格位置不合法。')
    board = deepcopy(attempt.board)
    if index in board['requested'] or index in board['revealed']:
        return attempt_resource(db, attempt)
    if attempt.status != 'active' or board['outcome'] != 'active':
        fail(409, 'attempt_terminal', '本次扫雷已结束。')
    if board.get('clock_paused_at'):
        fail(409,'attempt_paused','游戏已暂停，请继续游戏后再排雷。')
    if puzzle.get('tutorial'):
        step = board['tutorial_step']
        if step in (1,2) or (step == 0 and index != 0) or index in board['mine_indices']:
            fail(409, 'tutorial_step', '请按教学提示完成当前步骤。')
    # 仅新版本启用首击安全；旧尝试的随机布局和规则保持绑定版本。
    if puzzle.get('first_safe') and not board['requested'] and index in board['mine_indices']:
        available = sorted(set(range(rows*cols))-set(board['mine_indices'])-{index})
        board['mine_indices'].remove(index)
        board['mine_indices'].append(secrets.choice(available))
    board['requested'].append(index)
    mines, revealed = set(board['mine_indices']), set(board['revealed'])
    if index in mines:
        revealed.add(index)
        board['outcome'], attempt.status, attempt.ended_at = 'lost', 'lost', received_at or utc_now()
    else:
        pending = [index]
        while pending:
            cell = pending.pop()
            if cell in revealed or cell in mines:
                continue
            revealed.add(cell)
            neighbors = mine_neighbors(cell, rows, cols)
            if not mines.intersection(neighbors):
                pending.extend(n for n in neighbors if n not in revealed)
        if len(revealed) == rows*cols-len(mines):
            board['outcome'] = 'won'
            if level.get('rules_version', 1) >= 2:
                # JSON中只存ISO终盘时刻，结算重试无需依赖客户端或等待时间。
                board['finished_at'] = (received_at or utc_now()).isoformat()
                attempt.ended_at = received_at or utc_now()
        if puzzle.get('tutorial') and board['tutorial_step'] == 0:
            board['tutorial_step'] = 1
    board['revealed'] = sorted(revealed)
    attempt.board = board
    attempt.revision += 1
    result = attempt_resource(db, attempt, 201)
    result.headers['Location'] = f'/api/v1/attempts/{rid}/reveals/{index}'
    return result


def tutorial_action(db, uid, rid, tutorial_action, **_):
    """教学动作按顺序推进；重试已经完成的动作返回相同进度。"""
    attempt = owned_attempt(db, uid, rid)
    action = tutorial_action
    level = level_definition(db, attempt.level_id, attempt.level_version)
    if attempt.game_id!='mine' or not level['puzzle'].get('tutorial') or action not in ('number','flag'):
        fail(422, 'invalid_tutorial_action', '教学动作不合法。')
    target = {'number': 2, 'flag': 3}[action]
    board = deepcopy(attempt.board)
    if board['tutorial_step'] >= target:
        return attempt_resource(db, attempt)
    if attempt.status != 'active' or board['tutorial_step'] != target-1:
        fail(409, 'tutorial_step', '请先完成当前教学步骤。')
    if board.get('clock_paused_at'):
        fail(409,'attempt_paused','游戏已暂停，请继续游戏后再操作。')
    board['tutorial_step'] = target
    attempt.board = board
    attempt.revision += 1
    return attempt_resource(db, attempt)


def grant_cosmetics(db, uid, summary):
    """结算同事务永久授予主题，后续提高门槛不收回已拥有权益。"""
    unlocked = []
    for item in COSMETICS:
        if summary.total_stars >= item['required_stars'] and not repo.get(db, PlayerCosmetic, (uid, item['cosmetic_id'])):
            db.add(PlayerCosmetic(user_id=uid, cosmetic_id=item['cosmetic_id'], unlocked_at=utc_now(), source='stars'))
            unlocked.append(item['cosmetic_id'])
    return unlocked


def sudoku_tutorial(db,uid,rid,tutorial_action,data,**_):
    """逐步核对教学真实输入，重放只读原步骤，不允许跳步或覆盖终盘。"""
    attempt=owned_attempt(db,uid,rid)
    level=level_definition(db,attempt.level_id,attempt.level_version)
    steps=[('row',1,2),('erase',1,0),('note',1,2),('column',6,1),('box',1,2)]
    target=next((i for i,v in enumerate(steps) if v[0]==tutorial_action),None)
    if attempt.game_id!='sudoku' or not level['puzzle'].get('tutorial') or target is None:
        fail(422,'invalid_tutorial_action','教学动作不合法。')
    _,index,value=steps[target]
    if data!={'index':index,'value':value}:
        fail(409,'tutorial_input','请按引导选择目标格并输入对应数字。')
    board=deepcopy(attempt.board)
    if board['tutorial_step']>target:
        return attempt_resource(db,attempt)
    if attempt.status!='active' or board['tutorial_step']!=target:
        fail(409,'tutorial_step','请先完成当前教学步骤。')
    if board.get('clock_paused_at'):
        fail(409,'attempt_paused','游戏已暂停，请继续游戏后再操作。')
    if tutorial_action=='note':
        board['tutorial_notes'][index]=1<<(value-1)
    else:
        board['tutorial_values'][index]=value;board['tutorial_notes'][index]=0
    board['tutorial_step']=target+1;attempt.board=board;attempt.revision+=1
    return attempt_resource(db,attempt)


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
    if attempt.game_id in ('sudoku','akari') and attempt.board.get('clock_enabled'):
        if attempt.board.get('clock_paused_at'):
            fail(409,'attempt_paused','游戏已暂停，请继续游戏后再提交。')
        if attempt.game_id=='sudoku' and level['puzzle'].get('tutorial') and (attempt.board.get('tutorial_step',0)<5 or data.get('values')!=attempt.board['tutorial_values']):
            fail(409,'tutorial_step','请先完成全部教学步骤。')
    valid = (attempt.game_id == 'akari' and set(data) == {'bulbs'} and validate_akari(level['puzzle'], data['bulbs'])) or (
             attempt.game_id == 'sudoku' and set(data) == {'values'} and validate_sudoku(level['puzzle'], data['values'])) or (
             attempt.game_id == 'mine' and not data and attempt.board['outcome'] == 'won')
    if not valid:
        fail(422, 'invalid_completion', '终盘尚未满足全部规则。')
    terminal_at = datetime.fromisoformat(attempt.board['finished_at']) if attempt.game_id == 'mine' and attempt.board.get('finished_at') else received_at
    duration = max(0,elapsed_ms(attempt.started_at, terminal_at)-attempt.board.get('clock_paused_ms',0))
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
    milestones = reward_milestones(level, current)
    if attempt.mode == 'campaign':
        for milestone, amount in milestones:
            if not repo.get(db, ProgressionGrant, (uid, attempt.level_id, milestone)):
                db.add(ProgressionGrant(user_id=uid, level_id=attempt.level_id, milestone=milestone, xp_delta=amount,
                       policy_version=level['reward_policy_version'], attempt_id=rid, granted_at=received_at))
                awarded_xp += amount
    base_awarded_xp=awarded_xp
    first_three_star_bonus=0
    # 只翻倍首次三星当局实际新增经验；旧三星、旧版本和重复提交均不补发。
    if (attempt.mode=='campaign' and current==3 and previous<3 and progress.first_three_star_at is None
            and level.get('first_three_star_double') and base_awarded_xp>0
            and not repo.get(db,ProgressionGrant,(uid,attempt.level_id,'first-three-double'))):
        first_three_star_bonus=base_awarded_xp
        db.add(ProgressionGrant(user_id=uid,level_id=attempt.level_id,milestone='first-three-double',
               xp_delta=first_three_star_bonus,policy_version=level['reward_policy_version'],attempt_id=rid,granted_at=received_at))
        awarded_xp+=first_three_star_bonus
    progress.best_stars = max(previous, current)
    if current == 3 and progress.first_three_star_at is None:
        progress.first_three_star_at = received_at
    progress.revision += 1
    summary.xp += awarded_xp
    summary.total_stars += progress.best_stars - previous
    summary.revision += 1
    qualification_id = 'mine-beginner-001' if attempt.level_id == 'mine-v2-easy-10' else attempt.level_id
    if attempt.level_id=='sudoku-v2-easy-01':
        qualification_id='sudoku-beginner-001'
    if attempt.level_id=='akari-v2-001':
        qualification_id='akari-001'
    if qualification_id in QUALIFICATIONS and not repo.get(db, PlayerQualification, (uid, qualification_id)):
        db.add(PlayerQualification(user_id=uid, requirement_id=qualification_id, level_version=attempt.level_version,
               attempt_id=rid, completed_at=received_at))
    newly_cosmetics = grant_cosmetics(db, uid, summary)
    attempt.status, attempt.ended_at = 'completed', terminal_at
    attempt.revision += 1
    db.flush()
    energy_service.refund(db,uid,attempt)
    updated = progression(db, uid, True)
    after_progress = progress_rows(db, uid, True)
    after = {key for key, item in LEVELS.items() if not requirements(item, updated, after_progress)}
    base = f'/api/v1/attempts/{rid}/completion'
    snapshot = {'attempt_id': rid, 'level_id': attempt.level_id, 'level_version': attempt.level_version,
                'duration_ms': duration, 'stars': current, 'previous_best_stars': previous, 'best_stars': progress.best_stars,
                'awarded_stars': progress.best_stars - previous, 'awarded_xp': awarded_xp, 'progression': updated,
                'base_awarded_xp':base_awarded_xp,'first_three_star_bonus':first_three_star_bonus,
                'newly_unlocked_level_ids': sorted(after - before), 'newly_unlocked_cosmetic_ids': newly_cosmetics,
                'reward_policy_version': level['reward_policy_version'],
                'links': {'self': base, 'progression': '/api/v1/me/progression'}}
    snapshot['energy']=energy_service.snapshot(db,uid)
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
    candidates = [item for item in sorted(published_levels(), key=lambda v: v['level_id']) if (not game_id or item['game_id'] == game_id) and (not cursor or item['level_id'] > cursor)]
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
             'asset_url': '/journey.css'} for item in COSMETICS], 'appearance': appearance(db, uid).data})


ACTIONS = {'energy_get':get_energy,
           'attempt_restart':restart_attempt,'attempt_create': create_attempt, 'attempt_get': get_attempt, 'attempt_abandon': abandon_attempt,
           'reveal': reveal, 'mine_clock': mine_clock, 'tutorial_action': tutorial_action, 'sudoku_tutorial': sudoku_tutorial, 'completion_put': complete_attempt, 'completion_get': get_completion,
           'level_progress': list_progress, 'appearance_get': appearance, 'appearance_put': put_appearance,
           'cosmetics': cosmetics}
READ_ACTIONS = {'completion_get', 'level_progress', 'appearance_get', 'cosmetics', 'progression', 'eligibility'}


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
