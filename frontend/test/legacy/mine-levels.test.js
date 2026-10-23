/** 扫雷多关卡契约：配置校验、独立续玩、计时冻结和账号/旧存档隔离。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createGame, selectCell, revealSelected, toggleFlag } from '../../src/legacy/mine/rules.js';
import { MINE_LEVELS } from '../../src/legacy/mine/levels.js';
import { createMinePracticeStore } from '../../src/legacy/mine/practice-store.js';

/** 内存存储替代浏览器，保留与 localStorage 相同的序列化边界。 */
function memory() {
  const values = new Map();
  return { values, getItem:key=>values.get(key)??null, setItem:(key,value)=>values.set(key,value) };
}

test('关卡配置准确布雷、计算线索和胜负，原有默认调用保持10颗雷', () => {
  assert.equal(createGame(()=>0).level.mineCount,10);
  for (const level of MINE_LEVELS) {
    const game=createGame(()=>0,level);
    assert.equal(game.cells.length,level.rows*level.cols);
    assert.equal(game.cells.filter(cell=>cell.mine).length,level.mineCount);
    for(let index=0;index<game.cells.length;index++) {
      if(game.cells[index].mine||game.cells[index].revealed)continue;
      selectCell(game,index);revealSelected(game,1000+index);
    }
    assert.equal(game.status,'won');
    assert.equal(game.revealedCount,level.rows*level.cols-level.mineCount);
  }
  assert.throws(()=>createGame(Math.random,{rows:10,cols:10,mineCount:100}),/配置/);
  assert.throws(()=>createGame(Math.random,{rows:0,cols:10,mineCount:10}),/配置/);
});

test('提供三种棋盘尺寸且各有三个难度，原10×10关卡身份和版本保持兼容', () => {
  assert.equal(MINE_LEVELS.length,9);
  assert.equal(new Set(MINE_LEVELS.map(level=>level.id)).size,9);
  for(const size of [10,15,20]) {
    const group=MINE_LEVELS.filter(level=>level.rows===size&&level.cols===size);
    assert.equal(group.length,3);
    assert.deepEqual(group.map(level=>level.difficulty),['入门','进阶','挑战']);
    assert.ok(group[0].mineCount<group[1].mineCount&&group[1].mineCount<group[2].mineCount);
  }
  assert.deepEqual(MINE_LEVELS.filter(level=>level.rows===10).map(({id,version,mineCount})=>({id,version,mineCount})),[
    {id:'mine-easy',version:1,mineCount:10},{id:'mine-normal',version:1,mineCount:15},{id:'mine-hard',version:1,mineCount:20},
  ]);
});

test('不同尺寸独立保存和重开，大棋盘边缘格子可标记，刷新不丢失旧10×10进度', () => {
  const storage=memory();let now=1000;
  const options={storage,userId:1,now:()=>now,random:()=>0};
  const store=createMinePracticeStore(options);
  store.select('mine-easy');store.start();selectCell(store.current.game,99);toggleFlag(store.current.game);store.save();
  const small=structuredClone(store.current.game);
  for(const size of [15,20]) {
    const level=MINE_LEVELS.find(item=>item.rows===size&&item.difficulty==='挑战');
    assert.ok(level,`缺少${size}×${size}挑战关`);
    store.select(level.id);store.start();now+=2000;
    const last=size*size-1;
    assert.equal(selectCell(store.current.game,last),true);toggleFlag(store.current.game);store.save();
    const restored=createMinePracticeStore(options);
    assert.equal(restored.activeId,level.id);
    assert.equal(restored.current.game.cells[last].flagged,true);
    assert.deepEqual(restored.entries['mine-easy'].game,small);
    restored.restart();assert.equal(restored.current.game.cells[last].flagged,false);
    assert.deepEqual(restored.entries['mine-easy'].game,small);
  }
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
