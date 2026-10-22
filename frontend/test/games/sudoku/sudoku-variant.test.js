/** 作用：先验证可变尺寸数独、给定数保护及不依赖内置答案的完成判断。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createSudoku, selectSudokuCell, setSudokuValue, toggleSudokuNote, sudokuConflicts } from '../../../src/games/sudoku/rules.js';

test('4×4 uses its own givens, bounds, candidates and boxes',()=>{
  const state=createSudoku({rows:4,cols:4,box_rows:2,box_cols:2,values:[1,0,0,4,0,4,1,0,0,1,4,0,4,0,0,1]});
  assert.equal(state.values.length,16);
  assert.equal(selectSudokuCell(state,16),false);
  selectSudokuCell(state,0); assert.equal(setSudokuValue(state,2),false);
  selectSudokuCell(state,1); assert.equal(toggleSudokuNote(state,5),false);
  toggleSudokuNote(state,2); assert.equal(state.notes[1],2);
  setSudokuValue(state,1); assert.ok(sudokuConflicts(state).has(0));
  setSudokuValue(state,2); assert.equal(state.notes[1],0);
});

test('completion validates the supplied puzzle without a bundled solution',()=>{
  const answer=[1,2,3,4,3,4,1,2,2,1,4,3,4,3,2,1];
  const state=createSudoku({rows:4,cols:4,values:answer.map((v,i)=>i===15?0:v)});
  selectSudokuCell(state,15); setSudokuValue(state,2); assert.equal(state.complete,false);
  setSudokuValue(state,1); assert.equal(state.complete,true);
});
