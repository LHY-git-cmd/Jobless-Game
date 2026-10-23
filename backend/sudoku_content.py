"""作用：仅在开发机离线构造数独、验证唯一解和记录确定性逻辑分级；生产请求不调用。

python -m backend.sudoku_content --generate 构建新版本（拒绝覆盖）；默认核验已冻结题库。
分级器v2按单候选→隐藏单数→数对/区块→鱼/翼/强链顺序，每次只应用一条推理。
"""
import hashlib
import json
import random
import sys
from functools import lru_cache
from itertools import combinations
from math import isqrt
from pathlib import Path

ROOT = Path(__file__).parent


@lru_cache(maxsize=2)
def topology(size):
    """缓存4或9阶棋盘的行列宫及同伴，所有索引均为零起点。"""
    if size not in (4, 9):
        raise ValueError('只支持4或9阶数独')
    box = isqrt(size)
    groups = [tuple(r*size+c for c in range(size)) for r in range(size)]
    groups += [tuple(r*size+c for r in range(size)) for c in range(size)]
    groups += [tuple((br+r)*size+bc+c for r in range(box) for c in range(box))
               for br in range(0,size,box) for bc in range(0,size,box)]
    peers = [set().union(*(g for g in groups if i in g))-{i} for i in range(size*size)]
    return groups, peers


def checked(values, size):
    """检查输入结构；冲突给定数作为无解处理，非法类型明确拒绝。"""
    groups, _ = topology(size)
    if len(values) != size*size or any(type(v) is not int or not 0 <= v <= size for v in values):
        raise ValueError('数独输入尺寸或数字无效')
    return all(len([values[i] for i in g if values[i]]) == len({values[i] for i in g if values[i]}) for g in groups)


def solutions(values, size=9):
    """独立MRV搜索最多两解；不使用逻辑分级器，既能判多解也能判无解。"""
    if not checked(values,size):
        return []
    _, peers = topology(size)
    digits = set(range(1,size+1)); board = list(values); answers = []

    def search():
        """就地回溯，每条分支退出时恢复原值，候选最少优先。"""
        if len(answers) >= 2:
            return
        pending = [(digits-{board[j] for j in peers[i]},i) for i,v in enumerate(board) if not v]
        if not pending:
            answers.append(board[:]); return
        options,index = min(pending,key=lambda v:len(v[0]))
        for digit in sorted(options):
            board[index] = digit; search()
        board[index] = 0
    search()
    return answers


