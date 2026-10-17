/** 连锁爆炸测试：传播次序、逐颗音画回调，以及重开/离开时的取消保护。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createGame, selectCell, revealSelected, toggleFlag } from "../src/game.js";
import { createExplosionSequence, explosionOrder, EXPLOSION_INTERVAL, EXPLOSION_TAIL } from "../src/mine-effects.js";

/** 用可推进的时钟测试动画次序，避免真实等待数秒。 */
function fixture() {
  let time = 0;
  let serial = 0;
  const tasks = new Map();
  const events = [];
  const sequence = createExplosionSequence({
    reveal: (index) => events.push([time, "reveal", index]),
    explode: (index) => events.push([time, "explode", index]),
    settle: (index) => events.push([time, "settle", index]),
    finish: () => events.push([time, "finish"]),
    schedule: (fn, delay) => { const id = ++serial; tasks.set(id, { fn, at: time + delay }); return id; },
    cancel: (id) => tasks.delete(id),
  });
  function advance(to) {
    while (true) {
      const next = [...tasks].filter(([, task]) => task.at <= to).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) break;
      time = next[1].at;
      tasks.delete(next[0]);
      next[1].fn();
    }
    time = to;
  }
  return { sequence, events, tasks, advance };
}

test("踩中雷排在首位，向外引爆包括已标记的全部地雷", () => {
  const game = createGame(() => 0);
  assert.deepEqual(explosionOrder(game), []);
  selectCell(game, 0);
  toggleFlag(game);
  selectCell(game, 4);
  revealSelected(game, 1000);
  assert.deepEqual(explosionOrder(game), [4, 3, 5, 2, 6, 1, 7, 0, 8, 9]);
});

test("首颗立即引爆，其余先显雷再爆炸，每颗只爆一次，尾音结束后显示结果", () => {
  const { sequence, events, advance } = fixture();
  sequence.start([4, 3, 5]);
  assert.deepEqual(events, [[0, "reveal", 4], [0, "explode", 4]]);
  advance(EXPLOSION_INTERVAL - 120);
  assert.deepEqual(events.at(-1), [240, "reveal", 3]);
  advance(EXPLOSION_INTERVAL);
  assert.deepEqual(events.at(-1), [360, "explode", 3]);
  const end = 2 * EXPLOSION_INTERVAL + EXPLOSION_TAIL;
  advance(end - 1);
  assert.equal(events.some((event) => event[1] === "finish"), false);
  advance(end);
  assert.deepEqual(events.filter((event) => event[1] === "explode").map((event) => event[2]), [4, 3, 5]);
  assert.equal(events.filter((event) => event[1] === "settle").length, 3);
  assert.deepEqual(events.at(-1), [end, "finish"]);
});

test("中途停止会清除后续显雷、爆炸与结果弹窗", () => {
  const { sequence, events, tasks, advance } = fixture();
  sequence.start([4, 3, 5]);
  advance(300);
  sequence.stop();
  const count = events.length;
  advance(10000);
  assert.equal(events.length, count);
  assert.equal(tasks.size, 0);
});

test("再次启动不会混入上一轮爆炸或重复显示结果", () => {
  const { sequence, events, advance } = fixture();
  sequence.start([4, 3, 5]);
  advance(100);
  sequence.start([80, 90]);
  advance(10000);
  assert.deepEqual(events.filter((event) => event[1] === "explode").map((event) => event[2]), [4, 80, 90]);
  assert.equal(events.filter((event) => event[1] === "finish").length, 1);
});
