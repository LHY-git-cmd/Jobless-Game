/** 浏览器音频偏好：背景音乐和音效独立开关、音量持久化与跨组件同步。 */
const STORAGE_KEY = "jobless-audio-settings-v1";
const DEFAULTS = Object.freeze({ musicEnabled: true, effectsEnabled: true, musicVolume: 0.28, effectsVolume: 0.65 });
let sharedSettings;

/** 创建可注入存储的偏好控制器；无存储时当前页面仍能调节音频。 */
export function createAudioSettings(storage) {
  let state = { ...DEFAULTS };
  const listeners = new Set();

  /** 只接受约定的开关和有限音量，避免损坏数据传入浏览器音频 API。 */
  function normalize(value, previous) {
    const next = { ...previous };
    for (const key of ["musicEnabled", "effectsEnabled"]) {
      if (typeof value?.[key] === "boolean") next[key] = value[key];
    }
    for (const key of ["musicVolume", "effectsVolume"]) {
      if (typeof value?.[key] === "number" && Number.isFinite(value[key])) next[key] = Math.min(1, Math.max(0, value[key]));
    }
    return next;
  }
  try { state = normalize(JSON.parse(storage?.getItem(STORAGE_KEY) ?? "null"), state); } catch { /* 首次访问或损坏存档使用默认开启。 */ }

  return {
    /** 返回副本，外部不能绕过更新通知修改偏好。 */
    get state() { return { ...state }; },
    /** 调节立即生效并保存；存储失败不影响当前页面的控制。 */
    update(value) {
      state = normalize(value, state);
      try { storage?.setItem(STORAGE_KEY, JSON.stringify(state)); } catch { /* 隐私设置或配额限制时只保持内存状态。 */ }
      listeners.forEach(listener => listener({ ...state }));
    },
    /** 新组件立即取得当前设置，返回取消订阅方法。 */
    subscribe(listener) {
      listeners.add(listener);
      listener({ ...state });
      return () => listeners.delete(listener);
    },
  };
}

/** 页面内所有播放器与设置窗口共享同一份浏览器偏好。 */
export function getAudioSettings(view = window) {
  if (!sharedSettings) {
    let storage;
    try { storage = view.localStorage; } catch { /* 浏览器禁用本地存储时使用内存。 */ }
    sharedSettings = createAudioSettings(storage);
  }
  return sharedSettings;
}
