/** 首页只装配账号和新版选关入口；不再启动或恢复旧三个单关。 */
import { initAuth } from '../features/account/auth.js';

initAuth();

/** 介绍区按钮只滚动到三个入口，不创建游戏或改动已有存档。 */
document.getElementById('challenge-action').addEventListener('click', () => {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.getElementById('level-select').scrollIntoView({ behavior: reduced ? 'instant' : 'smooth', block: 'start' });
});
