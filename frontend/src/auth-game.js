/** 首页三关与重新挑战的登录拦截，以及个人通关记录的账号状态接入。 */
import { initAuth } from "./auth.js?v=20261019-audio-settings";
import { initPersonalRecords } from "./personal-records.js";

const auth = initAuth();
initPersonalRecords({ onLogin: continuation => auth.requireLogin(() => continuation(auth.currentUser)) });
for (const id of ["start-button", "akari-entry", "sudoku-entry", "challenge-action"]) {
  const button = document.getElementById(id);
  let checking = false;
  button.addEventListener("click", async () => {
    // 尚未开始挑战时，该按钮只负责滚动到关卡选择，无需登录。
    if (id === "challenge-action" && button.dataset.action !== "restart") return;
    if (checking) return;
    checking = true;
    button.setAttribute("aria-busy", "true");
    try { await auth.requireLogin(() => button.dispatchEvent(new Event("authorized-start"))); }
    finally { checking = false; button.setAttribute("aria-busy", "false"); }
  });
}
