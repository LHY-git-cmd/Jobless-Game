/** 首页入口：展示开始/继续/已通关状态，通过回调报告选关。 */
import { Events } from '../lib/events.js';
import { createScope } from '../lib/lifecycle.js';

/** ui 已由页面统一缓存；业务账号和挑战状态由外层提供。 */
export function createHomePage({ ui, onEnter }) {
  const scope = createScope();
  const entries = [
    { button: ui.startButton, status: ui.mineEntryStatus, name: '第一关扫雷' },
    { button: ui.akariEntry, status: ui.akariEntryStatus, name: '第二关照明' },
    { button: ui.sudokuEntry, status: ui.sudokuEntryStatus, name: '第三关数独' },
  ];
  scope.listen(ui.challengeAction, 'click', () => {
    if (ui.challengeAction.dataset.action === 'select') ui.levelSelect.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  entries.forEach((entry, index) => scope.listen(entry.button, Events.AUTHORIZED_START, () => onEnter(index)));
  return {
    /** 首页面板只读取状态，不创建请求或直接读写存档。 */
    sync({ state, levels, busy }) {
      entries.forEach((entry, index) => {
        const completed = state?.levels[index].seconds != null;
        const started = levels?.[index].startedAt != null;
        const label = completed ? '已通关' : started ? '继续游戏' : '开始游戏';
        entry.status.textContent = label;
        entry.button.disabled = busy;
        entry.button.setAttribute('aria-label', `${entry.name}，${completed ? '查看通关结果' : label}`);
      });
      ui.challengeAction.dataset.action = 'select';
      ui.challengeActionLabel.textContent = '选择你的挑战';
      ui.challengeActionIcon.textContent = '↓';
      ui.challengeAction.disabled = busy;
      ui.challengeAction.setAttribute('aria-busy', String(busy));
    },
    /** 解除首页事件绑定。 */
    destroy() { scope.dispose(); },
  };
}
