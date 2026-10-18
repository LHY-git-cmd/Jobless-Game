/** 全站共享音乐：循环背景、结算一次性胜利音效、静音与切页播放位置。 */

// 使用用户提供的同曲 MP3，不直接向浏览器发送原始 NCM。
const BACKGROUND_URL = new URL("../assets/audio/background.mp3", import.meta.url).href;
const VICTORY_URL = new URL("../assets/audio/victory.mp3", import.meta.url).href;
let sharedMusic;

/** 媒体状态与页面分离，避免重复打开结算叠加音轨或覆盖用户静音选择。 */
export function createMusicController({ backgroundUrl = BACKGROUND_URL, victoryUrl = VICTORY_URL,
  createAudio = url => new Audio(url), storage, onChange = () => {} } = {}) {
  /** 存储可能被隐私设置禁用，不让音乐阻塞游戏。 */
  function read(key) { try { return storage?.getItem(key); } catch { return null; } }
  /** 只保存音乐偏好与时间，不保存账号或凭据。 */
  function write(key, value) { try { storage?.setItem(key, String(value)); } catch { /* 无存储时沿用当前页状态。 */ } }

  const background = backgroundUrl ? createAudio(backgroundUrl) : null;
  const victory = createAudio(victoryUrl);
  let enabled = read("jobless-music-enabled") !== "false";
  let suspended = false;
  let celebrating = false;
  let lastRound = null;
  let version = 0;
  let blocked = false;
  if (background) {
    background.loop = true;
    background.volume = 0.28;
    background.preload = "none";
    background.addEventListener("loadedmetadata", () => {
      const saved = Number(read("jobless-music-position"));
      if (Number.isFinite(saved) && saved > 0 && Number.isFinite(background.duration) && saved < background.duration) {
        background.currentTime = saved;
      }
    });
  }
  victory.loop = false;
  victory.volume = 0.65;
  victory.preload = "none";

  /** 把实际状态交给开关渲染，autoplay 拒绝时不假装正在播放。 */
  function notify() { onChange({ enabled, blocked, hasBackground: Boolean(background), celebrating }); }

  /** 安全处理同步异常和 play Promise 拒绝，后续用户手势仍可重试。 */
  async function play(audio) {
    if (!audio || !enabled || suspended) return;
    const current = version;
    try {
      await audio.play();
      if (current !== version) { if (!enabled || suspended || (audio === victory && !celebrating) || (audio === background && celebrating)) audio.pause(); return; }
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
    if (!enabled) return;
    await play(celebrating ? victory : background);
  }

  /** 静音立即停止所有音乐；重新开启不重复播放已跳过的庆祝音。 */
  async function setEnabled(value) {
    enabled = Boolean(value);
    version++;
    write("jobless-music-enabled", enabled);
    if (!enabled) { background?.pause(); victory.pause(); blocked = false; }
    else await resume();
    notify();
  }

  /** 一轮只在首次开始结算时播放，静音时不补放，胜利音不与背景叠加。 */
  async function celebrate(roundId) {
    if (!roundId || lastRound === roundId) return;
    lastRound = roundId;
    if (!enabled) return;
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
    if (enabled && !suspended) await play(background);
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
    write("jobless-music-enabled", enabled);
    suspend();
  }

  victory.addEventListener("ended", () => { void leaveSettlement(); });
  victory.addEventListener("error", () => { if (celebrating) void leaveSettlement(); });
  background?.addEventListener("error", () => { blocked = true; notify(); });
  notify();
  return { get enabled() { return enabled; }, resume, setEnabled, celebrate, leaveSettlement, suspend, persist };
}

/** 所有页面通过共享登录装配入口初始化一次；开关在游戏面板内仍可访问。 */
export function initMusic({ dom = document, view = window } = {}) {
  if (sharedMusic || typeof Audio === "undefined") return sharedMusic;
  const button = dom.createElement("button");
  button.type = "button";
  button.id = "global-music";
  button.className = "global-music";
  let storage;
  let playbackBlocked = false;
  try { storage = view.sessionStorage; } catch { /* 不支持存储也能播放。 */ }
  const controller = createMusicController({ storage, createAudio: url => {
    const audio = new Audio(url);
    audio.hidden = true;
    audio.dataset.music = url === VICTORY_URL ? "victory" : "background";
    dom.body.append(audio);
    return audio;
  }, onChange: state => {
    playbackBlocked = state.blocked;
    button.textContent = state.enabled ? state.blocked ? "点击播放音乐" : "音乐：开" : "音乐：关";
    button.setAttribute("aria-label", state.enabled ? "关闭背景音乐与结算音乐" : "开启背景音乐与结算音乐");
    button.setAttribute("aria-pressed", String(state.enabled));
    button.title = state.hasBackground ? "背景循环播放，结算时播放胜利音效" : "结算胜利音效已启用，背景音乐等待可播放素材";
  } });
  sharedMusic = controller;
  dom.body.append(button);
  button.addEventListener("click", () => {
    if (playbackBlocked && controller.enabled) void controller.resume();
    else void controller.setEnabled(!controller.enabled);
  });
  /** 捕获阶段仅解锁播放，点击音乐开关由其自身处理，避免立即反向切换。 */
  function unlock(event) {
    if (event.target === button || dom.hidden) return;
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
