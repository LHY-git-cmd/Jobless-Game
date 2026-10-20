/** 模块契约：导入无页面副作用、独立棋盘、账号快照隔离及资源清理。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createScope } from '../src/lib/lifecycle.js';
import { createGameController } from '../src/game/game-controller.js';
import { createProgressCoordinator } from '../src/game/progress-coordinator.js';
import { createMineController } from '../src/game/mine-controller.js';
import { createSudokuController } from '../src/game/sudoku-controller.js';
import { createAkariController } from '../src/game/akari-controller.js';
import { createGameUi } from '../src/game/game-ui.js';
import { createAudioSettings } from '../src/audio-settings.js';

test('导入控制器只定义工厂，不依赖页面文档或发起请求', () => {
  for (const factory of [createGameController, createMineController, createSudokuController, createAkariController]) {
    assert.equal(typeof factory, 'function');
  }
});

test('实例作用域移除监听、取消订阅，只清理一次并阻止销毁后的回调', () => {
  const scope = createScope(), target = new EventTarget();
  let clicks = 0, disposed = 0;
  scope.listen(target, 'click', () => clicks++);
  scope.add(() => disposed++);
  const callback = scope.guard(() => clicks++);
  target.dispatchEvent(new Event('click'));
  callback();
  assert.equal(clicks, 2);
  scope.dispose(); scope.dispose();
  target.dispatchEvent(new Event('click')); callback();
  assert.equal(clicks, 2);
  assert.equal(disposed, 1);
});

test('存档协调使用当前账号与真实格式，恢复期间不覆盖快照，销毁后停止保存', () => {
  const values = new Map(), storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
  let userId = 1, blocked = false, failures = 0;
  const snapshot = { currentIndex: 2, session: { levels: [0, 1, 2].map(() => ({ startedAt: null, seconds: null })) },
    sudoku: { values: Array(81).fill(0), givens: Array(81).fill(0) }, dialogs: [],
    challenge: { startId: 'start', state: { run_id: 'run', levels: [{}, {}, {}] }, pending: [] } };
  const store = createProgressCoordinator({ storage, getUserId: () => userId,
    getSnapshot: atHome => ({ ...snapshot, atHome }), canSave: () => !blocked, onFailure: () => failures++ });
  assert.equal(store.save(true), true);
  assert.equal(store.load().atHome, true);
  blocked = true; store.save(false);
  assert.equal(store.load().atHome, true);
  userId = 2;
  assert.equal(store.load(), null);
  blocked = false; store.save(false);
  assert.equal(store.load().userId, 2);
  store.destroy(); store.save(true);
  assert.equal(store.load().atHome, false);
  assert.equal(failures, 0);
});

test('不同关卡实例的棋盘和笔记独立，恢复失败扫雷终盘不重播动画', () => {
  /** 最小真实控件替身：仅提供控制器渲染依赖，事件注册使用原生 EventTarget。 */
  class Node extends EventTarget {
    constructor() { super(); this.dataset={}; this.children=[]; this.classes=new Set(); this.textContent='';
      this.classList={add:(...names)=>names.forEach(name=>this.classes.add(name)),remove:(...names)=>names.forEach(name=>this.classes.delete(name)),contains:name=>this.classes.has(name)}; }
    set className(value) { this.classList.add(...value.split(/\s+/)); }
    setAttribute() {} removeAttribute() {} scrollTo() {}
    append(node) { this.children.push(node); }
    replaceChildren(fragment) { this.children=[...fragment.children]; }
    querySelectorAll() { return this.children; }
  }
  /** 每个实例持有独立固定节点和音频偏好，不读取全局 document/window。 */
  function setup(factory) {
    const dom={getElementById:()=>new Node(),createElement:()=>new Node(),createDocumentFragment:()=>new Node()};
    const {ui}=createGameUi(dom);
    const controller=factory({ui,dom,settings:createAudioSettings(),canPlay:()=>true,onChange:()=>{},onComplete:()=>{},onBusyChange:()=>{}});
    return {ui,controller};
  }
  for (const factory of [createMineController,createSudokuController,createAkariController]) {
    const first=setup(factory), second=setup(factory);
    first.controller.reset(); second.controller.reset();
    assert.notEqual(first.controller.state,second.controller.state);
    const saved=structuredClone(first.controller.state);
    if(factory===createMineController) {
      saved.status='lost'; saved.cells[0].mine=true;
      first.controller.restore(saved); first.controller.render();
      assert.equal(first.controller.busy,false);
      assert.ok(first.ui.board.children[0].classes.has('cell-spent'));
    } else if(factory===createSudokuController) {
      saved.notes[0]=2;
      first.controller.restore(saved);
      assert.equal(second.controller.state.notes[0],0);
    } else {
      saved.bulbs.add(0); first.controller.restore(saved);
      assert.equal(second.controller.state.bulbs.size,0);
    }
    first.controller.clear(); assert.equal(first.controller.state,null);
    assert.notEqual(second.controller.state,null);
    first.controller.destroy(); second.controller.destroy();
  }
});
