/** 将三个首页关卡入口接到共享登录控制器，通过授权事件续接原游戏流程。 */
import { initAuth } from "./auth.js";

const auth = initAuth();
for (const id of ["start-button"]) {
  const button = document.getElementById(id);
  let checking = false;
  button.addEventListener("click", async () => {
    if (checking) return;
    checking = true;
    button.setAttribute("aria-busy", "true");
    try { await auth.requireLogin(() => button.dispatchEvent(new Event("authorized-start"))); }
    finally { checking = false; button.setAttribute("aria-busy", "false"); }
  });
}
