/** 首页与闯关游戏目录共享账号装配；通过原生链接进入模式和关卡。 */
import { initAuth } from '../features/account/auth.js';

initAuth();

/** 首页介绍区滚动到模式入口；闯关目录没有此按钮。 */
document.getElementById('challenge-action')?.addEventListener('click', () => {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.getElementById('level-select').scrollIntoView({ behavior: reduced ? 'instant' : 'smooth', block: 'start' });
});
