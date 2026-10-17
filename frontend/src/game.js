/**
 * 纯扫雷规则模块：创建 10×10 棋盘，处理标记、排雷和胜负判断。
 * 不依赖页面元素，方便在浏览器和自动化测试中复用。
 */

export const GAME_CONFIG = Object.freeze({ rows: 10, cols: 10, mineCount: 10 });

/** 返回指定格子的全部有效相邻位置。 */
export function neighbors(index, rows, cols) {
  const row = Math.floor(index / cols);
  const col = index % cols;
  const result = [];
  for (let dr = -1; dr <= 1; dr += 1) {
    for (let dc = -1; dc <= 1; dc += 1) {
      if (dr === 0 && dc === 0) continue;
      const nextRow = row + dr;
      const nextCol = col + dc;
      if (nextRow >= 0 && nextRow < rows && nextCol >= 0 && nextCol < cols) {
        result.push(nextRow * cols + nextCol);
      }
    }
  }
  return result;
}

/** 创建随机棋盘；首次排雷不保底。 */
export function createGame(random = Math.random) {
  const level = GAME_CONFIG;

  const cells = Array.from({ length: level.rows * level.cols }, () => ({
    mine: false,
    adjacent: 0,
    revealed: false,
    flagged: false,
  }));

  // 部分 Fisher-Yates 洗牌确保雷的位置互不重复。
  const positions = cells.map((_, index) => index);
  for (let i = 0; i < level.mineCount; i += 1) {
    const j = i + Math.floor(random() * (positions.length - i));
    [positions[i], positions[j]] = [positions[j], positions[i]];
    cells[positions[i]].mine = true;
  }

  cells.forEach((cell, index) => {
    if (!cell.mine) {
      cell.adjacent = neighbors(index, level.rows, level.cols)
        .filter((nearby) => cells[nearby].mine).length;
    }
  });

  return {
    level,
    cells,
    selected: null,
    flaggedCount: 0,
    revealedCount: 0,
    status: "ready",
    startedAt: null,
    endedAt: null,
    explodedAt: null,
  };
}

/** 选择尚未揭开的格子；选择本身不触发扫雷。 */
export function selectCell(game, index) {
  if (game.status === "won" || game.status === "lost") return false;
  if (!Number.isInteger(index) || index < 0 || index >= game.cells.length) return false;
  if (game.cells[index].revealed) return false;
  game.selected = index;
  return true;
}

/** 在当前选中的格子上添加或取消标记。 */
export function toggleFlag(game) {
  const index = game.selected;
  if (index === null || game.status === "won" || game.status === "lost") return false;
  const cell = game.cells[index];
  if (cell.revealed) return false;
  cell.flagged = !cell.flagged;
  game.flaggedCount += cell.flagged ? 1 : -1;
  return true;
}

/** 揭开安全格；遇到空白格时用队列连续展开邻近安全区域。 */
export function revealSelected(game, now = Date.now()) {
  const index = game.selected;
  if (index === null || game.status === "won" || game.status === "lost") return "ignored";
  const selectedCell = game.cells[index];
  if (selectedCell.revealed || selectedCell.flagged) return "ignored";
  if (game.startedAt === null) game.startedAt = now;
  game.status = "playing";

  if (selectedCell.mine) {
    selectedCell.revealed = true;
    game.explodedAt = index;
    game.endedAt = now;
    game.status = "lost";
    game.selected = null;
    return "lost";
  }

  const queue = [index];
  let head = 0;
  while (head < queue.length) {
    const current = queue[head++];
    const cell = game.cells[current];
    if (cell.revealed || cell.flagged || cell.mine) continue;
    cell.revealed = true;
    game.revealedCount += 1;
    if (cell.adjacent === 0) {
      for (const nearby of neighbors(current, game.level.rows, game.level.cols)) {
        if (!game.cells[nearby].revealed && !game.cells[nearby].flagged) queue.push(nearby);
      }
    }
  }

  game.selected = null;
  if (game.revealedCount === game.cells.length - game.level.mineCount) {
    game.status = "won";
    game.endedAt = now;
    return "won";
  }
  return "revealed";
}

/** 返回计时秒数；结束后保持最终用时。 */
export function elapsedSeconds(game, now = Date.now()) {
  if (game.startedAt === null) return 0;
  return Math.floor((Math.max(game.startedAt, game.endedAt ?? now) - game.startedAt) / 1000);
}
