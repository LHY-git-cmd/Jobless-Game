/**
 * 数独第二关测试：独立验证题盘合法且唯一解，并检查固定数字与填写规则。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { SUDOKU_PUZZLE, SUDOKU_SOLUTION, createSudoku, selectSudokuCell, setSudokuValue, sudokuConflicts, checkSudoku } from "../src/sudoku.js";

const units = [
  ...Array.from({ length: 9 }, (_, row) => Array.from({ length: 9 }, (_, col) => row * 9 + col)),
  ...Array.from({ length: 9 }, (_, col) => Array.from({ length: 9 }, (_, row) => row * 9 + col)),
  ...Array.from({ length: 9 }, (_, box) => Array.from({ length: 9 }, (_, offset) =>
    (Math.floor(box / 3) * 3 + Math.floor(offset / 3)) * 9 + (box % 3) * 3 + offset % 3)),
];
const peers = Array.from({ length: 81 }, (_, index) =>
  [...new Set(units.filter((unit) => unit.includes(index)).flat())].filter((peer) => peer !== index));

/** 用独立的回溯算法数解，发现第二个解即停止。 */
function countSolutions(board, limit = 2) {
  const candidates = (index) => {
    const taken = new Set(peers[index].map((peer) => board[peer]));
    return [1, 2, 3, 4, 5, 6, 7, 8, 9].filter((digit) => !taken.has(digit));
  };
  const open = board.map((value, index) => value === 0 ? index : -1).filter((index) => index >= 0);
  if (open.length === 0) return 1;
  const index = open.reduce((best, current) => candidates(current).length < candidates(best).length ? current : best);
  let count = 0;
  for (const digit of candidates(index)) {
    board[index] = digit;
    count += countSolutions(board, limit - count);
    if (count >= limit) break;
  }
  board[index] = 0;
  return count;
}

test("题盘有 34 个已给数字，且只有一个合法解", () => {
  assert.equal(SUDOKU_PUZZLE.length, 81);
  assert.equal(SUDOKU_SOLUTION.length, 81);
  assert.equal([...SUDOKU_PUZZLE].filter((digit) => digit !== "0").length, 34);
  for (let index = 0; index < 81; index += 1) {
    if (SUDOKU_PUZZLE[index] !== "0") assert.equal(SUDOKU_PUZZLE[index], SUDOKU_SOLUTION[index]);
  }
  for (const unit of units) {
    assert.equal(new Set(unit.map((index) => SUDOKU_SOLUTION[index])).size, 9);
  }
  assert.equal(countSolutions([...SUDOKU_PUZZLE].map(Number)), 1);
});

test("题盘不能仅靠直接单数填完，包含隐藏单数推理步骤", () => {
  const board = [...SUDOKU_PUZZLE].map(Number);
  const candidates = (index) => {
    const taken = new Set(peers[index].map((peer) => board[peer]));
    return [1, 2, 3, 4, 5, 6, 7, 8, 9].filter((digit) => !taken.has(digit));
  };
  let changed = true;
  while (changed) {
    changed = false;
    for (let index = 0; index < 81; index += 1) {
      if (board[index] !== 0) continue;
      const options = candidates(index);
      if (options.length === 1) {
        board[index] = options[0];
        changed = true;
      }
    }
  }
  assert.ok(board.includes(0));
  const hasHiddenSingle = units.some((unit) => [1, 2, 3, 4, 5, 6, 7, 8, 9].some((digit) =>
    unit.filter((index) => board[index] === 0 && candidates(index).includes(digit)).length === 1));
  assert.equal(hasHiddenSingle, true);
});

test("固定题目数字不能修改，空格能填写和清除", () => {
  const state = createSudoku();
  selectSudokuCell(state, 1);
  assert.equal(setSudokuValue(state, 9), false);
  selectSudokuCell(state, 0);
  assert.equal(setSudokuValue(state, 5), true);
  assert.equal(state.values[0], 5);
  assert.equal(setSudokuValue(state, 0), true);
  assert.equal(state.values[0], 0);
});

test("重复数字会被标记；正确填满后显示完成", () => {
  const state = createSudoku();
  selectSudokuCell(state, 0);
  setSudokuValue(state, 3);
  assert.ok(sudokuConflicts(state).has(0));
  assert.equal(checkSudoku(state).status, "conflict");
  setSudokuValue(state, 0);
  assert.equal(checkSudoku(state).status, "incomplete");
  for (let index = 0; index < 81; index += 1) {
    if (state.givens[index] !== 0) continue;
    selectSudokuCell(state, index);
    setSudokuValue(state, Number(SUDOKU_SOLUTION[index]));
  }
  assert.equal(state.complete, true);
  assert.deepEqual(checkSudoku(state), { status: "complete", blanks: 0 });
});
