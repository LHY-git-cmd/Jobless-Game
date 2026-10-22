/** 结果与单关结算展示；计时、保存、重开和导航由注入回调决定。 */
import { formatTime } from './session.js';
import { Events, emit } from '../../shared/events.js';
import { createScope } from '../../shared/lifecycle.js';

/** 外层注入按钮行为与当前文档，避免展示模块导入游戏或请求模块。 */
export function createResultDialog({ ui, dom, onPrimary, onView, onHome, onRanking }) {
  const scope = createScope();
  let mode = '';
  scope.listen(ui.resultPrimary, 'click', () => onPrimary(mode));
  scope.listen(ui.resultSecondary, 'click', onView);
  scope.listen(ui.settlementHome, 'click', onHome);
  scope.listen(ui.settlementRanking, 'click', onRanking);
  return {
    /** 外层存档读取展示模式，不允许绕过统一展示流程修改。 */
    get mode() { return mode; },
    /** 通关秒数由外层冻结后传入；失败展示不提交成绩。 */
    show(index, outcome, seconds) {
      mode = `${['mine', 'akari', 'sudoku'][index]}-${outcome}`;
      ui.resultTitle.textContent = index === 2 ? '恭喜你，挑战完成！' : `${index === 0 ? '第一' : '第二'}关通关成功`;
      ui.resultDescription.textContent = index === 0 ? `已排开全部 90 个安全格，用时 ${formatTime(seconds)}。`
        : index === 1 ? `所有可放灯格已照亮，数字线索也全部满足，用时 ${formatTime(seconds)}。`
        : `你已完成数独挑战，用时 ${formatTime(seconds)}。`;
      ui.resultPrimary.textContent = '查看本关结算';
      ui.resultSecondary.textContent = '查看结果';
      if (outcome === 'lost') {
        ui.resultTitle.textContent = '游戏失败';
        ui.resultDescription.textContent = '地雷连锁爆炸，全部地雷已显示。可以查看棋盘，或重新开始。';
        ui.resultPrimary.textContent = '重新开始';
        ui.resultSecondary.textContent = '查看棋盘';
      }
      ui.result.classList.remove('hidden');
      ui.resultPrimary.disabled = false;
      ui.resultPrimary.focus();
    },
    /** 隐藏结果保留终盘，并聚焦相应的单关结算入口。 */
    view() {
      ui.result.classList.add('hidden');
      const next = { 'mine-won': ui.mineNext, 'akari-won': ui.akariNext, 'sudoku-won': ui.settlementOpen }[mode];
      if (next) {
        next.classList.remove('hidden');
        if (mode === 'mine-won') ui.message.textContent = '通关成功，已排开全部安全格。';
        next.focus();
      } else ui.viewport.focus();
    },
    /** 展示已由服务端确认的当前关成绩，尝试编号用于胜利音乐去重。 */
    settlement(index, level) {
      ui.result.classList.add('hidden');
      ui.settlementTitle.textContent = `${['扫雷', '照明', '数独'][index]}通关结算`;
      ui.settlementNote.textContent = '本关成绩已保存，可返回首页选择其他挑战。';
      ui.settlementTime.textContent = formatTime(level.seconds);
      ui.settlementDialog.classList.remove('hidden');
      emit(Events.SETTLEMENT_OPENED, { runId: level.attempt_id }, dom);
      ui.settlementHome.focus();
    },
    /** 新局和切关隐藏旧结算入口；保留当前模式直到外层显式清空。 */
    resetActions() {
      [ui.mineNext, ui.akariNext, ui.settlementOpen, ui.settlementDialog].forEach(node => node.classList.add('hidden'));
    },
    /** 返回首页或恢复棋局时清除旧模式。 */
    clear() { mode = ''; ui.result.classList.add('hidden'); },
    /** Tab 在规则或结算窗口内循环，避免焦点落到背后棋盘。 */
    trapFocus(event, dialog) {
      const controls = [...dialog.querySelectorAll('button:not(:disabled)')];
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && dom.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && dom.activeElement === last) { event.preventDefault(); first?.focus(); }
    },
    /** 清理弹窗按钮监听，不触发业务导航。 */
    destroy() { scope.dispose(); },
  };
}
