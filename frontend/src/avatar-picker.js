/** 独立头像弹窗的选择器：按需加载网格，明确保存，支持键盘、重试和账号隔离。 */
import { createAvatarImage, createAvatarSelection, loadAvatarCatalog, updateAvatarImage } from "./avatar.js";

/** 头像选择区独立滚动，沿用原保存及账号隔离流程。 */
export function initAvatarPicker(host, { dom = document, onSaved, onUnauthorized } = {}) {
  host.innerHTML = `<div class="settings-avatar-heading"><h3 id="avatar-title">个人头像</h3><span class="avatar-account-note">跟随账号保存</span></div>
    <div class="avatar-current"><div class="avatar-preview"></div><div><p class="avatar-caption">选一个喜欢的形象</p><button type="button" class="avatar-expand" aria-expanded="false" aria-controls="avatar-choices">更换头像</button></div></div>
    <div id="avatar-choices" hidden><div class="avatar-grid" role="group" aria-label="预设头像"></div>
      <button type="button" class="avatar-retry" hidden>重新加载头像</button>
      <button type="button" class="avatar-save" disabled>保存头像</button></div>
    <p class="avatar-status" role="status" aria-live="polite"></p>`;
  const grid = host.querySelector(".avatar-grid"), status = host.querySelector(".avatar-status");
  const choices = host.querySelector("#avatar-choices"), expand = host.querySelector(".avatar-expand");
  const save = host.querySelector(".avatar-save"), retry = host.querySelector(".avatar-retry");
  const preview = createAvatarImage(1, { dom, size: 64 });
  host.querySelector(".avatar-preview").append(preview);
  let options = null, loading = false, loadEpoch = 0;
  const model = createAvatarSelection({ onSaved, onUnauthorized, onChange: render });

  /** 同步选中外框、预览和保存状态，保存成功前不改变账号入口。 */
  function render(state) {
    updateAvatarImage(preview, state.selected);
    for (const button of grid.querySelectorAll("button")) {
      button.disabled = state.busy;
      button.setAttribute("aria-pressed", String(Number(button.dataset.avatarId) === state.selected));
    }
    save.disabled = loading || !options || state.busy || !state.user || state.selected === state.user.avatar_id;
    save.textContent = state.busy ? "正在保存…" : "保存头像";
    choices.setAttribute("aria-busy", String(state.busy || loading));
    status.textContent = state.message;
  }

  /** 清单失败显示可重试反馈，换号使旧加载失效，已成功的公共清单可以复用。 */
  async function load() {
    if (loading || options) return;
    const current = ++loadEpoch;
    loading = true; retry.hidden = true; render(model.state); status.textContent = "正在加载头像…";
    try {
      const entries = await loadAvatarCatalog();
      if (current !== loadEpoch) return;
      options = entries;
      const buttons = entries.map(entry => {
        const button = dom.createElement("button");
        button.type = "button"; button.className = "avatar-option"; button.dataset.avatarId = String(entry.id);
        button.setAttribute("aria-label", `头像 ${String(entry.id).padStart(3, "0")}`);
        button.append(createAvatarImage(entry.id, { dom, size: 48 }));
        button.addEventListener("click", () => model.select(entry.id));
        return button;
      });
      grid.replaceChildren(...buttons);
    } catch (error) {
      if (current !== loadEpoch) return;
      status.textContent = error.message; retry.hidden = false;
    } finally {
      if (current === loadEpoch) {
        loading = false;
        if (options) render(model.state);
        else { choices.setAttribute("aria-busy", "false"); save.disabled = true; }
      }
    }
  }

  expand.addEventListener("click", () => {
    choices.hidden = !choices.hidden;
    expand.setAttribute("aria-expanded", String(!choices.hidden));
    expand.textContent = choices.hidden ? "更换头像" : "收起头像";
    if (!choices.hidden) void load();
  });
  retry.addEventListener("click", () => { void load(); });
  save.addEventListener("click", () => { void model.save(); });
  return {
    /** 退出和换号时立刻清理预览及保存状态；成功后的同账号更新保留展开状态和反馈。 */
    setUser(user) {
      const previous = model.state;
      if (previous.user?.id === user?.id && previous.user?.avatar_id === user?.avatar_id) return;
      loadEpoch++; loading = false; retry.hidden = true;
      model.setUser(user);
      if (previous.user?.id !== user?.id) {
        choices.hidden = true; expand.setAttribute("aria-expanded", "false"); expand.textContent = "更换头像";
      }
    },
    /** 每次打开恢复账号当前头像，丢弃尚未保存的预览。 */
    reset(user) { if (!model.state.busy) model.setUser(user); },
    /** 点击头像直接展开候选网格，沿用原选择、重试和保存流程。 */
    open(user) {
      if (!model.state.busy) model.setUser(user);
      choices.hidden = false; expand.setAttribute('aria-expanded', 'true'); expand.textContent = '收起头像';
      void load();
    },
  };
}

/** 独立头像弹窗只负责形象选择，设置入口不再混入头像编辑。 */
export function initAvatarDialog({ dom = document, onSaved, onUnauthorized } = {}) {
  const dialog = dom.createElement('dialog');
  dialog.id = 'avatar-dialog'; dialog.className = 'auth-dialog avatar-dialog';
  dialog.setAttribute('aria-labelledby', 'avatar-dialog-title');
  dialog.innerHTML = '<div class="auth-card"><button type="button" class="auth-close avatar-dialog-close" aria-label="关闭头像选择">×</button><p class="eyebrow">个人形象 / AVATAR</p><h2 id="avatar-dialog-title">更换头像</h2><section class="settings-avatar" aria-labelledby="avatar-title"></section></div>';
  dom.body.append(dialog);
  const picker = initAvatarPicker(dialog.querySelector('.settings-avatar'), { dom, onSaved, onUnauthorized });
  const closeButton = dialog.querySelector('.avatar-dialog-close');
  let currentUser = null, returnFocus = null;
  /** 关闭或Esc回到头像按钮，恢复原来的键盘操作位置。 */
  function close() { dialog.close(); returnFocus?.focus(); }
  closeButton.addEventListener('click', close);
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const controls = [...dialog.querySelectorAll('button:not(:disabled)')].filter(button => !button.hidden && !button.closest('[hidden]'));
    const first = controls[0], last = controls.at(-1);
    // 网格滚动与焦点循环独立；首尾跳转不会把键盘焦点移出模态窗口。
    if (event.shiftKey && dom.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && dom.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  return {
    /** 原生dialog隔离焦点，直接展示头像列表。 */
    open(trigger) {
      if (!currentUser || dialog.open) return;
      returnFocus = trigger; picker.open(currentUser); dialog.showModal(); closeButton.focus();
    },
    /** 换号同步预览并使旧加载/保存结果失效。 */
    setUser(user) { currentUser = user; picker.setUser(user); },
    close,
  };
}
