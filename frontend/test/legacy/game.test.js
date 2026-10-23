/**
 * 单关扫雷规则测试：验证 10×10 布雷、标记保护、踩雷失败及安全格通关。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { createGame, elapsedSeconds, neighbors, revealSelected, selectCell, toggleFlag } from "../../src/legacy/mine/rules.js";

test("棋盘为 10×10，准确放置 10 颗雷", () => {
  const game = createGame(() => 0);
  assert.equal(game.cells.length, 100);
  assert.equal(game.cells.filter((cell) => cell.mine).length, 10);
  assert.equal(game.cells[10].adjacent, 2);
  assert.deepEqual(neighbors(0, 10, 10), [1, 10, 11]);
});

test("首次排雷踩中地雷会失败", () => {
  const game = createGame(() => 0);
  assert.equal(selectCell(game, 0), true);
  assert.equal(revealSelected(game, 1000), "lost");
  assert.equal(game.status, "lost");
  assert.equal(selectCell(game, 10), false);
  assert.equal(elapsedSeconds(game, 5000), 0);
});

test("已标记格子无法排雷，取消标记后可以排雷", () => {
  const game = createGame(() => 0);
  selectCell(game, 11);
  assert.equal(toggleFlag(game), true);
  assert.equal(revealSelected(game, 1000), "ignored");
  assert.equal(game.startedAt, null);
  assert.equal(toggleFlag(game), true);
  assert.equal(revealSelected(game, 1000), "revealed");
  assert.equal(game.cells[11].revealed, true);
});

test("排开全部安全格后通关，不要求标记地雷", () => {
  const game = createGame(() => 0);
  for (let index = 0; index < game.cells.length; index += 1) {
    if (game.cells[index].mine || game.cells[index].revealed) continue;
    selectCell(game, index);
    revealSelected(game, 1000 + index * 100);
  }
  assert.equal(game.status, "won");
  assert.equal(game.revealedCount, 90);
  assert.equal(game.flaggedCount, 0);
});
