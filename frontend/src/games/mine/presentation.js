/** 扫雷展示规则：未揭安全格、按难度/规格前进及小棋盘适配，不参与服务端奖励计算。 */
const DIFFICULTIES = ['tutorial', 'easy', 'medium', 'hard', 'hell'];

/** 只减去服务端确认揭开的安全格；旗标和爆炸雷格不计入排查进度。 */
export function remainingSafeCells(attempt) {
  if (!attempt) return 0;
  const { rows, cols, mine_count } = attempt.puzzle;
  const revealed = attempt.board.revealed.filter(cell => cell.value >= 0).length;
  return Math.max(0, rows * cols - mine_count - revealed);
}

/** 历史目录的order包含追加规格，按难度及面积重新排序；不修改原目录。 */
export function nextMineLevel(levels, currentId) {
  const ordered = [...levels].sort((a, b) => DIFFICULTIES.indexOf(a.difficulty) - DIFFICULTIES.indexOf(b.difficulty)
    || a.rows * a.cols - b.rows * b.cols || a.cols - b.cols);
  const index = ordered.findIndex(level => level.level_id === currentId);
  return index < 0 ? null : ordered[index + 1] ?? null;
}

/** width/height是减去边框后的可用棋盘区域；小盘最小24px，大盘保持44px滚动。 */
export function mineCellSize({ rows, cols, width, height }) {
  if (rows > 10 || cols > 10) return 44;
  return Math.max(24, Math.min(44, Math.floor(width / cols), Math.floor(height / rows)));
}
