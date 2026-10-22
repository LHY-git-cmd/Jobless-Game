/** 游戏流程协调：独立选关、账号与轮次隔离、规则计时及通关保存。 */
import { createSession, restartLevel, startLevel, completeLevel, levelSeconds, formatTime } from './session.js';
import { rankingRequest } from '../../features/ranking/client.js';
import { ChallengeClient } from './challenge-client.js';
import { clearProgress } from './progress.js';
import { getAudioSettings } from '../../features/audio/settings.js';
import { Events, emit } from '../../shared/events.js';
import { createScope } from '../../shared/lifecycle.js';
import { createHomePage } from './home.js';
import { createGameUi } from './ui.js';
import { createMineController } from '../mine/controller.js';
import { createSudokuController } from './sudoku-controller.js';
import { createAkariController } from './akari-controller.js';
import { createProgressCoordinator } from './progress-coordinator.js';
import { createResultDialog } from './result-dialog.js';

/** 显式创建页面实例；dom/view/request/storage 用于独立页面与真实流程测试。 */
export function createGameController({ dom = document, view = window, request = rankingRequest, storage, settings } = {}) {
  const scope = createScope();
  const { ui, byId } = createGameUi(dom);
  const challenge = new ChallengeClient(request);
  let session = createSession();
  let operationBusy = false, saveBusy = false, restoring = false, destroyed = false;
  let retryOperation = null, currentIndex = 0, currentUserId = null, development = false, quickEnabled = false;
  if (storage === undefined) {
    try { storage = view.localStorage; } catch { /* 禁用存储时游戏仍可使用。 */ }
  }
  const ruleControls = [
    { dialog: ui.mineRules, open: ui.mineRulesButton, close: ui.rulesClose, timing: ui.mineRulesTiming },
    { dialog: ui.akariRules, open: ui.akariRulesButton, close: ui.akariRulesClose, timing: ui.akariRulesTiming },
    { dialog: ui.sudokuRules, open: ui.sudokuRulesButton, close: ui.sudokuRulesClose, timing: ui.sudokuRulesTiming },
  ];
  const dialogIds = ['rules-dialog', 'akari-rules-dialog', 'sudoku-rules-dialog', 'result-dialog', 'settlement-dialog'];
  const screens = [ui.mineScreen, ui.akariScreen, ui.sudokuScreen];
  const quickButtons = [ui.mineQuick, ui.akariQuick, ui.sudokuQuick];

  /** 各关只上报棋局变化，统一更新显示计时与同步存档。 */
  function changed() { updateTimer(); persistProgress(); }

  const levels = [
    createMineController({ ui, dom, settings: settings ?? getAudioSettings(view), canPlay: () => canPlay(0),
      onChange: changed, onComplete: outcome => showResult(0, outcome), onBusyChange: syncProgressActions }),
    createAkariController({ ui, dom, canPlay: () => canPlay(1), onChange: changed, onComplete: () => showResult(1) }),
    createSudokuController({ ui, dom, canPlay: () => canPlay(2), onChange: changed, onComplete: () => showResult(2) }),
  ];
  const home = createHomePage({ ui, onEnter: enterFromHome });
  const result = createResultDialog({ ui, dom, onView: viewResult, onHome: returnHome,
    onPrimary: mode => { if (mode === 'mine-lost') void requestRestart(0); else if (mode.endsWith('won')) openSettlement(); },
    onRanking: () => { if (challenge.saved(currentIndex)) view.location.assign(`./ranking-${['mine', 'akari', 'sudoku'][currentIndex]}.html`); },
  });
  const progress = createProgressCoordinator({ storage, getUserId: () => currentUserId,
    canSave: () => !restoring && Boolean(challenge.state) && levels.some(level => level.state),
    getSnapshot: atHome => ({ currentIndex, game: levels[0].state, akari: levels[1].state, sudoku: levels[2].state,
      session, development, resultMode: result.mode, atHome, challenge: challenge.snapshot(),
      dialogs: dialogIds.filter(id => !byId[id].classList.contains('hidden')),
      messages: [ui.message.textContent, ui.akariMessage.textContent, ui.sudokuMessage.textContent] }),
    onFailure: () => recordStatus('浏览器无法保存游戏进度，请允许本站使用本地存储。'),
  });

  /** 首页读取当前轮或当前账号存档，展示层不直接依赖存储。 */
  function syncHomeEntries() {
    if (destroyed) return;
    const snapshot = challenge.state ? null : progress.load();
    home.sync({ state: challenge.state ?? snapshot?.challenge.state,
      levels: challenge.state ? session.levels : snapshot?.session.levels, busy: operationBusy });
  }

  /** 首次确认开始、规则关闭、当前轮有效后才允许操作棋盘。 */
  function canPlay(index) {
    return !destroyed && currentIndex === index && Boolean(challenge.state) && !operationBusy && !challenge.restartPayload &&
      session.levels[index].startedAt !== null && session.levels[index].seconds === null &&
      ruleControls[index].dialog.classList.contains('hidden') && ui.result.classList.contains('hidden');
  }

  /** 规则窗口展示状态，打开和重看不重置计时起点。 */
  function showRules(index) {
    refreshRuleText(index);
    ruleControls[index].dialog.classList.remove('hidden');
    ruleControls[index].close.focus(); syncProgressActions();
  }

  /** 结束状态由冻结成绩或扫雷失败判断。 */
  function refreshRuleText(index) {
    const controls = ruleControls[index];
    const ended = session.levels[index].seconds !== null || (index === 0 && levels[0].state?.status === 'lost');
    const started = session.levels[index].startedAt !== null;
    controls.close.textContent = ended ? '返回游戏' : started ? '继续游戏' : '开始游戏';
    controls.timing.textContent = ended ? '本局已结束，用时已固定。' : started ? '查看规则期间计时继续。' : '点击“开始游戏”后开始计时。';
  }

  /** 首次关闭明确启动计时；已开始后关闭只返回棋盘。 */
  function closeRules(index) {
    if (operationBusy || challenge.restartPayload || currentIndex !== index || !challenge.state ||
        ruleControls[index].dialog.classList.contains('hidden')) return;
    const started = session.levels[index].startedAt !== null;
    if (!(index === 0 && levels[0].state?.status === 'lost')) startLevel(session, index);
    if (index === 0) levels[0].start(session.levels[0].startedAt);
    ruleControls[index].dialog.classList.add('hidden');
    if (started) ruleControls[index].open.focus();
    else [ui.viewport, ui.akariBoard.querySelector('button:not(:disabled)'), ui.sudokuBoard.querySelector('button')][index]?.focus();
    updateTimer(); syncProgressActions();
  }

  /** 只更新文字，不每秒重画棋盘或向服务器请求。 */
  function updateTimer() {
    if (destroyed) return;
    ui.timer.textContent = formatTime(levelSeconds(session, 0, levels[0].state?.endedAt ?? Date.now()));
    ui.akariTimer.textContent = formatTime(levelSeconds(session, 1));
    ui.sudokuTimer.textContent = formatTime(levelSeconds(session, 2));
  }

  /** 所有持久化入口统一经过恢复/账号/实例生命周期检查。 */
  function persistProgress(atHome = false) { return progress.save(atHome); }

  /** 保存失败的重试入口在棋盘和结果弹窗同时显示。 */
  function recordStatus(message = '', retry = null) {
    if (destroyed) return;
    ui.challengeMessage.textContent = ui.saveStatus.textContent = message;
    ui.challengeStatus.classList[message ? 'remove' : 'add']('hidden');
    [ui.challengeRetry, ui.saveRetry].forEach(node => node.classList[retry ? 'remove' : 'add']('hidden'));
    retryOperation = retry;
  }

  /** 服务端确认保存后开放结算，同步记录可恢复的按钮/弹窗状态。 */
  function syncProgressActions() {
    if (destroyed) return;
    [ui.mineNext, ui.akariNext, ui.settlementOpen].forEach((node, index) => { node.disabled = !challenge.saved(index) || operationBusy; });
    if (result.mode.endsWith('won')) ui.resultPrimary.disabled = !challenge.saved(currentIndex) || operationBusy;
    ui.settlementRanking.disabled = !challenge.saved(currentIndex) || operationBusy;
    ui.sudokuNotes.disabled = !levels[2].state || !canPlay(2);
    quickButtons.forEach((node, index) => {
      node.classList[quickEnabled ? 'remove' : 'add']('hidden');
      node.disabled = saveBusy || !canPlay(index);
      ruleControls[index].open.disabled = operationBusy || currentIndex !== index || !levels[index].state ||
        !ui.result.classList.contains('hidden') || levels[0].busy;
    });
    persistProgress(); syncHomeEntries();
  }

  /** 客户端冻结原负载；离开或换号后旧响应不得操作新页面。 */
  async function persistCompletion() {
    if (saveBusy || !challenge.state || challenge.saved(currentIndex)) return;
    const index = currentIndex, generation = challenge.generation;
    saveBusy = true; recordStatus('正在保存通关记录…'); syncProgressActions();
    try {
      const pending = challenge.complete(index, session.levels[index].seconds, development);
      persistProgress(); await pending;
      emit(Events.RECORDS_UPDATED, undefined, dom); recordStatus('通关记录已保存，可查看本关排行。');
    } catch (error) {
      if (generation === challenge.generation) recordStatus(error.message, persistCompletion);
    } finally {
      if (generation === challenge.generation) { saveBusy = false; syncProgressActions(); }
    }
  }

  /** 重开先获得服务端确认，再清空本关；失败保留原请求和棋盘。 */
  async function requestRestart(index) {
    if (operationBusy || saveBusy) return;
    const generation = challenge.generation;
    operationBusy = true; syncProgressActions(); recordStatus('正在重新开始…');
    try {
      const pending = challenge.restart(index);
      persistProgress(); await pending;
      development = false; restart(index); recordStatus();
    } catch (error) {
      if (generation === challenge.generation) recordStatus(error.message, () => requestRestart(index));
    } finally {
      if (generation === challenge.generation) { operationBusy = false; syncProgressActions(); }
    }
  }

  /** 新局隐藏其他关首次规则及旧结算入口。 */
  function resetCompletionActions() {
    ruleControls.forEach(({ dialog }) => dialog.classList.add('hidden'));
    result.resetActions();
  }

  /** 当前关计时重置，其他关状态保留。 */
  function restart(index) {
    restartLevel(session, index); resetCompletionActions(); ui.result.classList.add('hidden');
    levels[index].reset(); showRules(index);
  }

  /** 切换可见屏幕，不创建或清空其他棋盘。 */
  function showScreen(index) {
    ui.landing.classList.add('hidden');
    screens.forEach((screen, position) => screen.classList[position === index ? 'remove' : 'add']('hidden'));
    view.scrollTo(0, 0);
  }

  /** 新关先读规则，已有棋盘直接查看，扫雷音频在用户手势内解锁。 */
  function enter(index) {
    if (operationBusy || saveBusy || challenge.restartPayload || !challenge.canEnter(index)) return;
    if (levels[index].state || challenge.saved(index)) { viewExistingLevel(index); return; }
    currentIndex = index; development = false;
    if (index === 0) levels[0].unlock();
    else { recordStatus(); levels[0].stopEffects(); }
    restart(index); showScreen(index); syncProgressActions();
  }

  /** 兼容旧存档缺少前关棋盘但已有保存成绩的情况。 */
  function viewExistingLevel(index) {
    currentIndex = index; result.clear(); recordStatus(); levels[0].stopEffects();
    dialogIds.forEach(id => byId[id].classList.add('hidden'));
    resetCompletionActions(); showScreen(index);
    const board = levels[index].state;
    if (!board) {
      [ui.board, ui.akariBoard, ui.sudokuBoard][index].replaceChildren(dom.createDocumentFragment());
      ui.flag.disabled = ui.reveal.disabled = true;
    }
    levels[index].render();
    if (challenge.saved(index) || (index === 0 ? board?.status === 'won' : board?.complete)) showResult(index);
    else if (index === 0 && board?.status === 'lost') showResult(0, 'lost');
    else if (session.levels[index].startedAt === null) showRules(index);
    updateTimer(); syncProgressActions();
  }

  /** 返回前保存当前账号完整棋局，再废弃请求轮次和内存状态。 */
  function returnHome() {
    persistProgress(true); emit(Events.SETTLEMENT_CLOSED, undefined, dom); challenge.reset();
    operationBusy = saveBusy = false; development = false; recordStatus(); resetCompletionActions();
    levels.forEach(level => level.clear()); result.clear(); session = createSession();
    screens.forEach(screen => screen.classList.add('hidden'));
    ui.landing.classList.remove('hidden'); syncHomeEntries(); ui.startButton.focus(); view.scrollTo(0, 0);
  }

  /** 统一冻结成绩并展示结果，展示模块不直接请求接口。 */
  function showResult(index, outcome = 'won') {
    if (outcome === 'won') completeLevel(session, index);
    updateTimer(); result.show(index, outcome, session.levels[index].seconds);
    if (outcome === 'won') void persistCompletion();
    syncProgressActions();
  }

  /** 当前关保存完成后才可进入结算。 */
  function openSettlement() {
    if (!challenge.saved(currentIndex) || saveBusy || operationBusy) return;
    result.settlement(currentIndex, challenge.state.levels[currentIndex]); persistProgress();
  }

  /** 关闭弹窗后保留终盘及失败重试入口。 */
  function viewResult() { result.view(); syncProgressActions(); }

  /** 恢复前核对轮次和尝试编号，未确认重开沿用原幂等请求。 */
  async function restoreProgress(snapshot) {
    challenge.restore(snapshot.challenge);
    const generation = challenge.generation;
    operationBusy = true; syncHomeEntries(); recordStatus('正在恢复游戏进度…');
    try {
      const state = await challenge.resume(), pendingRestart = snapshot.challenge.restartPayload;
      if (!pendingRestart && (state.revision !== snapshot.challenge.state.revision ||
          state.levels.some((level, index) => level.attempt_id !== snapshot.challenge.state.levels[index].attempt_id))) {
        throw Object.assign(new Error('本轮已在其他页面重新开始，请从首页开启新一轮。'), { status: 409 });
      }
      if (pendingRestart) await challenge.restart(['mine', 'akari', 'sudoku'].indexOf(pendingRestart.category));
      if (generation !== challenge.generation) return false;
      restoring = true;
      ({ session, currentIndex, development } = snapshot);
      [snapshot.game, snapshot.akari, snapshot.sudoku].forEach((board, index) => levels[index].restore(board));
      // 已确认成绩必须冻结，响应丢失后的离开时间不能继续计入。
      challenge.state.levels.forEach((level, index) => { if (level.seconds !== null) session.levels[index].seconds = level.seconds; });
      result.clear(); dialogIds.forEach(id => byId[id].classList.add('hidden')); resetCompletionActions(); showScreen(currentIndex);
      if (pendingRestart) { development = false; restart(currentIndex); }
      else {
        levels[currentIndex].render();
        const board = levels[currentIndex].state;
        const completed = challenge.saved(currentIndex) || (currentIndex === 0 ? board?.status === 'won' : board?.complete);
        if (completed || (currentIndex === 0 && board?.status === 'lost')) {
          showResult(currentIndex, currentIndex === 0 ? board?.status ?? 'won' : 'won');
          if (!snapshot.dialogs.includes('result-dialog') && snapshot.resultMode) viewResult();
        }
        for (const id of snapshot.dialogs) if (dialogIds.includes(id) && id !== 'settlement-dialog') byId[id].classList.remove('hidden');
        if (!completed && !(currentIndex === 0 && board?.status === 'lost') && session.levels[currentIndex].startedAt === null) showRules(currentIndex);
        refreshRuleText(currentIndex);
        if (!ruleControls[currentIndex].dialog.classList.contains('hidden')) ruleControls[currentIndex].close.focus();
        if (snapshot.dialogs.includes('settlement-dialog')) openSettlement();
        [ui.message, ui.akariMessage, ui.sudokuMessage].forEach((node, index) => { node.textContent = snapshot.messages?.[index] ?? ''; });
      }
      if (!saveBusy) recordStatus();
      return true;
    } catch (error) {
      if (generation !== challenge.generation) return false;
      restoring = false; challenge.reset(); operationBusy = false;
      if (error.status === 409) { clearProgress(storage, currentUserId); recordStatus(error.message); }
      else recordStatus(error.message, () => restoreProgress(snapshot));
      return false;
    } finally {
      if (generation === challenge.generation) { restoring = false; operationBusy = false; syncProgressActions(); }
      syncHomeEntries();
    }
  }

  /** 无存档创建挑战，有存档先完整恢复再进入所选关。 */
  async function enterFromHome(index) {
    if (operationBusy || ui.landing.classList.contains('hidden')) return;
    const snapshot = progress.load();
    if (snapshot) {
      if (!await restoreProgress(snapshot)) return;
      if (currentIndex !== index) enter(index);
      return;
    }
    operationBusy = true; syncHomeEntries();
    const generation = challenge.generation;
    recordStatus('正在创建挑战…');
    try {
      await challenge.start(); recordStatus(); development = false; operationBusy = false; enter(index);
    } catch (error) { if (generation === challenge.generation) recordStatus(error.message); }
    finally { if (generation === challenge.generation) { operationBusy = false; syncProgressActions(); } }
  }

  /** 开发求解器按需加载，离开或换号后不接受旧求解结果。 */
  async function quickComplete() {
    if (!quickEnabled || !canPlay(currentIndex) || saveBusy || !challenge.canEnter(currentIndex)) return;
    const index = currentIndex, generation = challenge.generation;
    operationBusy = true; syncProgressActions();
    try {
      const { solveCurrentLevel } = await import('./dev-quick-complete.js');
      if (generation !== challenge.generation) return;
      development = true; solveCurrentLevel(index, levels[index].state); levels[index].render(); showResult(index);
    } catch (error) { if (generation === challenge.generation) recordStatus(error.message); }
    finally { if (generation === challenge.generation) { operationBusy = false; syncProgressActions(); } }
  }

  /** 键盘规则确认与按钮共用判断，数字键交给数独控制器。 */
  function handleKey(event) {
    const activeDialog = [ui.settlementDialog, ...ruleControls.map(controls => controls.dialog)].find(dialog => !dialog.classList.contains('hidden'));
    if (activeDialog && event.key === 'Tab') { result.trapFocus(event, activeDialog); return; }
    if (event.key === 'Escape') {
      const index = ruleControls.findIndex(controls => !controls.dialog.classList.contains('hidden'));
      if (index !== -1) {
        if (session.levels[index].startedAt !== null || session.levels[index].seconds !== null) closeRules(index);
        else event.preventDefault();
        return;
      }
      if (!ui.settlementDialog.classList.contains('hidden')) {
        ui.settlementDialog.classList.add('hidden'); emit(Events.SETTLEMENT_CLOSED, undefined, dom); viewResult(); return;
      }
      if (!ui.result.classList.contains('hidden')) viewResult();
    } else if (levels[2].state && !ui.sudokuScreen.classList.contains('hidden') && ui.sudokuRules.classList.contains('hidden') && ui.result.classList.contains('hidden')) {
      if (/^[1-9]$/.test(event.key)) levels[2].input(Number(event.key));
      else if (event.key === 'Backspace' || event.key === 'Delete') levels[2].input(0);
    }
  }

  [ui.backButton, ui.akariBack, ui.sudokuBack].forEach(node => scope.listen(node, 'click', returnHome));
  [ui.restartButton, ui.akariRestart, ui.sudokuRestart].forEach((node, index) => scope.listen(node, 'click', () => requestRestart(index)));
  [ui.mineNext, ui.akariNext, ui.settlementOpen].forEach(node => scope.listen(node, 'click', openSettlement));
  [ui.challengeRetry, ui.saveRetry].forEach(node => scope.listen(node, 'click', () => { void retryOperation?.(); }));
  quickButtons.forEach(node => scope.listen(node, 'click', quickComplete));
  ruleControls.forEach((controls, index) => {
    scope.listen(controls.open, 'click', () => { if (!controls.open.disabled) showRules(index); });
    scope.listen(controls.close, 'click', () => closeRules(index));
  });
  scope.listen(dom, Events.AUTH_CHANGED, event => {
    const nextUserId = event?.detail?.user?.id ?? null;
    if (nextUserId === currentUserId) return;
    returnHome(); currentUserId = nextUserId; syncHomeEntries();
    const snapshot = progress.load();
    if (snapshot && !snapshot.atHome) void restoreProgress(snapshot);
  });
  scope.listen(dom, 'keydown', handleKey);
  scope.listen(dom, 'click', () => persistProgress());
  scope.listen(dom, 'keyup', () => persistProgress());
  scope.listen(dom, 'visibilitychange', () => { if (dom.visibilityState === 'hidden') persistProgress(); else updateTimer(); });
  scope.listen(view, 'pagehide', () => persistProgress());
  scope.listen(view, 'pageshow', updateTimer);
  const timer = view.setInterval(updateTimer, 1000);
  scope.add(() => view.clearInterval(timer));
  // 配置失败只隐藏开发按钮；guard 阻止销毁后回包触碰旧页面。
  void request('challenges/config').then(scope.guard(config => { quickEnabled = config.quick_complete_enabled === true; syncProgressActions(); })).catch(() => {});
  syncHomeEntries();
  return {
    /** 刷新模拟和宿主卸载先保存，再使旧异步任务及所有资源失效。 */
    destroy() {
      if (destroyed) return;
      persistProgress(); destroyed = true; challenge.reset();
      scope.dispose(); home.destroy(); result.destroy(); progress.destroy(); levels.forEach(level => level.destroy());
    },
  };
}
