"""开发机离线题库工具：唯一解检查、初级单候选检查及可复现题库构建。

运行 python -m backend.content_check 验证；--generate 仅创建开发中的题库文件，禁止在线调用。
"""

import hashlib
import json
from pathlib import Path
import random
import sys
from .app.services.game_rules import adjacent, ray, validate_akari, validate_sudoku

CONTENT = Path(__file__).parent / 'content' / 'game-catalog-v1.json'


def akari_solutions(grid, limit=2):
    """0/1约束传播搜索，最多取两解用于判唯一；只用于离线构建和测试。"""
    if not grid or not 1 <= len(grid) <= 20 or not 1 <= len(grid[0]) <= 20:
        raise ValueError('非法地图尺寸')
    cols = len(grid[0])
    if any(len(row) != cols or any(c not in '.#01234' for c in row) for row in grid):
        raise ValueError('非法地图字符')
    cells = ''.join(grid)
    white = [i for i, c in enumerate(cells) if c == '.']
    if not white:
        raise ValueError('地图必须包含白格')
    constraints = []
    segments = set()
    for i in white:
        targets = ray(i, grid)
        constraints.append((targets, 1, len(targets)))
        horizontal = frozenset(j for j in targets if j // cols == i // cols)
        vertical = frozenset(j for j in targets if j % cols == i % cols)
        segments.update((horizontal, vertical))
    constraints.extend((s, 0, 1) for s in segments)
    constraints.extend((set(adjacent(i, len(grid), cols)) & set(white), int(c), int(c))
                       for i, c in enumerate(cells) if c in '01234')
    answers = []

    def search(values):
        """收紧等式及覆盖约束，选约束最密集变量分支。"""
        if len(answers) >= limit:
            return
        while True:
            changed = False
            for indices, low, high in constraints:
                total = sum(values.get(i, 0) for i in indices)
                pending = indices - values.keys()
                if total > high or total + len(pending) < low:
                    return
                if pending and (total == high or total + len(pending) == low):
                    value = 0 if total == high else 1
                    values.update((i, value) for i in pending)
                    changed = True
            if not changed:
                break
        pending = set(white) - values.keys()
        if not pending:
            answers.append(sorted(i for i in white if values[i]))
            return
        target = max(sorted(pending), key=lambda i: sum(i in s and len(s - values.keys()) <= 4 for s, _, _ in constraints))
        for value in (1, 0):
            search({**values, target: value})
    search({})
    return answers


def sudoku_candidates(values, index):
    """计算一个空格合法候选，供离线搜索和初级难度校验共用。"""
    r, c = divmod(index, 9)
    used = {values[r*9+j] for j in range(9)} | {values[j*9+c] for j in range(9)}
    used |= {values[(r//3*3+a)*9+c//3*3+b] for a in range(3) for b in range(3)}
    return set(range(1, 10)) - used


def sudoku_solutions(values):
    """离线数独唯一解搜索，最多保留两个终盘。"""
    answers = []
    def search(board):
        """优先候选最少的空格，已完整时用正式规则再次验证。"""
        if len(answers) >= 2:
            return
        empty = [(sudoku_candidates(board, i), i) for i, n in enumerate(board) if not n]
        if not empty:
            if validate_sudoku({'values': values}, board):
                answers.append(board)
            return
        options, index = min(empty, key=lambda pair: len(pair[0]))
        for number in sorted(options):
            updated = board[:]
            updated[index] = number
            search(updated)
    search(values[:])
    return answers


def sudoku_singles(values):
    """只用裸单候选解题，确认资格题不需要猜测或高级技巧。"""
    result = values[:]
    while 0 in result:
        singles = [(i, sudoku_candidates(result, i)) for i, n in enumerate(result) if not n]
        forced = [(i, next(iter(s))) for i, s in singles if len(s) == 1]
        if not forced:
            return None
        for i, value in forced:
            result[i] = value
    return result


def checksum(puzzle):
    """规范化内容摘要用于冻结版本，避免前后端手抄内容。"""
    return hashlib.sha256(json.dumps(puzzle, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def generate():
    """用固定种子在开发机生成唯一题；发布后只能新增版本，不能原位重生成。"""
    if CONTENT.exists():
        raise ValueError('已有版本化题库，禁止覆盖；请创建新版本')
    rng = random.Random(20261021)
    levels, pk = [], []
    names = ['第一束光', '墙后的光', '浅滩信号', '相邻的约定', '数字回廊', '灯塔小径', '交叉光影', '深蓝回声', '群岛之光', '远方灯塔']
    for number, size in enumerate([5, 5, 5, 6, 6, 6, 7, 7, 8, 10, 7, 8, 8], 1):
        for _ in range(5000):
            grid = [['#' if rng.random() < .30 else '.' for _ in range(size)] for _ in range(size)]
            raw = [''.join(row) for row in grid]
            lit, bulbs = set(), set()
            whites = [i for i, c in enumerate(''.join(raw)) if c == '.']
            rng.shuffle(whites)
            for i in whites:
                if i not in lit:
                    bulbs.add(i)
                    lit |= ray(i, raw)
            for i, cell in enumerate(''.join(raw)):
                if cell == '#':
                    grid[i//size][i%size] = str(sum(j in bulbs for j in adjacent(i, size, size)))
            final = [''.join(row) for row in grid]
            if len(akari_solutions(final)) == 1:
                break
        else:
            raise ValueError('未找到唯一题')
        # 删除仍能保证唯一解的部分数字，基础关保留较多线索。
        for i in rng.sample(range(size*size), size*size):
            old = grid[i//size][i%size]
            if old in '01234' and rng.random() < .45:
                grid[i//size][i%size] = '#'
                if len(akari_solutions([''.join(row) for row in grid])) != 1:
                    grid[i//size][i%size] = old
        puzzle = {'rows': size, 'cols': size, 'map': [''.join(row) for row in grid]}
        puzzle['checksum'] = checksum(puzzle)
        item = {'level_id': f'akari-{number:03}' if number <= 10 else f'pk-akari-{number-10:03}',
                'game_id': 'akari', 'level_version': 1, 'rules_version': 1, 'reward_policy_version': 1,
                'order': number, 'name': names[number-1] if number <= 10 else '竞速灯塔',
                'difficulty': 'beginner' if number <= 3 else 'normal',
                'minimum_level': 1 if number <= 3 else 2 if number <= 6 else 3 if number <= 9 else 4,
                'prerequisite_level_id': None if number <= 3 else 'akari-003' if number <= 6 else 'akari-006' if number <= 9 else 'akari-009',
                'modes': ['campaign'] if number <= 10 else ['pk'],
                't3_ms': size*size*4000, 't2_ms': size*size*8000, 'puzzle': puzzle}
        (levels if number <= 10 else pk).append(item)
    sudoku = [int(c) for c in '530070000600195000098000060800060003400803001700020006060000280000419005000080079']
    for game, puzzle in [('mine', {'rows': 10, 'cols': 10, 'mines': 10}), ('sudoku', {'rows': 9, 'cols': 9, 'values': sudoku})]:
        puzzle['checksum'] = checksum(puzzle)
        levels.append({'level_id': f'{game}-beginner-001', 'game_id': game, 'level_version': 1,
                       'rules_version': 1, 'reward_policy_version': 1, 'order': 1,
                       'name': '扫雷初级' if game == 'mine' else '数独初级', 'difficulty': 'beginner',
                       'minimum_level': 1, 'prerequisite_level_id': None, 'modes': ['qualification'], 'puzzle': puzzle})
    CONTENT.parent.mkdir(exist_ok=True)
    CONTENT.write_text(json.dumps({'policy': {'version': 1, 'level_xp': [0, 90, 180, 270, 500, 800],
                       'milestone_xp': {'completion': 30, 'star': 10, 'three_star_bonus': 20},
                       'theme_stars': 10, 'attempt_days': 7, 'history_days': 30, 'tombstone_days': 7,
                       'room_wait_seconds': 300, 'countdown_seconds': 5, 'match_seconds': 600,
                       'reconnect_seconds': 30, 'draw_ms': 1000, 'ticket_seconds': 60},
                       'levels': levels, 'pk_puzzles': pk}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    """命令入口只输出最终统计；失败以异常退出，供CI使用。"""
    if '--generate' in sys.argv:
        generate()
    from .app.common.game_catalog import LEVELS, PK_PUZZLES
    for level in list(LEVELS.values()) + PK_PUZZLES:
        if level['game_id'] == 'akari':
            answers = akari_solutions(level['puzzle']['map'])
            assert len(answers) == 1 and validate_akari(level['puzzle'], answers[0]), level['level_id']
        elif level['game_id'] == 'sudoku':
            if level.get('rules_version',1)>=2:
                from .sudoku_content import solutions,grade
                size=level['puzzle']['rows']
                assert len(solutions(level['puzzle']['values'],size))==1
                if size==9: assert grade(level['puzzle']['values'])==level['difficulty']
            else:
                assert len(sudoku_solutions(level['puzzle']['values'])) == 1
                assert sudoku_singles(level['puzzle']['values'])
    print(f'Content verified: {len(LEVELS)} campaign/qualification levels, {len(PK_PUZZLES)} PK puzzles')


if __name__ == '__main__':
    main()
