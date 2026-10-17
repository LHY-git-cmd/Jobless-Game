/**
 * 第二关数独规则：固定题盘、填写数字、清除数字、检查重复和完成状态。
 * 题盘有唯一解；数字 0 表示待填写的空格。
 */

export const SUDOKU_PUZZLE = "030070010072005300008342500809001423000800000013004006061000080087000035340000170";
export const SUDOKU_SOLUTION = "534678912672195348198342567859761423426853791713924856961537284287419635345286179";

/** 创建新的一局数独；题目数字与玩家填写数字分开保存。 */
export function createSudoku() {
  const givens = [...SUDOKU_PUZZLE].map(Number);
  return {
    givens,
    values: [...givens],
    selected: null,
    complete: false,
  };
}

/** 选择一个格子；题目数字也可以选中查看所在行列，但不能修改。 */
export function selectSudokuCell(state, index) {
  if (!Number.isInteger(index) || index < 0 || index >= 81) return false;
  state.selected = index;
  return true;
}

/** 在选中空格填写 1–9，或用 0 清除；固定题目数字不能修改。 */
export function setSudokuValue(state, value) {
  const index = state.selected;
  if (index === null || state.complete || state.givens[index] !== 0) return false;
  if (!Number.isInteger(value) || value < 0 || value > 9) return false;
  state.values[index] = value;
  state.complete = state.values.every((entry, position) => entry === Number(SUDOKU_SOLUTION[position]));
  return true;
}

/** 找出行、列或九宫格中出现重复数字的格子。 */
export function sudokuConflicts(state) {
  const conflicts = new Set();
  const groups = [];
  for (let row = 0; row < 9; row += 1) {
    groups.push(Array.from({ length: 9 }, (_, col) => row * 9 + col));
  }
  for (let col = 0; col < 9; col += 1) {
    groups.push(Array.from({ length: 9 }, (_, row) => row * 9 + col));
  }
  for (let boxRow = 0; boxRow < 9; boxRow += 3) {
    for (let boxCol = 0; boxCol < 9; boxCol += 3) {
      groups.push(Array.from({ length: 9 }, (_, offset) =>
        (boxRow + Math.floor(offset / 3)) * 9 + boxCol + offset % 3));
    }
  }

  for (const group of groups) {
    const seen = new Map();
    for (const index of group) {
      const value = state.values[index];
      if (value === 0) continue;
      if (seen.has(value)) {
        conflicts.add(index);
        conflicts.add(seen.get(value));
      } else {
        seen.set(value, index);
      }
    }
  }
  return conflicts;
}

/** 返回检查结果，供页面生成不泄露答案的反馈。 */
export function checkSudoku(state) {
  if (state.complete) return { status: "complete", blanks: 0 };
  const conflicts = sudokuConflicts(state);
  if (conflicts.size > 0) return { status: "conflict", blanks: state.values.filter((value) => value === 0).length };
  return { status: "incomplete", blanks: state.values.filter((value) => value === 0).length };
}
