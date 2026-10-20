/** 临时开发验收：仅解当前关卡；生产开关关闭，不参与正常规则实现，后续可删除。 */
import { SUDOKU_SOLUTION } from "./sudoku.js";
import { inspectAkari } from "./akari.js";

/** 只将当前棋盘变为合法终盘；通关、计时和提交继续走 main 的正常处理。 */
export function solveCurrentLevel(index, state) {
  if (!state) throw new Error("请先开始当前关。");
  if (index === 0) {
    if (state.status === "lost") throw new Error("本局已失败，请先重新开始。");
    for (const cell of state.cells) { cell.revealed = !cell.mine; cell.flagged = false; }
    state.revealedCount = state.cells.filter((cell) => !cell.mine).length;
    state.flaggedCount = 0;
    state.status = "won";
    state.endedAt = Date.now();
  } else if (index === 1) {
    state.bulbs = new Set([0, 2, 11, 19, 28, 30, 36, 41, 45, 48, 54, 61, 66, 73, 80, 89, 92, 97]);
    state.complete = inspectAkari(state).complete;
    if (!state.complete) throw new Error("验收灯位与当前题盘不匹配。");
  } else if (index === 2) {
    state.values = [...SUDOKU_SOLUTION].map(Number);
    state.complete = true;
  }
}
