/** 本地棋局存档：按账号保存三关状态与绝对计时起点，关闭浏览器后仍可续玩。 */
import { normalizeSudokuNotes } from "../../games/sudoku/rules.js";

const PREFIX = "jobless-progress-v1:";

/** 按账号读取并校验存档；灯泡数组恢复为规则模块使用的 Set。 */
export function loadProgress(storage, userId) {
  if (userId == null) return null;
  try {
    const value = JSON.parse(storage?.getItem(PREFIX + userId) ?? "null");
    if (!value || value.version !== 1 || String(value.userId) !== String(userId)) return null;
    const { currentIndex: index, session, game, akari, sudoku, challenge } = value;
    if (![0, 1, 2].includes(index) || !challenge?.state?.run_id || !challenge.startId ||
        challenge.state.levels?.length !== 3 || !Array.isArray(challenge.pending) ||
        session?.levels?.length !== 3 || !session.levels.every(level =>
          (level.startedAt === null || Number.isFinite(level.startedAt)) &&
          (level.seconds === null || (Number.isInteger(level.seconds) && level.seconds >= 0)))) return null;
    const completedWithoutBoard = challenge.state.levels[index]?.seconds != null && ![game, akari, sudoku][index];
    if (!completedWithoutBoard && ![game, akari, sudoku][index]) return null;
    if (game && (game.cells?.length !== 100 ||
        !["ready", "playing", "won", "lost"].includes(game.status) ||
        game.level?.rows !== 10 || game.level?.cols !== 10)) return null;
    if (akari && (!Array.isArray(akari.bulbs) ||
        !akari.bulbs.every(cell => Number.isInteger(cell) && cell >= 0 && cell < 100))) return null;
    if (sudoku && (sudoku.values?.length !== 81 || sudoku.givens?.length !== 81 ||
        !sudoku.values.every(digit => Number.isInteger(digit) && digit >= 0 && digit <= 9))) return null;
    if (!Array.isArray(value.dialogs)) return null;
    if (akari) akari.bulbs = new Set(akari.bulbs);
    if (sudoku) normalizeSudokuNotes(sudoku);
    return value;
  } catch { return null; }
}

/** 同步保存操作结果；存储被禁用或已满时由调用方显示提示，游戏仍可继续。 */
export function saveProgress(storage, userId, value) {
  if (!storage || userId == null) return false;
  try {
    storage.setItem(PREFIX + userId, JSON.stringify({ ...value, version: 1, userId },
      (_key, entry) => entry instanceof Set ? [...entry] : entry));
    return true;
  } catch { return false; }
}

/** 只删除指定账号的本轮存档，其他账号与历史通关记录不受影响。 */
export function clearProgress(storage, userId) {
  try { storage?.removeItem(PREFIX + userId); } catch { /* 存储不可用时无需阻断返回首页。 */ }
}
