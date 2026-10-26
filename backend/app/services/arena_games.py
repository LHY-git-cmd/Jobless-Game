"""竞技复用正式闯关配置；保解变换换题，隐藏扫雷仅在服务端揭开。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import secrets
from .progression_service import mine_neighbors
from ..common.game_catalog import LEVELS, SUDOKU_LEVELS

POOLS=json.loads((Path(__file__).resolve().parents[2]/'content/arena-puzzles-v1.json').read_text(encoding='utf-8'))['pools']


def transformed_map(rows, turn):
    """正方形的八种旋转/镜像保持灯光约束和唯一解，不在线求解。"""
    grid = [list(row) for row in rows]
    if turn >= 4:
        grid = [row[::-1] for row in grid]
    for _ in range(turn % 4):
        grid = [list(row) for row in zip(*grid[::-1])]
    return [''.join(row) for row in grid]


def make_puzzle(game, previous=None):
    """冻结正式配置与版本；previous用于避免紧邻两局初始题面相同。"""
    if game == 'mine':
        level = LEVELS['mine-v2-easy-10']
    elif game == 'akari':
        level = LEVELS['akari-v2-010']
    else:
        level = secrets.choice([item for item in SUDOKU_LEVELS if item['difficulty']=='easy'])
    puzzle = deepcopy(level['puzzle'])
    old = (previous or {}).get('puzzle', {})
    if game == 'mine':
        rows, cols, count = puzzle['rows'], puzzle['cols'], puzzle['mine_count']
        safe = {0, *mine_neighbors(0, rows, cols)}
        candidates = [i for i in range(rows*cols) if i not in safe]
        # 有界重试避免开局已通关、立即重题；双方安全起始格一致。
        for _ in range(16):
            mines = sorted(secrets.SystemRandom().sample(candidates, count))
            puzzle.update(mine_indices=mines, start_index=0)
            if initial_board(puzzle)['outcome'] != 'won' and mines != old.get('mine_indices'):
                break
        else:
            puzzle['mine_indices'] = [12,24,36,48,55,67,73,81,89,96]
            if puzzle['mine_indices'] == old.get('mine_indices'):
                puzzle['mine_indices'] = [13,24,36,48,55,67,73,81,89,96]
    elif game == 'akari':
        turn = secrets.randbelow(8)
        for step in range(8):
            puzzle['map'] = transformed_map(level['puzzle']['map'], (turn+step)%8)
            if puzzle['map'] != old.get('map'):
                break
    else:
        # 数字双射不改变候选推理难度；循环移位兜底防止立即重题。
        digits = secrets.SystemRandom().sample(range(1,10),9)
        for shift in range(9):
            puzzle['values'] = [digits[(v-1+shift)%9] if v else 0 for v in level['puzzle']['values']]
            if puzzle['values'] != old.get('values'):
                break
    puzzle['checksum'] = sha256(json.dumps(puzzle,sort_keys=True).encode()).hexdigest()
    return {'level_id':level['level_id'], 'level_version':level['level_version'], 'puzzle':puzzle}


def reveal(board,puzzle,index):
    """纯服务端揭格，双方独立保存revealed；返回是否踩雷/完成，不泄露未揭雷。"""
    rows,cols=puzzle['rows'],puzzle['cols']
    mines=set(puzzle['mine_indices']);shown=set(board.get('revealed',[]))
    if index in shown:return board
    pending=[index]
    while pending:
        cell=pending.pop()
        if cell in shown:continue
        shown.add(cell)
        if cell not in mines and not mines.intersection(mine_neighbors(cell,rows,cols)):
            pending.extend(i for i in mine_neighbors(cell,rows,cols) if i not in shown and i not in mines)
    return {'revealed':sorted(shown),'outcome':'lost' if index in mines else 'won' if len(shown)==rows*cols-len(mines) else 'active'}


def initial_board(puzzle):
    """比赛统一安全起点，开局前对外仍不发题。"""
    return reveal({},puzzle,puzzle.get('start_index',0))


def public_board(board,puzzle):
    """只序列化本人已揭开的数字；雷坐标仅该格确实已踩中才返回。"""
    mines=set(puzzle['mine_indices'])
    return {'outcome':board.get('outcome','active'),'revealed':[{'index':i,'value':-1 if i in mines else len(mines.intersection(mine_neighbors(i,puzzle['rows'],puzzle['cols'])))} for i in board.get('revealed',[])]}
