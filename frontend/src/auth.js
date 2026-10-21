/** 三页复用的登录弹窗、会话恢复和关卡登录拦截；不改变关卡计时与规则。 */
import { Events } from "./lib/events.js";
import { authRequest } from "./auth-client.js";
import { usernameUnits, validateUsername, validatePassword } from "./auth-validation.js";
import { initMusic } from "./music.js";
import { initGameSettings } from "./settings.js";
import { createAvatarImage, updateAvatarImage } from "./avatar.js";
import { initNotifications } from "./notifications.js";
import { initPlayerProfile } from './player-profile.js';

/** 创建共享控制器；页面只需提供右上角 .auth-controls 容器。 */
export function initAuth() {
  const host = document.querySelector(".auth-controls");
  if (!host) return null;
  initMusic();
  host.innerHTML = `<button type="button" class="auth-open" aria-haspopup="dialog">登录</button>
    <button type="button" class="auth-user hidden" aria-haspopup="dialog" aria-controls="game-settings" title="打开游戏设置"></button><button type="button" class="auth-logout hidden">退出登录</button>
    <span class="auth-header-status" role="status"></span>`;
  initNotifications();
  const modal = document.createElement("dialog");
  modal.id = "auth-dialog";
  modal.className = "auth-dialog";
  modal.setAttribute("aria-labelledby", "auth-title");
  modal.setAttribute("aria-describedby", "auth-intro");
  modal.innerHTML = `<div class="auth-card">
    <button type="button" class="auth-close" aria-label="关闭登录弹窗">×</button>
    <p class="eyebrow">继续你的解谜之旅</p>
    <h2 id="auth-title">欢迎来到小岛</h2>
    <p id="auth-intro" class="auth-intro">用户名不存在时自动创建账号。<br>再次来访，请使用相同的用户名和密码。</p>
    <form id="auth-form" novalidate>
      <div class="auth-field"><div class="auth-label-row"><label for="auth-username">用户名</label><output id="auth-count" for="auth-username">0 / 12</output></div>
        <input id="auth-username" name="username" type="text" autocomplete="username" autocapitalize="none" spellcheck="false" aria-describedby="auth-username-hint auth-username-error" required>
        <p id="auth-username-hint" class="auth-hint">汉字、英文或数字 · 汉字计 1.5，最多 12</p>
        <p id="auth-username-error" class="auth-error" aria-live="polite"></p></div>
      <div class="auth-field"><label for="auth-password">密码</label>
        <input id="auth-password" name="password" type="password" autocomplete="current-password" aria-describedby="auth-password-hint auth-password-error" required>
        <p id="auth-password-hint" class="auth-hint">至少 6 个字符，请记住你的密码。</p>
        <p id="auth-password-error" class="auth-error" aria-live="polite"></p></div>
      <p id="auth-status" class="auth-status" role="status" tabindex="-1"></p>
      <button type="submit" class="auth-submit">登录并继续 <span aria-hidden="true">→</span></button>
    </form>
    <p class="auth-footnote">从这里出发，让好奇心带路。</p>
  </div>`;
  document.body.append(modal);
  const $ = (selector) => modal.querySelector(selector);
  const form = $("form");
  const username = $("#auth-username");
  const password = $("#auth-password");
  const status = $("#auth-status");
  const openButton = host.querySelector(".auth-open");
  const logoutButton = host.querySelector(".auth-logout");
  const headerStatus = host.querySelector(".auth-header-status");
  const gameSettings = initGameSettings({
    onAvatarSaved: value => {
      if (user?.id !== value.id) return;
      renderUser(value);
      document.dispatchEvent(new CustomEvent(Events.USER_PROFILE_UPDATED, { detail: { user: { ...value } } }));
    },
    onUnauthorized: () => { renderUser(null); headerStatus.textContent = "登录已失效，请重新登录。"; },
  });
  const userButton = host.querySelector(".auth-user");
  const avatarImage = createAvatarImage(1, { size: 28, className: "auth-avatar" });
  const usernameLabel = document.createElement("span");
  usernameLabel.className = "auth-username";
  userButton.append(avatarImage, usernameLabel);
  userButton.addEventListener("click", () => { if (user) gameSettings.open(userButton); });
  const profileHost = document.querySelector('[data-player-profile]');
  const profile = profileHost ? initPlayerProfile({ host: profileHost, userButton, openButton, avatarImage, usernameLabel }) : null;
  let user = null;
  let pending = null;
  let returnFocus = null;
  let submitting = false;
  let generation = 0;
  let identityGeneration = 0;
  document.addEventListener(Events.AUTH_EXPIRED, () => { renderUser(null); headerStatus.textContent = '登录已失效，请重新登录。'; });

  /** 用户名只写入 textContent，避免把用户输入作为 HTML 插入。 */
  function renderUser(value) {
    const previousId = user?.id;
    user = value ? { id: value.id, username: value.username, avatar_id: value.avatar_id ?? 1 } : null;
    if (previousId !== user?.id) identityGeneration++;
    if (previousId !== user?.id) gameSettings.close();
    gameSettings.setUser(user);
    profile?.setUser(user);
    if (previousId !== user?.id) document.dispatchEvent(new CustomEvent(Events.AUTH_CHANGED, {
      detail: { user: user ? { ...user } : null },
    }));
    const label = userButton;
    usernameLabel.textContent = user?.username || "";
    updateAvatarImage(avatarImage, user?.avatar_id);
    label.setAttribute("aria-label", user ? `${user.username}，打开游戏设置` : "打开游戏设置");
    label.classList.toggle("hidden", !user);
    openButton.classList.toggle("hidden", Boolean(user));
    logoutButton.classList.toggle("hidden", !user);
    headerStatus.textContent = "";
  }

  /** 显示字段附近的错误，同时为读屏提供 invalid 状态。 */
  function fieldError(input, message) {
    $(input === username ? "#auth-username-error" : "#auth-password-error").textContent = message;
    input.setAttribute("aria-invalid", String(Boolean(message)));
  }

  /** 关闭会丢弃原目标；取消弹窗不会开始游戏或改变计时。 */
  function close() {
    generation += 1;
    pending = null;
    password.value = "";
    modal.close();
    returnFocus?.focus();
  }

  /** 原生 dialog 提供模态背景，额外处理 Tab 边界和焦点恢复。 */
  function open(afterLogin = null) {
    if (modal.open) return;
    returnFocus = document.activeElement;
    pending = afterLogin;
    status.textContent = "";
    fieldError(username, "");
    fieldError(password, "");
    modal.showModal();
    username.focus();
  }

  const ready = authRequest("me").then((value) => renderUser(value)).catch((error) => {
    if (error.status !== 401) headerStatus.textContent = "暂时无法恢复登录，可重试登录。";
  });

  openButton.addEventListener("click", () => { void ready.then(() => { if (!user) open(); }); });
  $(".auth-close").addEventListener("click", close);
  modal.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
  // 手机键盘或横竖屏改变可视区域后，把当前输入/按钮滚动到弹窗可见范围。
  window.visualViewport?.addEventListener("resize", () => {
    if (modal.open && modal.contains(document.activeElement)) {
      requestAnimationFrame(() => document.activeElement.scrollIntoView({ block: "nearest" }));
    }
  });
  modal.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const controls = [...modal.querySelectorAll("button:not(:disabled), input:not(:disabled)")];
    const first = controls[0];
    const last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  username.addEventListener("input", () => {
    $("#auth-count").textContent = `${usernameUnits(username.value) / 2} / 12`;
    fieldError(username, "");
  });
  password.addEventListener("input", () => fieldError(password, ""));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitting) return;
    const usernameError = validateUsername(username.value);
    const passwordError = validatePassword(password.value);
    fieldError(username, usernameError);
    fieldError(password, passwordError);
    if (usernameError || passwordError) { (usernameError ? username : password).focus(); return; }
    submitting = true;
    const current = generation;
    const submit = $(".auth-submit");
    submit.disabled = true;
    form.setAttribute("aria-busy", "true");
    submit.textContent = "正在登录…";
    status.textContent = "";
    try {
      const result = await authRequest("login", { method: "POST", body: { username: username.value, password: password.value } });
      renderUser(result.user);
      if (current === generation && modal.open) {
        const continueTo = pending;
        close();
        continueTo?.();
      }
    } catch (error) {
      if (current === generation && modal.open) {
        if (error.field === "username" || error.field === "password") fieldError(error.field === "username" ? username : password, error.message);
        else { status.textContent = error.message; status.focus(); }
      }
    } finally {
      submitting = false;
      password.value = "";
      submit.disabled = false;
      submit.innerHTML = '登录并继续 <span aria-hidden="true">→</span>';
      form.setAttribute("aria-busy", "false");
    }
  });
  logoutButton.addEventListener("click", async () => {
    // 注销启动即废弃旧身份检查，防止晚到的 /me 重新显示已退出账号。
    identityGeneration++;
    logoutButton.disabled = true;
    try { await authRequest("logout", { method: "POST" }); renderUser(null); openButton.focus(); }
    catch (error) { headerStatus.textContent = error.message; }
    finally { logoutButton.disabled = false; }
  });

  return {
    ready,
    /** 向首页个人记录提供公开用户信息，不返回 Cookie 或凭据。 */
    get currentUser() { return user ? { ...user } : null; },
    /** 仅在确认当前会话后续接原入口回调，错误时停在登录表单。 */
    async requireLogin(continuation) {
      await ready;
      const identity = identityGeneration;
      try {
        const value = await authRequest("me");
        if (identity !== identityGeneration) return;
        renderUser(value);
      }
      catch (error) {
        if (identity !== identityGeneration) return;
        if (error.status === 401) renderUser(null);
        open(continuation);
        if (error.status !== 401) status.textContent = "暂时无法确认登录状态，请重试登录。";
        return;
      }
      return continuation();
    },
  };
}

