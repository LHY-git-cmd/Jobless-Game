"""纯规则与成长计算；有界终盘校验，不在请求内搜索解。"""


def adjacent(index, rows, cols):
    """返回矩形棋盘的四邻格，避免跨行相邻。"""
    row, col = divmod(index, cols)
    return [r * cols + c for r, c in ((row-1, col), (row+1, col), (row, col-1), (row, col+1))
            if 0 <= r < rows and 0 <= c < cols]


def ray(index, grid):
    """沿白格传播灯光，遇到任意墙立即停止。"""
    rows, cols = len(grid), len(grid[0])
    row, col = divmod(index, cols)
    result = {index}
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        r, c = row + dr, col + dc
        while 0 <= r < rows and 0 <= c < cols and grid[r][c] == '.':
            result.add(r * cols + c)
            r, c = r + dr, c + dc
    return result


def validate_akari(puzzle, bulbs):
    """验证完整覆盖、互照和数字；严格拒绝bool及重复/非法坐标。"""
    grid = puzzle['map']
    cells = ''.join(grid)
    if not isinstance(bulbs, list) or len(bulbs) > len(cells):
        return False
    if any(type(i) is not int or i < 0 or i >= len(cells) or cells[i] != '.' for i in bulbs):
        return False
    placed = set(bulbs)
    if len(placed) != len(bulbs):
        return False
    lit = set()
    for bulb in bulbs:
        targets = ray(bulb, grid)
        if (targets - {bulb}) & placed:
            return False
        lit |= targets
    for index, cell in enumerate(cells):
        if cell == '.' and index not in lit:
            return False
        if cell in '01234' and sum(i in placed for i in adjacent(index, len(grid), len(grid[0]))) != int(cell):
            return False
    return True


def validate_sudoku(puzzle, values):
    """只核对范围、给定数字和行列宫，不在线求解。"""
    size = puzzle.get('rows',9)
    box = 2 if size == 4 else 3
    if size not in (4,9) or puzzle.get('cols',size) != size:
        return False
    if not isinstance(values, list) or len(values) != size*size or any(type(v) is not int or not 1 <= v <= size for v in values):
        return False
    if any(clue and clue != values[i] for i, clue in enumerate(puzzle['values'])):
        return False
    groups = ([r * size + c for c in range(size)] for r in range(size))
    all_groups = list(groups) + [[r * size + c for r in range(size)] for c in range(size)]
    all_groups += [[(br+r)*size+bc+c for r in range(box) for c in range(box)]
                   for br in range(0,size,box) for bc in range(0,size,box)]
    return all({values[i] for i in group} == set(range(1,size+1)) for group in all_groups)


def stars_for(level, duration_ms):
    """按题目自身的有序毫秒门槛计算星级。"""
    if level.get('max_stars') == 1:
        return 1
    # 新照明按通关发星；计时仅供记录，不影响星数或是否允许通关。
    if level.get('game_id') == 'akari' and level.get('rules_version',1) >= 2:
        return 3
    return 3 if duration_ms <= level['t3_ms'] else 2 if duration_ms <= level['t2_ms'] else 1


def reward_milestones(level, current):
    """新扫雷按累计经验拆成逐星增量，旧版本继续使用原有里程碑。"""
    if 'star_xp' in level:
        amounts = [0] + level['star_xp']
        return [(f'star-{star}', amounts[star]-amounts[star-1]) for star in range(1, current+1)]
    from ..common.game_catalog import POLICY
    rewards = POLICY['milestone_xp']
    return [('completion', rewards['completion'])] + [
        (f'star-{star}', rewards['star'] + (rewards['three_star_bonus'] if star == 3 else 0))
        for star in range(1, current+1)]


def elapsed_ms(started_at, received_at):
    """纯整数微秒换算，避免1.001秒浮点乘法误变1000毫秒。"""
    delta = received_at-started_at
    return max(0, delta.days*86400000 + delta.seconds*1000 + delta.microseconds//1000)


def xp_for(previous, current):
    """按最高星里程碑发放经验，不因重复通关或版本更新重奖。"""
    from ..common.game_catalog import POLICY
    reward = POLICY['milestone_xp']
    return (reward['completion'] if previous == 0 and current > 0 else 0) + sum(
        reward['star'] + (reward['three_star_bonus'] if star == 3 else 0)
        for star in range(1, 4) if previous < star <= current)
