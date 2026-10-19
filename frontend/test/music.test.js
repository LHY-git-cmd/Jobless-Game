/** 全局音乐行为测试：静音、一次性结算、切页续播与异步播放拒绝处理。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createMusicController } from "../src/music.js";

/** 可观察的媒体替身，保留浏览器 play/pause、事件和异步失败语义。 */
class Media {
  /** 初始化播放状态和事件集合。 */
  constructor(url) { this.src = url; this.currentTime = 0; this.duration = 100; this.paused = true; this.events = {}; this.plays = 0; }
  /** 记录媒体回调，支持主动触发结束事件。 */
  addEventListener(name, callback) { this.events[name] = callback; }
  /** 模拟允许的播放以及 autoplay/解码拒绝。 */
  play() { this.plays++; if (this.reject) return Promise.reject(new Error("blocked")); this.paused = false; return Promise.resolve(); }
  /** 暂停不改变已播放位置。 */
  pause() { this.paused = true; }
}

/** 每个用例创建独立播放控制器，不依赖音响或真实时间。 */
function fixture(backgroundUrl = "background.mp3", storage = new Map()) {
  const media = [];
  const controller = createMusicController({ backgroundUrl, victoryUrl: "victory.mp3", createAudio: url => {
    const audio = new Media(url); media.push(audio); return audio;
  }, storage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) } });
  return { controller, media, storage };
}

test("全局背景循环，结算暂停背景并只播放一次胜利音效，结束恢复", async () => {
  const { controller, media: [background, victory] } = fixture();
  await controller.resume();
  assert.equal(background.loop, true);
  assert.equal(background.paused, false);
  await controller.celebrate("round1");
  assert.equal(background.paused, true);
  assert.equal(victory.paused, false);
  await controller.celebrate("round1");
  assert.equal(victory.plays, 1);
  victory.events.ended(); await Promise.resolve();
  assert.equal(background.paused, false);
  await controller.celebrate("round1");
  assert.equal(victory.plays, 1);
});

test("背景音乐与音效独立开关，关闭音效时不补放已跳过的结算音", async () => {
  const { controller, media: [background, victory], storage } = fixture();
  await controller.resume();
  await controller.setEnabled(false);
  assert.equal(background.paused, true);
  await controller.celebrate("effects-only");
  assert.equal(victory.paused, false);
  await controller.setEffectsEnabled(false);
  await controller.resume(); await controller.celebrate("muted-round");
  assert.equal(victory.plays, 1);
  assert.equal(victory.paused, true);
  assert.equal(JSON.parse(storage.get("jobless-audio-settings-v1")).musicEnabled, false);
  await controller.setEnabled(true);
  assert.equal(background.paused, false);
  assert.equal(victory.plays, 1);
  await controller.setEffectsEnabled(true);
  assert.equal(victory.plays, 1);
});

test("背景和胜利音实时调节独立音量，关闭胜利音立即恢复已开启的背景", async () => {
  const { controller, media: [background, victory] } = fixture();
  controller.setMusicVolume(0.2); controller.setEffectsVolume(0.8);
  assert.equal(background.volume, 0.2);
  assert.equal(victory.volume, 0.8);
  await controller.celebrate("round");
  await controller.setEffectsEnabled(false);
  assert.equal(victory.paused, true);
  assert.equal(background.paused, false);
  controller.setMusicVolume(0);
  assert.equal(controller.enabled, true);
  assert.equal(background.volume, 0);
});

test("音效音量降为零立即结束胜利音并恢复背景，调高后不补放", async () => {
  const { controller, media: [background, victory], storage } = fixture();
  await controller.celebrate("zero-volume");
  controller.setEffectsVolume(0);
  assert.equal(victory.paused, true);
  assert.equal(background.paused, false);
  assert.equal(JSON.parse(storage.get("jobless-audio-settings-v1")).effectsEnabled, true);
  controller.setEffectsVolume(0.8);
  await controller.celebrate("zero-volume");
  assert.equal(victory.plays, 1);
});

test("离开结算停止胜利音效、恢复背景，新轮次可以重新庆祝", async () => {
  const { controller, media: [background, victory] } = fixture();
  await controller.celebrate("first");
  await controller.leaveSettlement();
  assert.equal(victory.paused, true);
  assert.equal(victory.currentTime, 0);
  assert.equal(background.paused, false);
  await controller.celebrate("second");
  assert.equal(victory.plays, 2);
});

test("隐藏页面暂停，恢复时继续同一首；切页保存背景位置和静音设置", async () => {
  const { controller, media: [background], storage } = fixture();
  await controller.resume(); background.currentTime = 42;
  controller.suspend();
  assert.equal(background.paused, true);
  await controller.resume();
  assert.equal(background.currentTime, 42);
  controller.persist();
  const next = fixture("background.mp3", storage);
  next.media[0].events.loadedmetadata();
  assert.equal(next.media[0].currentTime, 42);
});

test("浏览器拒绝播放时可由后续用户手势重试，胜利加载失败恢复背景", async () => {
  const { controller, media: [background, victory] } = fixture();
  background.reject = true; await controller.resume();
  assert.equal(background.paused, true);
  background.reject = false; await controller.resume();
  assert.equal(background.paused, false);
  victory.reject = true; await controller.celebrate("failed");
  assert.equal(background.paused, false);
  assert.equal(victory.paused, true);
});

test("没有可播放背景素材时不请求虚假文件，胜利音效仍然可用", async () => {
  const { controller, media } = fixture(null);
  assert.equal(media.length, 1);
  await controller.resume();
  await controller.celebrate("one");
  assert.equal(media[0].plays, 1);
});

test("用户禁止存储时仍能正常播放和静音", async () => {
  const controller = createMusicController({ backgroundUrl: "background.mp3", victoryUrl: "victory.mp3", createAudio: url => new Media(url),
    storage: { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } } });
  await controller.resume(); await controller.setEnabled(false); controller.persist();
  assert.equal(controller.enabled, false);
});