def next_step(board, candidates, size, tier, coloring=True):
    """从当前候选状态返回第一条合法推理；tier为1～4，不允许猜测分支。"""
    groups, peers = topology(size)
    for i, options in enumerate(candidates):
        if not board[i] and len(options) == 1:
            return {'technique':'single','place':[i,next(iter(options))]}
    if tier < 2:
        return None
    for group in groups:
        for digit in range(1,size+1):
            cells = [i for i in group if digit in candidates[i]]
            if len(cells) == 1:
                return {'technique':'hidden-single','place':[cells[0],digit]}
    if tier < 3:
        return None

    def removal(name, pairs):
        """标准化去重后的候选删除，避免无作用步骤形成求解死循环。"""
        edits = sorted({(i,d) for i,d in pairs if d in candidates[i]})
        return {'technique':name,'remove':[list(v) for v in edits]} if edits else None

    for group in groups:
        empties = [i for i in group if not board[i]]
        for a,b in combinations([i for i in empties if len(candidates[i]) == 2],2):
            if candidates[a] == candidates[b]:
                step = removal('naked-pair',((i,d) for i in empties if i not in (a,b) for d in candidates[a]))
                if step: return step
        positions = {d:{i for i in empties if d in candidates[i]} for d in range(1,size+1)}
        for a,b in combinations(range(1,size+1),2):
            cells = positions[a] | positions[b]
            if positions[a] and positions[b] and len(cells) == 2:
                step = removal('hidden-pair',((i,d) for i in cells for d in candidates[i]-{a,b}))
                if step: return step
    # 宫与行列的交集既处理指向也处理认领；至少两个候选才需要区块排除。
    sets = [set(g) for g in groups]
    for a,group in enumerate(groups):
        for digit in range(1,size+1):
            cells = {i for i in group if digit in candidates[i]}
            if len(cells) < 2: continue
            for b,other in enumerate(sets):
                if a != b and cells <= other:
                    step = removal('locked',((i,digit) for i in other-sets[a]))
                    if step: return step
    if tier < 4:
        return None
    # X-Wing：两行中同一数字恰好落在相同两列，或其转置。
    for transpose in (False,True):
        for digit in range(1,size+1):
            lines = {}
            for r in range(size):
                cells = tuple(c for c in range(size) if digit in candidates[c*size+r if transpose else r*size+c])
                if len(cells) == 2: lines[r] = cells
            for a,b in combinations(lines,2):
                if lines[a] == lines[b]:
                    step = removal('x-wing',((c*size+r if transpose else r*size+c,digit)
                        for r in range(size) if r not in (a,b) for c in lines[a]))
                    if step: return step
    # XY-Wing：枢轴{X,Y}看见{X,Z}和{Y,Z}，共同看见两个翼的格可排除Z。
    bivalue = [i for i in range(size*size) if len(candidates[i]) == 2]
    for pivot in bivalue:
        wings = [i for i in bivalue if i in peers[pivot] and len(candidates[i]&candidates[pivot]) == 1]
        for a,b in combinations(wings,2):
            common = candidates[a]&candidates[b]
            if len(common) == 1 and not common&candidates[pivot] and candidates[a]|candidates[b] == candidates[pivot]|common:
                digit = next(iter(common))
                step = removal('xy-wing',((i,digit) for i in peers[a]&peers[b]-{pivot,a,b}))
                if step: return step
    if not coloring:
        return None
    # 强链二染色：每个单元中仅两处候选互为真假，整条连通链颜色交替。
    for digit in range(1,size+1):
        graph = {}
        for group in groups:
            cells = [i for i in group if digit in candidates[i]]
            if len(cells) == 2:
                a,b = cells; graph.setdefault(a,set()).add(b); graph.setdefault(b,set()).add(a)
        visited = set()
        for root in sorted(graph):
            if root in visited: continue
            colors = {root:0}; queue = [root]
            for a in queue:
                for b in sorted(graph[a]):
                    if b not in colors: colors[b] = 1-colors[a]; queue.append(b)
            visited.update(colors)
            sides = [{i for i,c in colors.items() if c == side} for side in (0,1)]
            for side in sides:
                if any(b in peers[a] for a,b in combinations(side,2)):
                    step = removal('coloring',((i,digit) for i in side))
                    if step: return step
            step = removal('coloring',((i,digit) for i in range(size*size) if i not in colors
                         and peers[i]&sides[0] and peers[i]&sides[1]))
            if step: return step
    return None


def solve(values, size=9, tier=4, coloring=True):
    """返回完整确定性推理记录或停滞中间盘，绝不调用答案搜索。"""
    if not checked(values,size): return {'values':list(values),'trace':[],'solved':False}
    groups, peers = topology(size); board = list(values); digits = set(range(1,size+1))
    candidates = [digits-{board[j] for j in peers[i]} if not v else set() for i,v in enumerate(board)]
    trace = []
    # 每次必定填一格或删除候选，总步数受格数×候选数约束。
    while 0 in board:
        if any(not candidates[i] for i,v in enumerate(board) if not v): break
        step = next_step(board,candidates,size,tier,coloring)
        if step is None: break
        trace.append(step)
        if 'place' in step:
            i,digit = step['place']; board[i] = digit; candidates[i] = set()
            for j in peers[i]: candidates[j].discard(digit)
        else:
            for i,digit in step['remove']: candidates[i].discard(digit)
    return {'values':board,'trace':trace,'solved':0 not in board and checked(board,size)}


def grade(values):
    """以固定技巧集合的最低可解层级分档，高档必须通过低档停滞检查。"""
    for tier,name in enumerate(('easy','medium','hard','hell'),1):
        if solve(values,9,tier)['solved']: return name
    return None


def verify_trace(values, size, trace):
    """重新执行技巧并独立核对唯一答案，拒绝伪造填数、错误排除及缺失步骤。"""
    answers = solutions(values,size)
    if len(answers) != 1: return False
    expected = solve(values,size,4)
    if not expected['solved'] or expected['trace'] != trace: return False
    for step in trace:
        if 'place' in step and answers[0][step['place'][0]] != step['place'][1]: return False
        if any(answers[0][i] == digit for i,digit in step.get('remove',[])): return False
    return True


def canonical(values):
    """把数字重命名及方形的八种旋转/镜像归为同一题，避免题库伪多样性。"""
    size = isqrt(len(values)); variants = []
    board = [values[r*size:(r+1)*size] for r in range(size)]
    for _ in range(4):
        for grid in (board,[row[::-1] for row in board]):
            names = {}; normalized = []
            for row in grid:
                for digit in row:
                    if digit: names.setdefault(digit,len(names)+1)
                    normalized.append(names[digit] if digit else 0)
            variants.append(tuple(normalized))
        board = [list(row) for row in zip(*board[::-1])]
    return min(variants)


