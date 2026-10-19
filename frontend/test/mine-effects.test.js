/** 连锁爆炸测试：传播次序、逐颗音画回调，以及重开/离开时的取消保护。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createGame, selectCell, revealSelected, toggleFlag } from "../src/game.js";
import { createExplosionSequence, createExplosionSound, explosionOrder, EXPLOSION_INTERVAL, EXPLOSION_TAIL } from "../src/mine-effects.js";

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

test("爆炸音效实时响应独立音量和静音，关闭或零音量停止当前声音", async (t) => {
  const original = { AudioContext: globalThis.AudioContext, fetch: globalThis.fetch };
  let gain, starts = 0, stops = 0;
  globalThis.AudioContext = class {
    /** 使用可观察增益与音源模拟 Web Audio，不依赖声卡。 */
    constructor() { this.state = "running"; }
    /** 压缩器保留真实链路需要的参数与连接。 */
    createDynamicsCompressor() { return { threshold: {}, ratio: {}, connect() {} }; }
    /** 捕获主增益供测试核对实时音量。 */
    createGain() { gain = { value: 0 }; return { gain, connect: node => node }; }
    /** 模拟可重叠的单次音源。 */
    createBufferSource() { return { playbackRate: {}, connect() {}, disconnect() {}, start() { starts++; }, stop() { stops++; } }; }
    /** 音频资源完成解码后可供真实控制器播放。 */
    async decodeAudioData() { return {}; }
  };
  globalThis.fetch = async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(1) });
  t.after(() => { for (const [key, value] of Object.entries(original)) { if (value === undefined) delete globalThis[key]; else globalThis[key] = value; } });
  const sound = createExplosionSound("explosion.wav");
  sound.unlock(); await sound.play(0);
  assert.equal(starts, 1);
  sound.setVolume(0.2); assert.equal(gain.value, 0.13);
  sound.setMuted(true); assert.equal(gain.value, 0); assert.equal(stops, 1);
  sound.setVolume(1); assert.equal(gain.value, 0);
  sound.setMuted(false); assert.equal(gain.value, 0.65);
  await sound.play(1); sound.setVolume(0);
  assert.equal(gain.value, 0); assert.equal(stops, 2);
});
