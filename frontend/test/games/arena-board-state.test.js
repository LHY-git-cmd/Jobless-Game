/** 作用：竞技复用闯关输入规则，验证选格、笔记、撤回和服务端揭格边界。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createArenaBoardState } from '../../src/games/arena-board-state.js';

const sudoku={rows:9,cols:9,values:Array.from({length:81},(_,i)=>i===0?1:0)};
test('数独笔记不进入提交，撤回恢复数值和笔记，给定数不可修改',()=>{
  const board=createArenaBoardState('sudoku',sudoku);
  board.choose(1);board.toggleNotes();board.digit(3);
  assert.equal(board.snapshot().notes[1],4);
  assert.equal(board.payload().values[1],0);
  board.toggleNotes();board.digit(2);
  assert.equal(board.payload().values[1],2);
  board.undo();assert.equal(board.payload().values[1],0);assert.equal(board.snapshot().notes[1],4);
  board.choose(0);board.digit(9);assert.equal(board.payload().values[0],1);
});
test('扫雷点击只选格，标记阻止揭格；揭格必须经服务端回调',()=>{
  const reveals=[];
  const board=createArenaBoardState('mine',{rows:10,cols:10,mine_count:10},{},{revealed:[{index:0,value:0}],outcome:'active'},{onReveal:index=>reveals.push(index)});
  board.choose(12);assert.deepEqual(reveals,[]);
  board.mark();board.reveal();assert.deepEqual(reveals,[]);
  board.mark();board.reveal();assert.deepEqual(reveals,[12]);
  assert.equal(board.mine.revealed.length,1);
  board.choose(0);board.mark();assert.deepEqual(board.snapshot().flags,[]);
});
test('冻结或结束后的棋盘不能更改草稿或重复发起揭格',()=>{
  const board=createArenaBoardState('sudoku',sudoku);
  board.choose(1);board.setDisabled(true);board.digit(9);board.toggleNotes();
  assert.equal(board.payload().values[1],0);assert.equal(board.snapshot().notesMode,false);
});
test('恢复草稿保留笔记和选格，并清理损坏值及越界旗标',()=>{
  const values=Array(81).fill(0);values[0]=9;values[1]=50;
  const notes=Array(81).fill(0);notes[1]=3;
  const board=createArenaBoardState('sudoku',sudoku,{values,notes,selected:1});
  assert.equal(board.payload().values[0],1);assert.equal(board.payload().values[1],0);
  assert.equal(board.snapshot().notes[1],3);assert.equal(board.grid.selected,1);
  const mine=createArenaBoardState('mine',{rows:10,cols:10,mine_count:10},{flags:[-1,12,999]});
  assert.deepEqual(mine.snapshot().flags,[12]);
});
test('已离开成员读取历史结果时，空的权威棋盘不会破坏结算页',()=>{
  const mine=createArenaBoardState('mine',{rows:10,cols:10,mine_count:10},{},{});
  assert.deepEqual(mine.mine.revealed,[]);
  mine.setMine({});assert.deepEqual(mine.mine.revealed,[]);
});
test('刷新恢复数独后仍可撤回最近的实际输入',()=>{
  const first=createArenaBoardState('sudoku',sudoku);first.choose(1);first.digit(2);first.digit(3);
  const restored=createArenaBoardState('sudoku',sudoku,first.snapshot());
  restored.undo();assert.equal(restored.payload().values[1],2);
  restored.undo();assert.equal(restored.payload().values[1],0);
});