def build(seed=20261022):
    """固定种子有界筛选13题；生成进度只报档位统计，不输出答案。"""
    rng = random.Random(seed); found = {k:[] for k in ('easy','medium','hard','hell')}; seen = set(); chain = False
    for attempt in range(12000):
        # 随机合法终盘只作为构造起点；题目最终由独立搜索及分级器验证。
        groups = lambda: [a*3+b for a in rng.sample(range(3),3) for b in rng.sample(range(3),3)]
        rows,cols = groups(),groups(); digits = rng.sample(range(1,10),9)
        board = [digits[(r*3+r//3+c)%9] for r in rows for c in cols]
        order = rng.sample(range(81),81)
        for i in order:
            old = board[i]; board[i] = 0
            if len(solutions(board)) != 1: board[i] = old
        difficulty = grade(board)
        if difficulty is None: continue
        result = solve(board)
        has_chain = any(s['technique'] == 'coloring' for s in result['trace'])
        identity = canonical(board)
        if identity in seen: continue
        if len(found[difficulty]) < 3 or difficulty == 'hell' and not chain and has_chain:
            if len(found[difficulty]) == 3: found[difficulty].pop()
            found[difficulty].append(board); seen.add(identity)
            if difficulty == 'hell' and has_chain: chain = True
            print('Selected',attempt,difficulty,{k:len(v) for k,v in found.items()},'chain',chain,flush=True)
        if all(len(v) == 3 for v in found.values()) and chain: break
    else: raise ValueError('有界构造未满足全部分级门槛，拒绝发布')
    tutorial = [1,0,3,4,3,4,0,2,2,1,4,3,4,3,2,1]
    catalog = []; audit = {}
    entries = [('tutorial',tutorial)] + [(name,board) for name,boards in found.items() for board in boards]
    counts = {}; labels = {'tutorial':'入门教学','easy':'简单','medium':'中等','hard':'困难','hell':'地狱'}
    for order,(difficulty,board) in enumerate(entries,1):
        counts[difficulty] = counts.get(difficulty,0)+1; number = counts[difficulty]
        size = isqrt(len(board)); identity = 'sudoku-v2-'+difficulty+(f'-{number:02}' if size == 9 else '')
        puzzle = {'rows':size,'cols':size,'box_rows':isqrt(size),'box_cols':isqrt(size),'values':board}
        if size == 4: puzzle['tutorial'] = True
        puzzle['checksum'] = hashlib.sha256(json.dumps(puzzle,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        xp,t3 = {'tutorial':(2,0),'easy':(2,300),'medium':(3,600),'hard':(4,1200),'hell':(5,2100)}[difficulty]
        techniques = sorted({s['technique'] for s in solve(board,size)['trace']})
        catalog.append({'level_id':identity,'game_id':'sudoku','level_version':1,'rules_version':2,'reward_policy_version':2,
            'order':order,'name':labels[difficulty]+(f' · 第{number}题' if size == 9 else ''),'difficulty':difficulty,
            'minimum_level':1,'prerequisite_level_id':None,'modes':['campaign'],'max_stars':1 if size == 4 else 3,
            'star_xp':[2] if size == 4 else [xp,xp*2,xp*3],'t3_ms':t3*1000,'t2_ms':t3*2000,
            'clue_count':sum(bool(v) for v in board),'techniques':techniques,'puzzle':puzzle})
        audit[identity] = {'grader_version':2,'seed':seed,'unique':True,'trace':solve(board,size)['trace']}
    return catalog,audit


def main():
    """构建只写未存在的冻结版本；默认验收输出最终统计。"""
    target = ROOT/'content/sudoku-catalog-v2.json'; audit_target = ROOT/'content/sudoku-audit-v2.json'
    if '--generate' in sys.argv:
        if target.exists() or audit_target.exists(): raise ValueError('冻结版本已存在，禁止覆盖')
        levels,audit = build()
        target.write_text(json.dumps({'levels':levels},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        audit_target.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    levels = json.loads(target.read_text(encoding='utf-8'))['levels']
    audit = json.loads(audit_target.read_text(encoding='utf-8'))
    for level in levels:
        assert verify_trace(level['puzzle']['values'],level['puzzle']['rows'],audit[level['level_id']]['trace']),level['level_id']
    print(f'Sudoku content verified: {len(levels)} levels')


if __name__ == '__main__': main()
