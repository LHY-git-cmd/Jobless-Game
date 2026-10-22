/** 首页三关的登录拦截，以及个人通关记录的账号状态接入。 */
import { Events } from "../shared/events.js";
import { initAuth } from "../features/account/auth.js";
import { initPersonalRecords } from "../features/ranking/personal-records.js";

const auth = initAuth();
initPersonalRecords({ onLogin: continuation => auth.requireLogin(() => continuation(auth.currentUser)) });
for (const id of ["start-button", "akari-entry", "sudoku-entry"]) {
  const button = document.getElementById(id);
  let checking = false;
  button.addEventListener("click", async () => {
    if (checking) return;
    checking = true;
    button.setAttribute("aria-busy", "true");
    try { await auth.requireLogin(() => button.dispatchEvent(new Event(Events.AUTHORIZED_START))); }
    finally { checking = false; button.setAttribute("aria-busy", "false"); }
  });
}
