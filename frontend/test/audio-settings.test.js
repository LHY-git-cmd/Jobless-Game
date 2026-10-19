/** 音频偏好测试：默认开启、独立音量、刷新持久化与禁用存储时的降级。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createAudioSettings } from "../src/audio-settings.js";

test("首次音乐和音效均开启，调节与静音分别保存且不互相影响", () => {
  const values = new Map();
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
  const settings = createAudioSettings(storage);
  assert.deepEqual(settings.state, { musicEnabled: true, effectsEnabled: true, musicVolume: 0.28, effectsVolume: 0.65 });
  const changes = [];
  const unsubscribe = settings.subscribe(value => changes.push(value));
  settings.update({ musicEnabled: false, musicVolume: 0.4, effectsVolume: 0.8 });
  assert.equal(settings.state.effectsEnabled, true);
  assert.deepEqual(createAudioSettings(storage).state, settings.state);
  settings.update({ musicEnabled: true });
  assert.equal(settings.state.musicVolume, 0.4);
  unsubscribe();
  settings.update({ effectsEnabled: false });
  assert.equal(changes.length, 3);
});

test("无效存档和不可用存储保持默认，音量限制在零到一之间", () => {
  const denied = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("full"); } };
  const settings = createAudioSettings(denied);
  settings.update({ musicVolume: -2, effectsVolume: 5, musicEnabled: "false" });
  assert.deepEqual(settings.state, { musicEnabled: true, effectsEnabled: true, musicVolume: 0, effectsVolume: 1 });
  settings.update({ effectsVolume: NaN });
  assert.equal(settings.state.effectsVolume, 1);
  assert.equal(createAudioSettings({ getItem: () => "{" }).state.musicEnabled, true);
});
