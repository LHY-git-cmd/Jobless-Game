"""作用：开发机离线生成/审核照明、数独各20道竞技独立原题，线上不调用。

python -m backend.arena_content --generate 只创建未发布v2文件；默认重新审核已冻结题库。
固定种子保证可复现；墙体/数字规范化排除旋转镜像复制，独立验证唯一解与同档难度。
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import random
from .akari_content import candidate, solve as akari_solve
from .sudoku_content import canonical, grade, solve as sudoku_solve, solutions, verify_trace
from .content_check import akari_solutions, checksum
from .app.common.game_catalog import LEVELS, SUDOKU_LEVELS

ROOT=Path(__file__).resolve().parent
SEED=20261027022
POOL_SIZE=20
HISTORY_LIMIT=4


def square_variants(grid):
    """列出八种方向，仅用于离线等价题检查，不充当新增原题。"""
    board=[list(row) for row in grid]
    for _ in range(4):
        yield tuple(''.join(row) for row in board)
        yield tuple(''.join(row[::-1]) for row in board)
        board=[list(row) for row in zip(*board[::-1])]


def akari_identity(grid):
    """墙体拓扑在八种方向下规范化，数字不同但同墙图也不算独立原题。"""
    walls=[''.join('.' if cell=='.' else '#' for cell in row) for row in grid]
    return min(square_variants(walls))


def sudoku_layout_signature(values):
    """行/列/宫线索数量不变量不同，可证明并非合法行列重排或数字重命名复制题。"""
    rows=tuple(sorted(sum(bool(values[r*9+c]) for c in range(9)) for r in range(9)))
    cols=tuple(sorted(sum(bool(values[r*9+c]) for r in range(9)) for c in range(9)))
    boxes=tuple(sorted(sum(bool(values[(br+r)*9+bc+c]) for r in range(3) for c in range(3))
                       for br in range(0,9,3) for bc in range(0,9,3)))
    return tuple(sorted((rows,cols))),boxes


def entry(game,number,puzzle,source):
    """生成稳定原题ID与配置来源，不将解答和审计轨迹放入题面。"""
    puzzle=deepcopy(puzzle);puzzle.pop('checksum',None);puzzle['checksum']=checksum(puzzle)
    return {'base_puzzle_id':f'arena-{game}-v2-{number:03}', 'level_id':source['level_id'],
            'level_version':source['level_version'], 'puzzle':puzzle}


def build_akari():
    """筛选第10关相同tier=1、29～49步的10×10独立墙图，最多50000次构造。"""
    source=LEVELS['akari-v2-010'];rng=random.Random(SEED)
    items=[entry('akari',1,source['puzzle'],source)]
    audit={items[0]['base_puzzle_id']:{'source':'campaign','seed':SEED,'unique':True,'logic':akari_solve(source['puzzle']['map'],1)}}
    seen={akari_identity(source['puzzle']['map'])}
    for attempt in range(50000):
        grid=candidate(rng,10,10)
        if not grid or any('.' not in row for row in grid) or any(all(row[col]!='.' for row in grid) for col in range(10)):
            continue
        identity=akari_identity(grid)
        if identity in seen:
            continue
        logical=akari_solve(grid,1)
        if not logical['solved'] or logical['tier']!=1 or not 29<=len(logical['trace'])<=49:
            continue
        answers=akari_solutions(grid)
        if len(answers)!=1 or answers[0]!=logical['bulbs']:
            continue
        item=entry('akari',len(items)+1,{'rows':10,'cols':10,'map':grid},source)
        items.append(item);seen.add(identity)
        audit[item['base_puzzle_id']]={'source':'generated','seed':SEED,'attempt':attempt,'unique':True,'logic':logical}
        print(f'Akari selected: {len(items)}/{POOL_SIZE}; attempt={attempt}; steps={len(logical["trace"])}',flush=True)
        if len(items)==POOL_SIZE:
            return items,audit
    raise ValueError('有界构造未得到20道同难度照明原题，不发布不合格或重复题')


def build_sudoku():
    """保留3道既有简单原题，独立构造25给定数、唯一解且简单的9×9新题。"""
    sources=[item for item in SUDOKU_LEVELS if item['difficulty']=='easy']
    rng=random.Random(SEED+1);items=[];audit={};seen=set()
    for source in sources:
        item=entry('sudoku',len(items)+1,source['puzzle'],source);items.append(item)
        seen.add(canonical(source['puzzle']['values']))
        audit[item['base_puzzle_id']]={'source':'campaign','seed':SEED+1,'unique':True,'logic':sudoku_solve(item['puzzle']['values'])}
    for attempt in range(12000):
        # 随机合法终盘只作为构造起点；每次独立挖空并审核，不能直接变换旧题充数。
        rows=[a*3+b for a in rng.sample(range(3),3) for b in rng.sample(range(3),3)]
        cols=[a*3+b for a in rng.sample(range(3),3) for b in rng.sample(range(3),3)]
        digits=rng.sample(range(1,10),9)
        board=[digits[(r*3+r//3+c)%9] for r in rows for c in cols]
        count=81
        for index in rng.sample(range(81),81):
            old=board[index];board[index]=0
            if len(solutions(board))!=1:
                board[index]=old
            else:
                count-=1
            if count==25:
                break
        identity=canonical(board)
        if count!=25 or identity in seen or grade(board)!='easy':
            continue
        puzzle={'rows':9,'cols':9,'box_rows':3,'box_cols':3,'values':board}
        item=entry('sudoku',len(items)+1,puzzle,sources[0]);items.append(item);seen.add(identity)
        audit[item['base_puzzle_id']]={'source':'generated','seed':SEED+1,'attempt':attempt,'unique':True,'logic':sudoku_solve(board)}
        print(f'Sudoku selected: {len(items)}/{POOL_SIZE}; attempt={attempt}',flush=True)
        if len(items)==POOL_SIZE:
            return items,audit
    raise ValueError('有界构造未得到20道简单数独原题，不发布其他难度题目')


def verify(content,audit):
    """离线独立求解与重放审计，校验每种20道、原题独立、唯一解及固定难度。"""
    assert content['version']==2 and content['history_limit']==HISTORY_LIMIT
    for game,items in content['pools'].items():
        assert len(items)==POOL_SIZE
        identities=set();ids=set();layouts=set()
        for item in items:
            puzzle=item['puzzle'];record=audit['puzzles'][item['base_puzzle_id']]
            assert item['base_puzzle_id'] not in ids;ids.add(item['base_puzzle_id'])
            assert puzzle['checksum']==checksum({k:v for k,v in puzzle.items() if k!='checksum'})
            if game=='akari':
                assert puzzle['rows']==puzzle['cols']==10
                identity=akari_identity(puzzle['map']);answers=akari_solutions(puzzle['map']);logical=akari_solve(puzzle['map'],1)
                assert len(answers)==1 and logical['solved'] and logical['tier']==1 and 29<=len(logical['trace'])<=49
                assert logical['bulbs']==answers[0] and logical==record['logic']
            else:
                assert puzzle['rows']==puzzle['cols']==9
                identity=canonical(puzzle['values'])
                layout=sudoku_layout_signature(puzzle['values'])
                assert layout not in layouts;layouts.add(layout)
                assert sum(bool(v) for v in puzzle['values'])==25 and grade(puzzle['values'])=='easy'
                assert verify_trace(puzzle['values'],9,record['logic']['trace'])
            assert identity not in identities;identities.add(identity)


def main():
    """生成只写新文件，完整构造审核成功后才落盘；已发布版本拒绝覆盖。"""
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--generate',action='store_true');args=parser.parse_args()
    target=ROOT/'content/arena-puzzles-v2.json';audit_target=ROOT/'content/arena-audit-v2.json'
    if args.generate:
        if target.exists() or audit_target.exists():
            raise ValueError('冻结版本已存在，禁止覆盖；修改题目请新增版本')
        akari,akari_audit=build_akari();sudoku,sudoku_audit=build_sudoku()
        content={'version':2,'history_limit':HISTORY_LIMIT,'pools':{'akari':akari,'sudoku':sudoku}}
        audit={'version':2,'akari_baseline':'akari-v2-010','akari_tier':1,'akari_steps':[29,49],
               'sudoku_difficulty':'easy','sudoku_clue_count':25,'puzzles':{**akari_audit,**sudoku_audit}}
        verify(content,audit)
        target.write_text(json.dumps(content,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        audit_target.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    else:
        verify(json.loads(target.read_text(encoding='utf-8')),json.loads(audit_target.read_text(encoding='utf-8')))
    print('PASS: 20 Akari + 20 Sudoku originals; unique solutions, independent originals and difficulty audited')


if __name__=='__main__':main()
