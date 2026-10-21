/** 首页只装配账号、历史记录和新版选关入口；不再启动或恢复旧三个单关。 */
import { initAuth } from './auth.js';
import { initPersonalRecords } from './personal-records.js';

const auth = initAuth();
initPersonalRecords({ onLogin: continuation => auth.requireLogin(() => continuation(auth.currentUser)) });

/** 介绍区按钮只滚动到三个入口，不创建游戏或改动已有存档。 */
document.getElementById('challenge-action').addEventListener('click', () => {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.getElementById('level-select').scrollIntoView({ behavior: reduced ? 'instant' : 'smooth', block: 'start' });
});
