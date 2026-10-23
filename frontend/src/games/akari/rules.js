/**
 * 第三关照明规则：灯泡沿行列照射到黑格为止，所有白格须被照亮，
 * 灯泡不能互照，数字黑格要求相邻灯泡数量恰好等于其数字。
 * '.' 是白格，'#' 是普通黑格，'0'–'4' 是数字黑格。
 */

export const AKARI_SIZE = 10;
export const AKARI_PUZZLE = Object.freeze([
  ".#....#0..",
  "#.2.......",
  ".1#00.1...",
  "...#....2.",
  "...0...1..",
  "0##..210.#",
  "#..1....##",
  ".1.....#0.",
  ".....#.#..",
  "#1....1..#",
]);

const cells = AKARI_PUZZLE.join("");

/** 无实例时兼容旧页面与存档；正式关卡使用服务端绑定的矩形地图。 */
function boardOf(state) {
  const level = state?.level || state;
  const map = level?.map || AKARI_PUZZLE;
  return { rows: map.length, cols: map[0].length, cells: map.join('') };
}

/** 返回格子四周相邻的有效位置。 */
export function adjacentCells(index, state) {
  const { rows, cols } = boardOf(state);
  const row = Math.floor(index / cols);
  const col = index % cols;
  return [
    row > 0 ? index - cols : null,
    row < rows - 1 ? index + cols : null,
    col > 0 ? index - 1 : null,
    col < cols - 1 ? index + 1 : null,
  ].filter((next) => next !== null);
}

/** 返回一盏灯照到的全部白格，包含灯所在格。 */
export function lightRay(index, state) {
  const { rows, cols, cells } = boardOf(state);
  if (cells[index] !== ".") return [];
  const row = Math.floor(index / cols);
  const col = index % cols;
  const lit = [index];
  for (const [dr, dc] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
    let nextRow = row + dr;
    let nextCol = col + dc;
    while (nextRow >= 0 && nextRow < rows && nextCol >= 0 && nextCol < cols) {
      const next = nextRow * cols + nextCol;
      if (cells[next] !== ".") break;
      lit.push(next);
      nextRow += dr;
      nextCol += dc;
    }
  }
  return lit;
}

/** 创建或重置第三关。 */
export function createAkari(level) {
  return { bulbs: new Set(), complete: false, ...(level ? { level: { ...level, map: [...level.map] } } : {}) };
}

/** 点击白格放灯，再次点击撤灯；黑格和已通关棋盘不可修改。 */
export function toggleBulb(state, index) {
  const { cells } = boardOf(state);
  if (state.complete || !Number.isInteger(index) || index < 0 || index >= cells.length || cells[index] !== ".") return false;
  if (state.bulbs.has(index)) state.bulbs.delete(index);
  else state.bulbs.add(index);
  state.complete = inspectAkari(state).complete;
  return true;
}

/** 汇总照明、互照和数字黑格状态，供页面显示及通关判定使用。 */
export function inspectAkari(state) {
  const { cells } = boardOf(state);
  const lit = new Set();
  const conflictingBulbs = new Set();
  const wrongClues = new Set();
  const unmetClues = new Set();
  const clueCounts = new Map();

  for (const bulb of state.bulbs) {
    for (const target of lightRay(bulb, state)) {
      lit.add(target);
      if (target !== bulb && state.bulbs.has(target)) {
        conflictingBulbs.add(bulb);
        conflictingBulbs.add(target);
      }
    }
  }

  for (let index = 0; index < cells.length; index += 1) {
    if (!/^[0-4]$/.test(cells[index])) continue;
    const count = adjacentCells(index, state).filter((next) => state.bulbs.has(next)).length;
    clueCounts.set(index, count);
    if (count > Number(cells[index])) wrongClues.add(index);
    if (count !== Number(cells[index])) unmetClues.add(index);
  }

  const whiteCount = [...cells].filter((cell) => cell === ".").length;
  const allLit = lit.size === whiteCount;
  const cluesSatisfied = [...clueCounts].every(([index, count]) => count === Number(cells[index]));
  return {
    lit,
    conflictingBulbs,
    wrongClues,
    unmetClues,
    clueCounts,
    whiteCount,
    complete: allLit && cluesSatisfied && conflictingBulbs.size === 0,
  };
}

/** 只向界面提供格子类型，不暴露题盘解答。 */
export function akariCell(index, state) {
  return boardOf(state).cells[index];
}
