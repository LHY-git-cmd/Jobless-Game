/** 扫雷多关卡契约：配置校验、独立续玩、计时冻结和账号/旧存档隔离。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createGame, selectCell, revealSelected, toggleFlag } from '../src/game.js';
import { MINE_LEVELS } from '../src/games/mine/levels.js';
import { createMinePracticeStore } from '../src/games/mine/practice-store.js';

/** 内存存储替代浏览器，保留与 localStorage 相同的序列化边界。 */
function memory() {
  const values = new Map();
  return { values, getItem:key=>values.get(key)??null, setItem:(key,value)=>values.set(key,value) };
}

test('关卡配置准确布雷、计算线索和胜负，原有默认调用保持10颗雷', () => {
  assert.equal(createGame(()=>0).level.mineCount,10);
  for (const level of MINE_LEVELS) {
    const game=createGame(()=>0,level);
    assert.equal(game.cells.length,100);
    assert.equal(game.cells.filter(cell=>cell.mine).length,level.mineCount);
    for(let index=0;index<game.cells.length;index++) {
      if(game.cells[index].mine||game.cells[index].revealed)continue;
      selectCell(game,index);revealSelected(game,1000+index);
    }
    assert.equal(game.status,'won');
    assert.equal(game.revealedCount,100-level.mineCount);
  }
  assert.throws(()=>createGame(Math.random,{rows:10,cols:10,mineCount:100}),/配置/);
  assert.throws(()=>createGame(Math.random,{rows:0,cols:10,mineCount:10}),/配置/);
});

test('三关独立续玩和重开，首次确认才计时，切关和刷新继续累计', () => {
  const storage=memory();let now=1000;
  const options={storage,userId:1,now:()=>now,random:()=>0};
  const store=createMinePracticeStore(options);
  store.select('mine-easy');now+=5000;
  assert.equal(store.seconds('mine-easy'),0);
  store.start();now+=3000;
  selectCell(store.current.game,99);toggleFlag(store.current.game);store.save();
  store.select('mine-normal');store.start();now+=4000;
  assert.equal(store.seconds('mine-easy'),7);
  assert.equal(store.seconds('mine-normal'),4);
  store.select('mine-easy');
  assert.equal(store.current.game.cells[99].flagged,true);
  store.restart();
  assert.equal(store.current.game.flaggedCount,0);
  assert.equal(store.seconds('mine-easy'),0);
  assert.equal(store.seconds('mine-normal'),4);
  now+=2000;
  const restored=createMinePracticeStore(options);
  assert.equal(restored.activeId,'mine-easy');
  assert.equal(restored.current.rulesOpen,true);
  restored.select('mine-normal');
  assert.equal(restored.current.rulesOpen,false);
  assert.equal(restored.seconds('mine-normal'),6);
});

test('终盘时间冻结，账号与游客隔离，正式旧存档原文不被改写', () => {
  const storage=memory();let now=1000;
  storage.setItem('jobless-progress-v1:1','old-official-save');
  const store=createMinePracticeStore({storage,userId:1,now:()=>now,random:()=>0});
  store.select('mine-hard');store.start();now+=5000;
  selectCell(store.current.game,0);revealSelected(store.current.game,now);store.save();now+=10000;
  assert.equal(store.seconds('mine-hard'),5);
  store.setUser(2);assert.equal(store.activeId,null);
  store.select('mine-easy');assert.equal(store.current.game.flaggedCount,0);
  store.setUser(null);assert.equal(store.activeId,null);
  store.setUser(1);assert.equal(store.activeId,'mine-hard');
  assert.equal(store.current.game.status,'lost');
  assert.equal(store.seconds('mine-hard'),5);
  assert.equal(storage.getItem('jobless-progress-v1:1'),'old-official-save');
});

test('损坏/版本不兼容的单关不影响其他关，存储不可用时可正常练习', () => {
  const storage=memory();
  const store=createMinePracticeStore({storage,userId:1,random:()=>0});
  store.select('mine-easy');store.select('mine-hard');
  const key=[...storage.values.keys()][0],snapshot=JSON.parse(storage.getItem(key));
  snapshot.entries['mine-hard'].version=99;
  storage.setItem(key,JSON.stringify(snapshot));
  const restored=createMinePracticeStore({storage,userId:1});
  assert.ok(restored.entries['mine-easy']);
  assert.equal(restored.entries['mine-hard'],undefined);
  assert.throws(()=>restored.select('unknown'),/关卡/);
  const denied={getItem(){throw new Error('denied');},setItem(){throw new Error('full');}};
  const temporary=createMinePracticeStore({storage:denied});
  temporary.select('mine-easy');temporary.start();
  assert.equal(temporary.save(),false);
  assert.equal(temporary.current.rulesOpen,false);
});
