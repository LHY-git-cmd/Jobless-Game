/** 右上角独立游戏设置弹窗：音乐/音效开关和音量即时生效并自动保存。 */
import { getAudioSettings } from "./audio-settings.js";

/** 复用原生 dialog 的模态焦点隔离，所有带账号页共用同一设置入口。 */
export function initGameSettings({ dom = document, settings = getAudioSettings() } = {}) {
  const dialog = dom.createElement("dialog");
  dialog.id = "game-settings";
  dialog.className = "auth-dialog settings-dialog";
  dialog.setAttribute("aria-labelledby", "settings-title");
  dialog.innerHTML = `<div class="auth-card settings-card">
    <button type="button" class="auth-close settings-close" aria-label="关闭游戏设置">×</button>
    <p class="eyebrow">偏好设置 / SETTINGS</p><h2 id="settings-title">游戏设置</h2>
    <p class="settings-intro">调节背景音乐和音效，让声音陪你解谜。</p>
    ${[ ["music", "背景音乐"], ["effects", "音效"] ].map(([key, title]) => `
      <section class="settings-audio" aria-labelledby="settings-${key}-label">
        <div class="settings-audio-heading"><h3 id="settings-${key}-label">${title}</h3>
          <button type="button" class="settings-toggle" id="settings-${key}-enabled" role="switch" aria-checked="true" aria-labelledby="settings-${key}-label">
            <span class="settings-switch-track" aria-hidden="true"></span><span class="settings-switch-state">开启</span>
          </button>
        </div>
        <div class="settings-volume-heading"><label for="settings-${key}-volume">音量</label><output id="settings-${key}-value" for="settings-${key}-volume"></output></div>
        <input type="range" id="settings-${key}-volume" min="0" max="100" step="1" aria-label="${title}音量">
      </section>`).join("")}
    <p class="settings-note">声音设置即时生效，保存在当前浏览器。</p>
  </div>`;
  dom.body.append(dialog);
  const closeButton = dialog.querySelector(".settings-close");
  let returnFocus;

  /** 关闭后回到独立设置按钮，不触发游戏导航或改变计时。 */
  function close() {
    dialog.close();
    returnFocus?.focus();
  }
  closeButton.addEventListener("click", close);
  dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
  // 原生 dialog 已阻止背景交互；显式循环 Tab 保持键盘操作顺序稳定。
  dialog.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    const controls = [...dialog.querySelectorAll("button:not(:disabled), input:not(:disabled)")].filter(control => !control.hidden && !control.closest("[hidden]"));
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && dom.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && dom.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  for (const key of ["music", "effects"]) {
    dialog.querySelector(`#settings-${key}-enabled`).addEventListener("click", () => settings.update({ [`${key}Enabled`]: !settings.state[`${key}Enabled`] }));
    dialog.querySelector(`#settings-${key}-volume`).addEventListener("input", event => settings.update({ [`${key}Volume`]: Number(event.target.value) / 100 }));
  }
  settings.subscribe(state => {
    for (const key of ["music", "effects"]) {
      const button = dialog.querySelector(`#settings-${key}-enabled`);
      const value = Math.round(state[`${key}Volume`] * 100);
      button.setAttribute("aria-checked", String(state[`${key}Enabled`]));
      button.querySelector(".settings-switch-state").textContent = state[`${key}Enabled`] ? "开启" : "关闭";
      dialog.querySelector(`#settings-${key}-volume`).value = String(value);
      dialog.querySelector(`#settings-${key}-volume`).setAttribute("aria-valuetext", `${value}%`);
      dialog.querySelector(`#settings-${key}-value`).textContent = `${value}%`;
    }
  });
  return {
    /** 设置按钮提供可访问名称与焦点来源。 */
    open(trigger) { if (!dialog.open) { returnFocus = trigger; dialog.showModal(); closeButton.focus(); } },
    /** 换号或退出时关闭设置窗口，不残留失效的账号入口。 */
    close,
  };
}
