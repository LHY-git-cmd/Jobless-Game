/** 全站音轨：背景音乐和胜利音效独立控制，保留一次性结算与切页播放位置。 */
import { createAudioSettings, getAudioSettings } from "./audio-settings.js";

// 使用用户提供的同曲 MP3，不直接向浏览器发送原始 NCM。
const BACKGROUND_URL = new URL("../assets/audio/background.mp3", import.meta.url).href;
const VICTORY_URL = new URL("../assets/audio/victory.mp3", import.meta.url).href;
let sharedMusic;

/** 媒体状态与页面分离，避免重复打开结算叠加音轨或覆盖用户静音选择。 */
export function createMusicController({ backgroundUrl = BACKGROUND_URL, victoryUrl = VICTORY_URL,
  createAudio = url => new Audio(url), storage, settings = createAudioSettings(storage), onChange = () => {} } = {}) {
  /** 存储可能被隐私设置禁用，不让音乐阻塞游戏。 */
  function read(key) { try { return storage?.getItem(key); } catch { return null; } }
  /** 这里只保存播放位置，不保存账号或凭据；音频偏好由共享设置持久化。 */
  function write(key, value) { try { storage?.setItem(key, String(value)); } catch { /* 无存储时沿用当前页状态。 */ } }

  const background = backgroundUrl ? createAudio(backgroundUrl) : null;
  const victory = createAudio(victoryUrl);
  let preferences = settings.state;
  let suspended = false;
  let celebrating = false;
  let lastRound = null;
  let version = 0;
  let blocked = false;
  if (background) {
    background.loop = true;
    background.volume = preferences.musicVolume;
    background.preload = "none";
    background.addEventListener("loadedmetadata", () => {
      const saved = Number(read("jobless-music-position"));
      if (Number.isFinite(saved) && saved > 0 && Number.isFinite(background.duration) && saved < background.duration) {
        background.currentTime = saved;
      }
    });
  }
  victory.loop = false;
  victory.volume = preferences.effectsVolume;
  victory.preload = "none";

  /** 分别报告偏好和实际播放状态，autoplay 拒绝不改变用户开关。 */
  function notify() { onChange({ enabled: preferences.musicEnabled, effectsEnabled: preferences.effectsEnabled, blocked, hasBackground: Boolean(background), celebrating }); }

  /** 背景与胜利音分别遵守音乐、音效开关。 */
  function isEnabled(audio) { return audio === victory ? preferences.effectsEnabled && preferences.effectsVolume > 0 : preferences.musicEnabled; }

  /** 安全处理同步异常和 play Promise 拒绝，后续用户手势仍可重试。 */
  async function play(audio) {
    if (!audio || !isEnabled(audio) || suspended) return;
    const current = version;
    try {
      await audio.play();
      if (current !== version) { if (!isEnabled(audio) || suspended || (audio === victory && !celebrating) || (audio === background && celebrating)) audio.pause(); return; }
      blocked = false;
    } catch {
      if (current !== version) return;
      blocked = true;
      if (audio === victory) {
        celebrating = false;
        victory.pause();
        await play(background);
      }
    }
    notify();
  }

  /** 用户手势或可见性恢复时继续当前音轨，不重置进度。 */
  async function resume() {
    suspended = false;
    await play(celebrating ? victory : background);
  }

  /** 背景音乐开关不影响爆炸与胜利音效。 */
  async function setEnabled(value) {
    settings.update({ musicEnabled: Boolean(value) });
  }

  /** 一轮只在首次开始结算时播放，静音时不补放，胜利音不与背景叠加。 */
  async function celebrate(roundId) {
    if (!roundId || lastRound === roundId) return;
    lastRound = roundId;
    if (!isEnabled(victory)) return;
    version++;
    celebrating = true;
    background?.pause();
    victory.pause();
    victory.currentTime = 0;
    await play(victory);
  }

  /** 返回首页、关闭结算或换页时结束胜利音效，从背景暂停位置恢复。 */
  async function leaveSettlement() {
    version++;
    celebrating = false;
    victory.pause();
    victory.currentTime = 0;
    if (preferences.musicEnabled && !suspended) await play(background);
  }

  /** 页面不可见时暂停，返回后由可见性事件恢复同一音轨。 */
  function suspend() {
    version++;
    suspended = true;
    background?.pause();
    victory.pause();
  }

  /** 页面跳转前保存位置，下一页仍需遵守浏览器对音频播放的授权。 */
  function persist() {
    if (background) write("jobless-music-position", background.currentTime);
    suspend();
  }

  victory.addEventListener("ended", () => { void leaveSettlement(); });
  victory.addEventListener("error", () => { if (celebrating) void leaveSettlement(); });
  background?.addEventListener("error", () => { blocked = true; notify(); });
  settings.subscribe(next => {
    const previous = preferences;
    preferences = next;
    if (background) background.volume = next.musicVolume;
    victory.volume = next.effectsVolume;
    if (previous.musicEnabled !== next.musicEnabled || previous.effectsEnabled !== next.effectsEnabled) version++;
    if (!next.musicEnabled) { background?.pause(); blocked = false; }
    if (!next.effectsEnabled || next.effectsVolume === 0) {
      if (celebrating) void leaveSettlement();
      else victory.pause();
    }
    if (!previous.musicEnabled && next.musicEnabled && !suspended && !celebrating) void play(background);
    notify();
  });
  return {
    get enabled() { return preferences.musicEnabled; },
    resume, setEnabled, celebrate, leaveSettlement, suspend, persist,
    /** 音效独立开关；已跳过的结算提示不因重新开启而补放。 */
    async setEffectsEnabled(value) { settings.update({ effectsEnabled: Boolean(value) }); },
    /** 背景音量实时更新，零音量不改变用户的开关选择。 */
    setMusicVolume(value) { settings.update({ musicVolume: value }); },
    /** 胜利音和其他游戏音效使用同一音效音量。 */
    setEffectsVolume(value) { settings.update({ effectsVolume: value }); },
  };
}

/** 所有页面初始化音轨与手势解锁；控制入口统一由用户名的游戏设置提供。 */
export function initMusic({ dom = document, view = window } = {}) {
  if (sharedMusic || typeof Audio === "undefined") return sharedMusic;
  let storage;
  try { storage = view.sessionStorage; } catch { /* 不支持存储也能播放。 */ }
  const controller = createMusicController({ storage, settings: getAudioSettings(view), createAudio: url => {
    const audio = new Audio(url);
    audio.hidden = true;
    audio.dataset.music = url === VICTORY_URL ? "victory" : "background";
    dom.body.append(audio);
    return audio;
  } });
  sharedMusic = controller;
  /** 任意用户手势只恢复允许播放的音轨，不改变设置中的开关。 */
  function unlock(event) {
    if (dom.hidden) return;
    void controller.resume();
  }
  dom.addEventListener("click", unlock, true);
  dom.addEventListener("keydown", event => { if (["Enter", " "].includes(event.key)) unlock(event); }, true);
  dom.addEventListener("visibilitychange", () => { if (dom.hidden) controller.suspend(); else void controller.resume(); });
  dom.addEventListener("settlement-opened", event => { void controller.celebrate(event.detail?.runId); });
  dom.addEventListener("settlement-closed", () => { void controller.leaveSettlement(); });
  view.addEventListener("pagehide", () => controller.persist());
  view.addEventListener("pageshow", () => { if (!dom.hidden) void controller.resume(); });
  void controller.resume();
  return controller;
}
