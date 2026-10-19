/** 扫雷连锁爆炸时间线：逐颗显雷、引爆、熄灭，离开或重开可完整取消。 */

export const EXPLOSION_INTERVAL = 360;
export const EXPLOSION_TAIL = 1400;

/** 从踩中的地雷向外传播；相同距离使用棋盘位置保持顺序稳定。 */
export function explosionOrder(game) {
  const origin = game.explodedAt;
  if (game.status !== "lost" || origin === null) return [];
  const cols = game.level.cols;
  const distance = (index) => (Math.floor(index / cols) - Math.floor(origin / cols)) ** 2
    + (index % cols - origin % cols) ** 2;
  return game.cells.flatMap((cell, index) => cell.mine ? [index] : [])
    .sort((a, b) => distance(a) - distance(b) || a - b);
}

/** 将计时器与页面分开，保证重开后旧动画不会再修改新棋盘。 */
export function createExplosionSequence({ reveal, explode, settle, finish, schedule = setTimeout, cancel = clearTimeout }) {
  let version = 0;
  const pending = new Set();

  function stop() {
    version += 1;
    pending.forEach(cancel);
    pending.clear();
  }

  function start(order) {
    stop();
    if (order.length === 0) return;
    const current = version;
    const later = (delay, callback) => {
      const id = schedule(() => {
        pending.delete(id);
        if (version === current) callback();
      }, delay);
      pending.add(id);
    };
    // 首颗直接响应用户操作，音画同时触发；其余先显雷再引爆。
    reveal(order[0]);
    explode(order[0], 0);
    order.forEach((index, step) => {
      if (step > 0) {
        later(step * EXPLOSION_INTERVAL - 120, () => reveal(index));
        later(step * EXPLOSION_INTERVAL, () => explode(index, step));
      }
      later(step * EXPLOSION_INTERVAL + 520, () => settle(index));
    });
    later((order.length - 1) * EXPLOSION_INTERVAL + EXPLOSION_TAIL, finish);
  }

  return { start, stop };
}

/** 预解码用户音效；点击时解锁音频，支持短音效重叠并限制叠加音量。 */
export function createExplosionSound(url) {
  let context;
  let output;
  let decoded;
  let epoch = 0;
  let muted = false;
  let volume = 0.65;
  const active = new Set();

  function unlock() {
    try {
      if (!context) {
        context = new AudioContext();
        const compressor = context.createDynamicsCompressor();
        compressor.threshold.value = -12;
        compressor.ratio.value = 6;
        output = context.createGain();
        output.gain.value = muted ? 0 : 0.65 * volume;
        output.connect(compressor).connect(context.destination);
        decoded = fetch(url).then((response) => {
          if (!response.ok) throw new Error("无法加载爆炸音效");
          return response.arrayBuffer();
        }).then((bytes) => context.decodeAudioData(bytes)).catch(() => null);
      }
      if (context.state === "suspended") void context.resume().catch(() => {});
    } catch {
      // 不支持音频或加载失败时，视觉连锁仍按原节奏完成。
    }
  }

  async function play(step) {
    const current = epoch;
    const buffer = await decoded;
    if (!buffer || muted || volume === 0 || current !== epoch || context?.state !== "running") return;
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.playbackRate.value = step === 0 ? 1 : [0.96, 1.04, 1, 1.08][step % 4];
    source.connect(output);
    source.onended = () => { active.delete(source); source.disconnect(); };
    active.add(source);
    source.start();
  }

  function stop() {
    epoch += 1;
    active.forEach((source) => { source.stop(); source.disconnect(); });
    active.clear();
  }

  function setMuted(value) {
    muted = Boolean(value);
    if (output) output.gain.value = muted ? 0 : 0.65 * volume;
    if (muted) stop();
  }

  /** 实时调整主增益，保留压缩器限制叠加峰值；零音量立即结束尾音。 */
  function setVolume(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return;
    volume = Math.min(1, Math.max(0, value));
    if (output) output.gain.value = muted ? 0 : 0.65 * volume;
    if (volume === 0) stop();
  }

  return { unlock, play, stop, setMuted, setVolume };
}
