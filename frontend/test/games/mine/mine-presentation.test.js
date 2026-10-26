/** 作用：验证玩家可见安全格计数、下一关顺序和手机棋盘布局边界。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { remainingSafeCells, nextMineLevel, mineCellSize } from '../../../src/games/mine/presentation.js';

test('排查计数只减服务端已揭安全格，标旗和踩雷不减数', () => {
  const attempt = { puzzle: { rows: 10, cols: 10, mine_count: 10 }, board: { revealed: [{index: 0, value: 0}, {index: 1, value: 1}, {index: 4, value: -1}] } };
  assert.equal(remainingSafeCells(attempt), 88);
  attempt.flags = [2, 3, 5];
  assert.equal(remainingSafeCells(attempt), 88);
  attempt.board.revealed = Array.from({length: 90}, (_,index) => ({index, value: 0}));
  assert.equal(remainingSafeCells(attempt), 0);
  assert.equal(remainingSafeCells(null), 0);
});

test('下一关按难度和棋盘面积排序，不沿用历史追加迁移的顺序', () => {
  const levels = [
    {level_id:'medium-10', difficulty:'medium', rows:10, cols:10, order:5},
    {level_id:'easy-20', difficulty:'easy', rows:15, cols:20, order:4},
    {level_id:'hard-10', difficulty:'hard', rows:10, cols:10, order:6},
    {level_id:'medium-15', difficulty:'medium', rows:12, cols:15, order:8},
    {level_id:'easy-10', difficulty:'easy', rows:10, cols:10, order:2},
    {level_id:'easy-15', difficulty:'easy', rows:12, cols:15, order:3},
    {level_id:'tutorial', difficulty:'tutorial', rows:5, cols:5, order:1},
    {level_id:'hell-20', difficulty:'hell', rows:15, cols:20, order:13},
  ];
  const original = levels.map(item => item.level_id);
  for(const [id,next] of [['tutorial','easy-10'],['easy-10','easy-15'],['easy-20','medium-10'],['medium-15','hard-10']])
    assert.equal(nextMineLevel(levels,id)?.level_id,next);
  assert.equal(nextMineLevel(levels,'hell-20'),null);
  assert.equal(nextMineLevel(levels,'missing'),null);
  assert.deepEqual(levels.map(item => item.level_id),original);
});

test('所有尺寸棋盘按可用宽高完整适配，不设置最小格子限制', () => {
  assert.equal(mineCellSize({rows:10,cols:10,width:308,height:380}),30);
  assert.equal(mineCellSize({rows:10,cols:10,width:400,height:290}),29);
  assert.equal(mineCellSize({rows:10,cols:10,width:900,height:800}),44);
  assert.equal(mineCellSize({rows:5,cols:5,width:300,height:300}),44);
  assert.equal(mineCellSize({rows:12,cols:15,width:300,height:400}),20);
  assert.equal(mineCellSize({rows:10,cols:10,width:200,height:180}),18);
  for (const [rows,cols] of [[5,5],[10,10],[12,15],[15,20],[50,80],[500,800]]) {
    for (const [width,height] of [[270,330],[800,120],[1200,760]]) {
      const size=mineCellSize({rows,cols,width,height});
      assert.ok(size>0&&size<=44);
      assert.ok(size*cols<=width&&size*rows<=height,`${rows}×${cols}超出${width}×${height}`);
    }
  }
});
