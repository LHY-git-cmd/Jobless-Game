/**
 * 照明关卡测试：核对 10×10 题盘、灯光、数字约束与唯一解。
 * 唯一解测试使用独立回溯搜索，避免只相信预置答案。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { AKARI_SIZE, AKARI_PUZZLE, akariCell, adjacentCells, createAkari, inspectAkari, lightRay, toggleBulb } from "../../../src/games/akari/rules.js";

const expectedBulbs = [0, 2, 11, 19, 28, 30, 36, 41, 45, 48, 54, 61, 66, 73, 80, 89, 92, 97];

test("10×10 题盘完整，灯光遇黑格停止", () => {
  assert.equal(AKARI_PUZZLE.length, AKARI_SIZE);
  assert.ok(AKARI_PUZZLE.every((row) => row.length === AKARI_SIZE));
  assert.equal(akariCell(1), "#");
  assert.deepEqual(adjacentCells(0), [10, 1]);
  assert.ok(lightRay(2).includes(3));
  assert.ok(!lightRay(2).includes(1));
});

test("数字黑格限制相邻灯泡，互照时不能通关", () => {
  const game = createAkari();
  toggleBulb(game, 2);
  toggleBulb(game, 3);
  assert.deepEqual([...inspectAkari(game).conflictingBulbs].sort((a, b) => a - b), [2, 3]);
  toggleBulb(game, 11);
  toggleBulb(game, 13);
  assert.equal(inspectAkari(game).wrongClues.has(12), true);
  assert.equal(game.complete, false);
});

test("截图中的十九盏灯虽照亮全部格子，缺灯的数字墙格仍须满足", () => {
  const game = createAkari();
  for (const index of [0, 2, 9, 11, 15, 28, 30, 36, 41, 48, 54, 61, 65, 73, 80, 86, 89, 92, 98]) {
    toggleBulb(game, index);
  }
  const inspection = inspectAkari(game);
  assert.equal(inspection.lit.size, 66);
  assert.equal(inspection.conflictingBulbs.size, 0);
  assert.equal(inspection.wrongClues.size, 0);
  assert.deepEqual([...inspection.unmetClues], [56]);
  assert.equal(inspection.clueCounts.get(56), 0);
  assert.equal(game.complete, false);
});

test("正确放置十八盏灯可以通关，黑格不可放灯", () => {
  const game = createAkari();
  assert.equal(toggleBulb(game, 1), false);
  for (const index of expectedBulbs) assert.equal(toggleBulb(game, index), true);
  const inspection = inspectAkari(game);
  assert.equal(inspection.whiteCount, 66);
  assert.equal(inspection.lit.size, inspection.whiteCount);
  assert.equal(inspection.conflictingBulbs.size, 0);
  assert.equal(inspection.unmetClues.size, 0);
  assert.equal(inspection.complete, true);
  assert.equal(game.complete, true);
  assert.equal(toggleBulb(game, 3), false);
});

test("固定 10×10 题盘只有一组合法灯泡位置", () => {
  const white = Array.from({ length: 100 }, (_, index) => index).filter((index) => akariCell(index) === ".");
  const rays = new Map(white.map((index) => [index, new Set(lightRay(index))]));
  const sources = new Map(white.map((index) => [index, white.filter((source) => rays.get(source).has(index))]));
  const clues = Array.from({ length: 100 }, (_, index) => index)
    .filter((index) => /^[0-4]$/.test(akariCell(index)))
    .map((index) => ({ target: Number(akariCell(index)), neighbors: adjacentCells(index).filter((neighbor) => akariCell(neighbor) === ".") }));
  const bulbs = new Set();
  const solutions = new Set();

  // 每步优先满足缺灯的数字黑格，再照亮候选位置最少的白格。
  function search() {
    if (solutions.size > 1) return;
    const canPlace = (index) => !bulbs.has(index) && [...bulbs].every((placed) => !rays.get(placed).has(index))
      && clues.every((clue) => !clue.neighbors.includes(index) ||
        clue.neighbors.filter((neighbor) => bulbs.has(neighbor)).length < clue.target);
    let choices = null;
    for (const clue of clues) {
      const placed = clue.neighbors.filter((neighbor) => bulbs.has(neighbor)).length;
      if (placed >= clue.target) continue;
      const options = clue.neighbors.filter(canPlace);
      if (options.length < clue.target - placed) return;
      if (choices === null || options.length < choices.length) choices = options;
    }
    if (choices === null) {
      const lit = new Set([...bulbs].flatMap((bulb) => [...rays.get(bulb)]));
      for (const cell of white) {
        if (lit.has(cell)) continue;
        const options = sources.get(cell).filter(canPlace);
        if (options.length === 0) return;
        if (choices === null || options.length < choices.length) choices = options;
      }
    }
    if (choices === null) {
      solutions.add([...bulbs].sort((a, b) => a - b).join(","));
      return;
    }
    for (const option of choices) {
      bulbs.add(option);
      search();
      bulbs.delete(option);
      if (solutions.size > 1) return;
    }
  }
  search();
  assert.deepEqual([...solutions], [expectedBulbs.join(",")]);
});
