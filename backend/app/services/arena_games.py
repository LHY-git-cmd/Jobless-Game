"""三模式竞技题库及隐藏扫雷棋盘；唯一解搜索只在离线工具和测试执行。"""
from copy import deepcopy
import json
from pathlib import Path
import secrets
from .progression_service import mine_neighbors

POOLS=json.loads((Path(__file__).resolve().parents[2]/'content/arena-puzzles-v1.json').read_text(encoding='utf-8'))['pools']


def make_puzzle(game):
    """数独/照明使用离线题；扫雷共享雷区且0号格及邻域无雷，开局一致。"""
    if game!='mine':return deepcopy(secrets.choice(POOLS[game]))
    safe={0,*mine_neighbors(0)}
    for _ in range(16):
        mines=secrets.SystemRandom().sample([i for i in range(100) if i not in safe],10)
        puzzle={'rows':10,'cols':10,'mine_count':10,'mine_indices':sorted(mines),'start_index':0}
        if initial_board(puzzle)['outcome']!='won':break
    else:puzzle={'rows':10,'cols':10,'mine_count':10,'mine_indices':[12,24,36,48,55,67,73,81,89,96],'start_index':0}
    return {'level_version':1,'puzzle':puzzle}


def reveal(board,puzzle,index):
    """纯服务端揭格，双方独立保存revealed；返回是否踩雷/完成，不泄露未揭雷。"""
    mines=set(puzzle['mine_indices']);shown=set(board.get('revealed',[]))
    if index in shown:return board
    pending=[index]
    while pending:
        cell=pending.pop()
        if cell in shown:continue
        shown.add(cell)
        if cell not in mines and not mines.intersection(mine_neighbors(cell)):
            pending.extend(i for i in mine_neighbors(cell) if i not in shown and i not in mines)
    return {'revealed':sorted(shown),'outcome':'lost' if index in mines else 'won' if len(shown)==90 else 'active'}


def initial_board(puzzle):
    """比赛统一安全起点，开局前对外仍不发题。"""
    return reveal({},puzzle,0)


def public_board(board,puzzle):
    """只序列化本人已揭开的数字；雷坐标仅该格确实已踩中才返回。"""
    mines=set(puzzle['mine_indices'])
    return {'outcome':board.get('outcome','active'),'revealed':[{'index':i,'value':-1 if i in mines else len(mines.intersection(mine_neighbors(i)))} for i in board.get('revealed',[])]}
