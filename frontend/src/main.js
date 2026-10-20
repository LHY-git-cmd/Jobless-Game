/**
 * 无职游戏页面入口：管理扫雷、数独、照明三关与对应的规则弹窗。
 * 三个关卡独立开放；按账号保存棋局，离开期间计时继续累计。
 */
import { Events } from "./lib/events.js";

import { createGame, revealSelected, selectCell, toggleFlag } from "./game.js";
import { createSudoku, selectSudokuCell, setSudokuValue, toggleSudokuNote, sudokuConflicts, checkSudoku } from "./sudoku.js";
import { AKARI_SIZE, akariCell, createAkari, inspectAkari, toggleBulb } from "./akari.js";
import { createExplosionSequence, createExplosionSound, explosionOrder } from "./mine-effects.js";
import { getAudioSettings } from "./audio-settings.js";
import { createSession, restartLevel, startLevel, completeLevel, levelSeconds, formatTime } from "./session.js";
import { ChallengeClient, rankingRequest } from "./ranking-client.js";
import { loadProgress, saveProgress, clearProgress } from "./progress.js";

const $ = (id) => document.getElementById(id);
const ui = {
  landing: $("landing"), mineScreen: $("game-screen"), board: $("board"),
  viewport: $("board-viewport"), caption: $("board-caption"),
  minesLeft: $("mines-left"), cleared: $("cleared-count"), timer: $("timer"),
  selection: $("selection-label"), flag: $("flag-button"), reveal: $("reveal-button"),
  message: $("game-message"), mineRules: $("rules-dialog"),
  sudokuEntry: $("sudoku-entry"), sudokuScreen: $("sudoku-screen"),
  sudokuBoard: $("sudoku-board"), sudokuKeypad: $("sudoku-keypad"),
  sudokuSelection: $("sudoku-selection"), sudokuMessage: $("sudoku-message"),
  sudokuClear: $("sudoku-clear"), sudokuCheck: $("sudoku-check"),
  sudokuNotes: $("sudoku-notes-toggle"), sudokuInputHint: $("sudoku-input-hint"),
  sudokuRules: $("sudoku-rules-dialog"),
  akariEntry: $("akari-entry"), akariScreen: $("akari-screen"),
  akariBoard: $("akari-board"), akariStatus: $("akari-status"),
  akariMessage: $("akari-message"), akariRules: $("akari-rules-dialog"),
  result: $("result-dialog"), resultTitle: $("result-title"),
  resultDescription: $("result-description"), resultPrimary: $("result-primary"),
  resultSecondary: $("result-secondary"),
};

let game = null;
let sudoku = null;
let akari = null;
let resultMode = "";
let mineExplosion = null;
let session = createSession();
const challenge = new ChallengeClient();
let operationBusy = false;
let saveBusy = false;
let retryOperation = null;
let currentIndex = 0;
let quickEnabled = false;
let development = false;
let currentUserId = null;
let restoring = false;
let progressStorage;
try { progressStorage = window.localStorage; } catch { /* 存储不可用时保留正常游戏操作。 */ }
const dialogIds = ["rules-dialog", "akari-rules-dialog", "sudoku-rules-dialog", "result-dialog", "settlement-dialog"];
const ruleControls = [
  { dialog: ui.mineRules, open: $("mine-rules"), close: $("rules-close"), timing: $("mine-rules-timing") },
  { dialog: ui.akariRules, open: $("akari-rules"), close: $("akari-rules-close"), timing: $("akari-rules-timing") },
  { dialog: ui.sudokuRules, open: $("sudoku-rules"), close: $("sudoku-rules-close"), timing: $("sudoku-rules-timing") },
];
const homeEntries = [
  { button: $("start-button"), status: $("mine-entry-status"), name: "第一关扫雷" },
  { button: ui.akariEntry, status: $("akari-entry-status"), name: "第二关照明" },
  { button: ui.sudokuEntry, status: $("sudoku-entry-status"), name: "第三关数独" },
];

/** 三关始终开放，各入口按当前账号存档展示开始、继续或已通关。 */
function syncHomeEntries() {
  const snapshot = challenge.state ? null : loadProgress(progressStorage, currentUserId);
  const state = challenge.state ?? snapshot?.challenge.state;
  const levels = challenge.state ? session.levels : snapshot?.session.levels;
  homeEntries.forEach((entry, index) => {
    const completed = state?.levels[index].seconds != null;
    const started = levels?.[index].startedAt != null;
    const label = completed ? "已通关" : started ? "继续游戏" : "开始游戏";
    entry.status.textContent = label;
    entry.button.disabled = operationBusy;
    entry.button.setAttribute("aria-label", `${entry.name}，${completed ? "查看通关结果" : label}`);
  });
  $("challenge-action").dataset.action = "select";
  $("challenge-action-label").textContent = "选择你的挑战";
  $("challenge-action-icon").textContent = "↓";
  $("challenge-action").disabled = operationBusy;
  $("challenge-action").setAttribute("aria-busy", String(operationBusy));
}

/** 只有确认开始且规则窗口已关闭时才能操作棋盘，不能绕过开始按钮起计时。 */
function canPlay(index) {
  return currentIndex === index && Boolean(challenge.state) && !operationBusy && !challenge.restartPayload &&
    session.levels[index].startedAt !== null && session.levels[index].seconds === null &&
    ruleControls[index].dialog.classList.contains("hidden") && ui.result.classList.contains("hidden");
}

/** 规则窗口按未开始、进行中和已结束显示操作文字，不修改已有计时起点。 */
function refreshRuleText(index) {
  const controls = ruleControls[index];
  const ended = session.levels[index].seconds !== null || (index === 0 && game?.status === "lost");
  const started = session.levels[index].startedAt !== null;
  controls.close.textContent = ended ? "返回游戏" : started ? "继续游戏" : "开始游戏";
  controls.timing.textContent = ended ? "本局已结束，用时已固定。" : started
    ? "查看规则期间计时继续。" : "点击“开始游戏”后开始计时。";
}

/** 复用各关规则窗口；打开窗口本身不启动、暂停或重置计时。 */
function showRules(index) {
  refreshRuleText(index);
  ruleControls[index].dialog.classList.remove("hidden");
  ruleControls[index].close.focus();
  syncProgressActions();
}

/** 首次点击开始立即计时；重看规则后关闭只返回棋盘，保留原始起点。 */
function closeRules(index) {
  if (operationBusy || challenge.restartPayload || currentIndex !== index || !challenge.state ||
      ruleControls[index].dialog.classList.contains("hidden")) return;
  const started = session.levels[index].startedAt !== null;
  if (!(index === 0 && game?.status === "lost")) startLevel(session, index);
  if (index === 0 && game && game.startedAt === null) game.startedAt = session.levels[0].startedAt;
  ruleControls[index].dialog.classList.add("hidden");
  if (started) ruleControls[index].open.focus();
  else [ui.viewport, ui.akariBoard.querySelector("button:not(:disabled)"), ui.sudokuBoard.querySelector("button")][index]?.focus();
  updateTimer();
  syncProgressActions();
}

/** 每次棋局变化同步落盘，不依赖可能不会触发的页面退出事件。 */
function persistProgress(atHome = false) {
  if (restoring || !challenge.state || !(game || akari || sudoku) || currentUserId === null) return;
  const saved = saveProgress(progressStorage, currentUserId, {
    currentIndex, game, akari, sudoku, session, development, resultMode, atHome,
    challenge: challenge.snapshot(),
    dialogs: dialogIds.filter(id => !$(id).classList.contains("hidden")),
    messages: [ui.message.textContent, ui.akariMessage.textContent, ui.sudokuMessage.textContent],
  });
  if (!saved) recordStatus("浏览器无法保存游戏进度，请允许本站使用本地存储。");
}

/** 恢复同账号棋盘前核对服务端轮次，网络失败保留存档并允许原样重试。 */
async function restoreProgress(snapshot) {
  challenge.restore(snapshot.challenge);
  const generation = challenge.generation;
  operationBusy = true;
  $("start-button").disabled = true;
  syncHomeEntries();
  recordStatus("正在恢复游戏进度…");
  try {
    const state = await challenge.resume();
    const restart = snapshot.challenge.restartPayload;
    // 重开请求可能已到达服务器，必须用原请求编号确认后再创建新棋盘。
    if (!restart && (state.revision !== snapshot.challenge.state.revision ||
        state.levels.some((level, index) => level.attempt_id !== snapshot.challenge.state.levels[index].attempt_id))) {
      const error = new Error("本轮已在其他页面重新开始，请从首页开启新一轮。");
      error.status = 409;
      throw error;
    }
    if (restart) await challenge.restart(["mine", "akari", "sudoku"].indexOf(restart.category));
    if (generation !== challenge.generation) return false;
    restoring = true;
    ({ game, akari, sudoku, session, currentIndex, development } = snapshot);
    // 已落库的成绩使用服务端冻结值，响应丢失后恢复也不能把离开时间计入已通关关卡。
    challenge.state.levels.forEach((level, index) => {
      if (level.seconds !== null) session.levels[index].seconds = level.seconds;
    });
    resultMode = "";
    dialogIds.forEach(id => $(id).classList.add("hidden"));
    resetCompletionActions();
    cancelMineExplosion();
    ui.landing.classList.add("hidden");
    [ui.mineScreen, ui.akariScreen, ui.sudokuScreen].forEach((screen, index) =>
      screen.classList[index === currentIndex ? "remove" : "add"]("hidden"));
    if (restart) {
      development = false;
      [restartGame, restartAkari, restartSudoku][currentIndex]();
    } else {
      if (game?.status === "lost") {
        const mines = game.cells.flatMap((cell, index) => cell.mine ? [index] : []);
        mineExplosion = { revealed: new Set(mines), exploded: new Set(mines), settled: new Set(mines), running: false };
      }
      [renderMine, renderAkari, renderSudoku][currentIndex]();
      const activeBoard = [game, akari, sudoku][currentIndex];
      const completed = challenge.saved(currentIndex) || (currentIndex === 0 ? game?.status === "won" : activeBoard?.complete);
      if (completed || (currentIndex === 0 && game?.status === "lost")) {
        [() => showMineResult(game?.status ?? "won"), showAkariResult, showSudokuResult][currentIndex]();
        if (!snapshot.dialogs.includes("result-dialog") && snapshot.resultMode) viewResult();
      }
      for (const id of snapshot.dialogs) {
        if (dialogIds.includes(id) && id !== "settlement-dialog") $(id).classList.remove("hidden");
      }
      // 兼容旧版本未操作且已关闭规则的存档，仍须明确点击开始后才起计时。
      if (!completed && !(currentIndex === 0 && game?.status === "lost") && session.levels[currentIndex].startedAt === null) showRules(currentIndex);
      refreshRuleText(currentIndex);
      if (!ruleControls[currentIndex].dialog.classList.contains("hidden")) ruleControls[currentIndex].close.focus();
      if (snapshot.dialogs.includes("settlement-dialog")) openSettlement();
      [ui.message, ui.akariMessage, ui.sudokuMessage].forEach((node, index) => {
        node.textContent = snapshot.messages?.[index] ?? "";
      });
    }
    if (!saveBusy) recordStatus();
    return true;
  } catch (error) {
    if (generation !== challenge.generation) return false;
    restoring = false;
    challenge.reset();
    operationBusy = false;
    if (error.status === 409) {
      clearProgress(progressStorage, currentUserId);
      recordStatus(error.message);
    } else recordStatus(error.message, () => restoreProgress(snapshot));
    return false;
  } finally {
    if (generation === challenge.generation) {
      restoring = false;
      operationBusy = false;
      syncProgressActions();
      $("start-button").disabled = false;
    } else if (!operationBusy) $("start-button").disabled = false;
    syncHomeEntries();
  }
}

/** 保存提示在结果弹窗和棋盘外同步显示，离开弹窗后也能重试。 */
function recordStatus(message = "", retry = null) {
  $("challenge-message").textContent = message;
  $("challenge-status").classList[message ? "remove" : "add"]("hidden");
  $("save-status").textContent = message;
  $("challenge-retry").classList[retry ? "remove" : "add"]("hidden");
  $("save-retry").classList[retry ? "remove" : "add"]("hidden");
  retryOperation = retry;
}

/** 只有服务端已经接收本关才开启本关结算，其他关始终可从首页进入。 */
function syncProgressActions() {
  $("mine-next").disabled = !challenge.saved(0) || operationBusy;
  $("akari-next").disabled = !challenge.saved(1) || operationBusy;
  $("settlement-open").disabled = !challenge.saved(2) || operationBusy;
  if (resultMode.endsWith("won")) ui.resultPrimary.disabled = !challenge.saved(currentIndex) || operationBusy;
  $("settlement-ranking").disabled = !challenge.saved(currentIndex) || operationBusy;
  ui.sudokuNotes.disabled = !sudoku || !canPlay(2);
  for (const [index, id] of ["mine-quick", "akari-quick", "sudoku-quick"].entries()) {
    $(id).classList[quickEnabled ? "remove" : "add"]("hidden");
    $(id).disabled = saveBusy || !canPlay(index);
    ruleControls[index].open.disabled = operationBusy || currentIndex !== index || ![game, akari, sudoku][index] ||
      !ui.result.classList.contains("hidden") || Boolean(mineExplosion?.running);
  }
  persistProgress();
  syncHomeEntries();
}

/** 通关立即保存；失败保留同一负载和终盘，重试不重复增加记录。 */
async function persistCompletion() {
  if (saveBusy || !challenge.state || challenge.saved(currentIndex)) return;
  const index = currentIndex;
  const generation = challenge.generation;
  saveBusy = true;
  recordStatus("正在保存通关记录…");
  syncProgressActions();
  try {
    const request = challenge.complete(index, session.levels[index].seconds, development);
    persistProgress();
    await request;
    document.dispatchEvent(new CustomEvent(Events.RECORDS_UPDATED));
    recordStatus("通关记录已保存，可查看本关排行。");
  } catch (error) {
    if (generation === challenge.generation) recordStatus(error.message, persistCompletion);
  } finally {
    if (generation === challenge.generation) { saveBusy = false; syncProgressActions(); }
  }
}

/** 在服务端确认重开之前阻止棋盘操作，失败时可原样重试。 */
async function requestRestart(index, restart) {
  if (operationBusy || saveBusy) return;
  const generation = challenge.generation;
  operationBusy = true;
  syncProgressActions();
  recordStatus("正在重新开始…");
  try {
    const request = challenge.restart(index);
    persistProgress();
    await request;
    development = false;
    restart();
    recordStatus();
  } catch (error) {
    if (generation === challenge.generation) recordStatus(error.message, () => requestRestart(index, restart));
  } finally {
    if (generation === challenge.generation) { operationBusy = false; syncProgressActions(); }
  }
}
const explosionSound = createExplosionSound(new URL("../assets/audio/explosion.wav", import.meta.url));
const audioSettings = getAudioSettings();
// 设置窗口与棋盘音效按钮共享同一偏好，修改开关或音量立即影响爆炸声音。
audioSettings.subscribe(({ effectsEnabled, effectsVolume }) => {
  explosionSound.setMuted(!effectsEnabled);
  explosionSound.setVolume(effectsVolume);
  $("mine-sound").textContent = effectsEnabled ? "音效：开" : "音效：关";
  $("mine-sound").setAttribute("aria-label", effectsEnabled ? "关闭游戏音效" : "开启游戏音效");
  $("mine-sound").setAttribute("aria-pressed", String(!effectsEnabled));
});
const explosionSequence = createExplosionSequence({
  reveal(index) {
    mineExplosion.revealed.add(index);
    const cell = ui.board.children[index];
    cell.classList.remove("cell-flagged", "cell-selected");
    cell.classList.add("cell-mine");
    cell.setAttribute("aria-label", `第 ${Math.floor(index / 10) + 1} 行第 ${index % 10 + 1} 列，地雷`);
  },
  explode(index, step) {
    mineExplosion.exploded.add(index);
    ui.board.children[index].classList.add("cell-exploded", "cell-blasting");
    ui.board.children[index].setAttribute("aria-label", `第 ${Math.floor(index / 10) + 1} 行第 ${index % 10 + 1} 列，地雷已爆炸`);
    void explosionSound.play(step);
  },
  settle(index) {
    mineExplosion.settled.add(index);
    ui.board.children[index].classList.remove("cell-blasting");
    ui.board.children[index].classList.add("cell-spent");
  },
  finish() {
    mineExplosion.running = false;
    ui.caption.textContent = "连锁爆炸结束。全部地雷已显示。";
    ui.message.textContent = "10 颗地雷已引爆。";
    showMineResult("lost");
  },
});

/** 清理旧局的计时器和尾音，避免重开或离开后继续爆炸。 */
function cancelMineExplosion() {
  explosionSequence.stop();
  explosionSound.stop();
  mineExplosion = null;
}

/** 新局或返回首页时隐藏上一局的结算入口。 */
function resetCompletionActions() {
  // 自由换关时，上一关可能尚未关闭首次规则；避免多个关卡弹窗叠在一起。
  ruleControls.forEach(({ dialog }) => dialog.classList.add("hidden"));
  $("mine-next").classList.add("hidden");
  $("akari-next").classList.add("hidden");
  $("settlement-open").classList.add("hidden");
  $("settlement-dialog").classList.add("hidden");
}

/** 关闭结果弹窗并保留终盘，各关下方均提供单关结算入口。 */
function viewResult() {
  ui.result.classList.add("hidden");
  if (resultMode === "mine-won") {
    $("mine-next").classList.remove("hidden");
    ui.message.textContent = "通关成功，已排开全部安全格。";
    $("mine-next").focus();
  } else if (resultMode === "akari-won") {
    $("akari-next").classList.remove("hidden");
    $("akari-next").focus();
  } else if (resultMode === "sudoku-won") {
    $("settlement-open").classList.remove("hidden");
    $("settlement-open").focus();
  } else {
    ui.viewport.focus();
  }
  syncProgressActions();
}

/** 从入口进入扫雷先显示规则，确认开始后才计时。 */
function enterGame() {
  if (operationBusy || saveBusy || challenge.restartPayload || !challenge.canEnter(0)) return;
  if (game || challenge.saved(0)) { viewExistingLevel(0); return; }
  explosionSound.unlock();
  currentIndex = 0;
  development = false;
  restartGame();
  ui.landing.classList.add("hidden");
  ui.sudokuScreen.classList.add("hidden");
  ui.akariScreen.classList.add("hidden");
  ui.mineScreen.classList.remove("hidden");
  window.scrollTo(0, 0);
  syncProgressActions();
}

/** 清空当前扫雷棋盘与计时；服务端重开在外层确认。 */
function restartGame() {
  restartLevel(session, 0);
  resetCompletionActions();
  cancelMineExplosion();
  game = createGame();
  ui.result.classList.add("hidden");
  ui.message.textContent = "";
  ui.viewport.scrollTo(0, 0);
  renderMine();
  showRules(0);
}

/** 首次进入数独创建题盘，已有本轮棋盘直接查看或继续。 */
function enterSudoku() {
  if (operationBusy || saveBusy || challenge.restartPayload || !challenge.canEnter(2)) return;
  if (sudoku || challenge.saved(2)) { viewExistingLevel(2); return; }
  currentIndex = 2;
  development = false;
  recordStatus();
  cancelMineExplosion();
  restartSudoku();
  ui.landing.classList.add("hidden");
  ui.mineScreen.classList.add("hidden");
  ui.akariScreen.classList.add("hidden");
  ui.sudokuScreen.classList.remove("hidden");
  window.scrollTo(0, 0);
  syncProgressActions();
}

/** 从固定数独题目重新绘制，已保存历史成绩不受影响。 */
function restartSudoku() {
  restartLevel(session, 2);
  resetCompletionActions();
  sudoku = createSudoku();
  ui.result.classList.add("hidden");
  ui.sudokuMessage.textContent = "";
  renderSudoku();
  showRules(2);
}

/** 首次进入照明先显示规则；已有本轮棋盘直接查看或继续，保留原始计时。 */
function enterAkari() {
  if (operationBusy || saveBusy || challenge.restartPayload || !challenge.canEnter(1)) return;
  if (akari || challenge.saved(1)) { viewExistingLevel(1); return; }
  currentIndex = 1;
  development = false;
  recordStatus();
  cancelMineExplosion();
  restartAkari();
  ui.landing.classList.add("hidden");
  ui.mineScreen.classList.add("hidden");
  ui.sudokuScreen.classList.add("hidden");
  ui.akariScreen.classList.remove("hidden");
  window.scrollTo(0, 0);
  syncProgressActions();
}

/** 重置灯泡与本关计时，其他关卡棋盘和用时保持原样。 */
function restartAkari() {
  restartLevel(session, 1);
  resetCompletionActions();
  akari = createAkari();
  ui.result.classList.add("hidden");
  ui.akariMessage.textContent = "";
  renderAkari();
  showRules(1);
}

/** 查看本轮已有棋局或通关结果，切换关卡不重开、不清理后续棋盘与计时。 */
function viewExistingLevel(index) {
  currentIndex = index;
  resultMode = "";
  recordStatus();
  cancelMineExplosion();
  dialogIds.forEach(id => $(id).classList.add("hidden"));
  resetCompletionActions();
  ui.landing.classList.add("hidden");
  [ui.mineScreen, ui.akariScreen, ui.sudokuScreen].forEach((screen, position) =>
    screen.classList[position === index ? "remove" : "add"]("hidden"));
  const board = [game, akari, sudoku][index];
  if (!board) {
    // 早期存档仅包含最后一关棋盘；已保存的前关仍能查看真实通关结果和用时。
    [ui.board, ui.akariBoard, ui.sudokuBoard][index].replaceChildren(document.createDocumentFragment());
    ui.flag.disabled = ui.reveal.disabled = true;
  }
  [renderMine, renderAkari, renderSudoku][index]();
  if (challenge.saved(index) || (index === 0 ? game?.status === "won" : board?.complete)) {
    [() => showMineResult("won"), showAkariResult, showSudokuResult][index]();
  } else if (index === 0 && game?.status === "lost") showMineResult("lost");
  else if (session.levels[index].startedAt === null) showRules(index);
  updateTimer();
  syncProgressActions();
  window.scrollTo(0, 0);
}

/** 返回首页保存所有关卡棋局和结果；旧异步响应始终失效。 */
function returnHome() {
  persistProgress(true);
  document.dispatchEvent(new CustomEvent(Events.SETTLEMENT_CLOSED));
  challenge.reset();
  operationBusy = saveBusy = false;
  development = false;
  recordStatus();
  resetCompletionActions();
  cancelMineExplosion();
  ui.mineRules.classList.add("hidden");
  ui.sudokuRules.classList.add("hidden");
  ui.akariRules.classList.add("hidden");
  ui.result.classList.add("hidden");
  ui.mineScreen.classList.add("hidden");
  ui.sudokuScreen.classList.add("hidden");
  ui.akariScreen.classList.add("hidden");
  ui.landing.classList.remove("hidden");
  game = null;
  sudoku = null;
  akari = null;
  session = createSession();
  resultMode = "";
  syncHomeEntries();
  $("start-button").focus();
  window.scrollTo(0, 0);
}

/** 未揭开的扫雷格子不展示雷或数字。 */
function renderMineBoard() {
  const fragment = document.createDocumentFragment();
  game.cells.forEach((cell, index) => {
    const row = Math.floor(index / 10) + 1;
    const col = index % 10 + 1;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "cell";
    button.dataset.index = String(index);
    button.setAttribute("aria-label", `第 ${row} 行第 ${col} 列`);
    button.setAttribute("aria-pressed", game.selected === index ? "true" : "false");
    if (game.selected === index) button.classList.add("cell-selected");
    if (cell.flagged) {
      button.classList.add("cell-flagged");
      button.setAttribute("aria-label", `第 ${row} 行第 ${col} 列，已标记`);
    }
    // 失败后的地雷按时间线出现，包括原先插旗的雷；未轮到的仍保持原样。
    if (game.status === "lost" && cell.mine) {
      if (mineExplosion?.revealed.has(index)) {
        button.classList.remove("cell-flagged");
        button.classList.add("cell-mine");
        button.setAttribute("aria-label", `第 ${row} 行第 ${col} 列，地雷`);
        if (mineExplosion.exploded.has(index)) {
          button.classList.add("cell-exploded");
          button.setAttribute("aria-label", `第 ${row} 行第 ${col} 列，地雷已爆炸`);
        }
        if (mineExplosion.settled.has(index)) button.classList.add("cell-spent");
      }
    } else if (cell.revealed) {
      button.classList.add("cell-revealed");
      if (cell.mine) {
        button.classList.add("cell-mine");
        if (game.explodedAt === index) button.classList.add("cell-exploded");
        button.setAttribute("aria-label", `第 ${row} 行第 ${col} 列，地雷`);
      } else {
        // 1～3 使用原图切片；原图没有的 4～8 用同风格文字补齐。
        button.textContent = cell.adjacent > 3 ? String(cell.adjacent) : "";
        // 只为已揭开的格子选择数字切片，隐藏格子不暴露线索。
        button.dataset.adjacent = String(cell.adjacent);
        button.setAttribute("aria-label", `第 ${row} 行第 ${col} 列，周围 ${cell.adjacent} 颗雷`);
      }
    }
    fragment.append(button);
  });
  ui.board.replaceChildren(fragment);
}

/** 刷新扫雷棋盘、操作状态和同一口径的计时。 */
function renderMine() {
  if (!game) return;
  renderMineBoard();
  const selected = game.selected;
  const active = selected !== null && game.status !== "won" && game.status !== "lost";
  ui.flag.disabled = !active;
  ui.reveal.disabled = !active || game.cells[selected]?.flagged;
  ui.flag.textContent = active && game.cells[selected].flagged ? "取消标记" : "标记";
  ui.selection.textContent = active
    ? `已选第 ${Math.floor(selected / 10) + 1} 行，第 ${selected % 10 + 1} 列`
    : "尚未选择格子";
  ui.caption.textContent = game.status === "won" ? "你赢了。" : game.status === "lost"
    ? "碰到地雷了。" : "点选一个格子，再选择操作。棋盘可左右滑动。";
  ui.minesLeft.textContent = String(game.level.mineCount - game.flaggedCount);
  ui.cleared.textContent = String(game.revealedCount);
  updateTimer();
  persistProgress();
}

/** 周期回调只更新用时文字，不向服务器轮询或重画棋盘。 */
function updateTimer() {
  ui.timer.textContent = formatTime(levelSeconds(session, 0, game?.endedAt ?? Date.now()));
  $("akari-timer").textContent = formatTime(levelSeconds(session, 1));
  $("sudoku-timer").textContent = formatTime(levelSeconds(session, 2));
}

/** 显示数独棋盘；重复数字用颜色标识，题目数字不能修改。 */
function renderSudoku() {
  if (!sudoku) return;
  const conflicts = sudokuConflicts(sudoku);
  const selected = sudoku.selected;
  const fragment = document.createDocumentFragment();
  sudoku.values.forEach((value, index) => {
    const row = Math.floor(index / 9);
    const col = index % 9;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "sudoku-cell";
    button.dataset.index = String(index);
    button.textContent = value === 0 ? "" : String(value);
    const mask = value === 0 ? sudoku.notes[index] : 0;
    const digits = Array.from({ length: 9 }, (_, offset) => offset + 1).filter(digit => mask & (1 << (digit - 1)));
    if (mask) {
      const notes = document.createElement("span");
      notes.className = "sudoku-notes";
      notes.setAttribute("aria-hidden", "true");
      // 每个候选数使用固定九宫位置，空位仍占格，方便快速扫视与比较。
      for (let digit = 1; digit <= 9; digit++) {
        const slot = document.createElement("span");
        slot.textContent = digits.includes(digit) ? String(digit) : "";
        notes.append(slot);
      }
      button.append(notes);
    }
    button.setAttribute("aria-label", `第 ${row + 1} 行第 ${col + 1} 列，${value === 0 ? digits.length ? `候选数 ${digits.join("、")}` : "空格" : value}${sudoku.givens[index] ? "，题目数字" : ""}`);
    button.setAttribute("aria-pressed", selected === index ? "true" : "false");
    if (sudoku.givens[index] !== 0) button.classList.add("given");
    if (selected !== null && (row === Math.floor(selected / 9) || col === selected % 9 ||
      (Math.floor(row / 3) === Math.floor(Math.floor(selected / 9) / 3) && Math.floor(col / 3) === Math.floor((selected % 9) / 3)))) {
      button.classList.add("peer");
    }
    // 与选中格相同的数字单独高亮，帮助在手机上快速定位同值格。
    if (selected !== null && value !== 0 && value === sudoku.values[selected]) {
      button.classList.add("same-value");
    }
    if (selected === index) button.classList.add("selected");
    if (conflicts.has(index)) button.classList.add("conflict");
    if (col === 2 || col === 5) button.classList.add("box-right");
    if (row === 2 || row === 5) button.classList.add("box-bottom");
    fragment.append(button);
  });
  ui.sudokuBoard.replaceChildren(fragment);
  const editable = selected !== null && sudoku.givens[selected] === 0 && !sudoku.complete;
  ui.sudokuSelection.textContent = selected === null ? "请选择一个空格。"
    : `已选第 ${Math.floor(selected / 9) + 1} 行，第 ${selected % 9 + 1} 列${editable ? "" : sudoku.givens[selected] ? "（题目数字不可修改）" : ""}`;
  const noteEditable = editable && sudoku.values[selected] === 0;
  ui.sudokuKeypad.querySelectorAll("button").forEach((button) => {
    button.disabled = !editable || (sudoku.notesMode && !noteEditable);
    if (sudoku.notesMode) button.setAttribute("aria-pressed", String(noteEditable && Boolean(sudoku.notes[selected] & (1 << (Number(button.dataset.digit) - 1)))));
    else button.removeAttribute("aria-pressed");
  });
  ui.sudokuClear.disabled = !editable;
  ui.sudokuClear.textContent = sudoku.notesMode && noteEditable ? "清除本格笔记" : "清除选中格";
  ui.sudokuNotes.textContent = sudoku.notesMode ? "笔记：开" : "笔记：关";
  ui.sudokuNotes.setAttribute("aria-pressed", String(sudoku.notesMode));
  ui.sudokuKeypad.setAttribute("aria-label", sudoku.notesMode ? "记录候选数" : "填写数字");
  ui.sudokuInputHint.textContent = sudoku.notesMode
    ? editable && !noteEditable ? "笔记模式：先清除本格答案，再记录候选数。" : "笔记模式：点击数字添加或取消候选数。"
    : "填数模式：点击数字填写答案，开启笔记可记录候选数。";
  // 操作时也同步用时，页面后台节流后无需等下一次定时刷新。
  updateTimer();
  persistProgress();
}

/** 绘制灯光覆盖和错误位置，数字墙格显示当前灯数与目标灯数。 */
function renderAkari() {
  if (!akari) return;
  const inspection = inspectAkari(akari);
  const fragment = document.createDocumentFragment();
  for (let index = 0; index < AKARI_SIZE * AKARI_SIZE; index += 1) {
    const type = akariCell(index);
    const row = Math.floor(index / AKARI_SIZE) + 1;
    const col = index % AKARI_SIZE + 1;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "akari-cell";
    button.dataset.index = String(index);
    if (type !== ".") {
      button.classList.add("wall");
      button.disabled = true;
      button.textContent = type === "#" ? "" : type;
      button.setAttribute("aria-label", type === "#" ? `第 ${row} 行第 ${col} 列，墙格`
        : `第 ${row} 行第 ${col} 列，数字墙格 ${type}，已相邻 ${inspection.clueCounts.get(index)} 盏灯`);
      // 棋盘全亮仍未通关时，也标出缺灯的数字墙格，避免看似完成却无提示。
      if (inspection.wrongClues.has(index) ||
        (inspection.lit.size === inspection.whiteCount && inspection.unmetClues.has(index))) {
        button.classList.add("error");
      }
    } else {
      const bulb = akari.bulbs.has(index);
      // 灯泡用现有素材绘制；读屏名称仍明确说明格子状态。
      button.textContent = "";
      button.setAttribute("aria-label", `第 ${row} 行第 ${col} 列，${bulb ? "已放灯" : inspection.lit.has(index) ? "已照亮" : "未照亮"}`);
      button.setAttribute("aria-pressed", bulb ? "true" : "false");
      if (inspection.lit.has(index)) button.classList.add("lit");
      if (bulb) button.classList.add("bulb");
      if (inspection.conflictingBulbs.has(index)) button.classList.add("error");
    }
    fragment.append(button);
  }
  ui.akariBoard.replaceChildren(fragment);
  ui.akariStatus.textContent = `已照亮：${inspection.lit.size} / ${inspection.whiteCount} 格；已放灯：${akari.bulbs.size} 盏`;
  if (inspection.conflictingBulbs.size > 0) ui.akariMessage.textContent = "有灯泡互相照射，请检查标红的灯。";
  else if (inspection.wrongClues.size > 0) ui.akariMessage.textContent = "数字墙格旁的灯太多，请检查标红的格子。";
  else if (inspection.lit.size === inspection.whiteCount && inspection.unmetClues.size > 0) {
    const index = inspection.unmetClues.values().next().value;
    ui.akariMessage.textContent = `棋盘已全亮，但尚未通关：第 ${Math.floor(index / AKARI_SIZE) + 1} 行第 ${index % AKARI_SIZE + 1} 列需 ${akariCell(index)} 盏相邻灯，目前 ${inspection.clueCounts.get(index)} 盏。请检查标红的数字墙格。`;
  }
  else ui.akariMessage.textContent = "";
  updateTimer();
  persistProgress();
}

/** 扫雷胜利进入统一保存流程；失败不创建通关记录。 */
function showMineResult(outcome) {
  if (outcome === "won") {
    completeLevel(session, 0);
    updateTimer();
    resultMode = "mine-won";
    ui.resultTitle.textContent = "第一关通关成功";
    ui.resultDescription.textContent = `已排开全部 90 个安全格，用时 ${formatTime(session.levels[0].seconds)}。`;
    ui.resultPrimary.textContent = "查看本关结算";
    ui.resultSecondary.textContent = "查看结果";
  } else {
    resultMode = "mine-lost";
    ui.resultTitle.textContent = "游戏失败";
    ui.resultDescription.textContent = "地雷连锁爆炸，全部地雷已显示。可以查看棋盘，或重新开始。";
    ui.resultPrimary.textContent = "重新开始";
    ui.resultSecondary.textContent = "查看棋盘";
  }
  ui.result.classList.remove("hidden");
  ui.resultPrimary.disabled = false;
  if (outcome === "won") void persistCompletion();
  ui.resultPrimary.focus();
  syncProgressActions();
}

/** 数独完成后先祝贺，等待保存成功后打开本关结算。 */
function showSudokuResult() {
  completeLevel(session, 2);
  updateTimer();
  resultMode = "sudoku-won";
  ui.resultTitle.textContent = "恭喜你，挑战完成！";
  ui.resultDescription.textContent = `你已完成数独挑战，用时 ${formatTime(session.levels[2].seconds)}。`;
  ui.resultPrimary.textContent = "查看本关结算";
  ui.resultSecondary.textContent = "查看结果";
  ui.result.classList.remove("hidden");
  void persistCompletion();
  ui.resultPrimary.focus();
  syncProgressActions();
}

/** 照明完成后冻结秒数并提交，保存成功后可查看本关结算。 */
function showAkariResult() {
  completeLevel(session, 1);
  updateTimer();
  resultMode = "akari-won";
  ui.resultTitle.textContent = "第二关通关成功";
  ui.resultDescription.textContent = `所有可放灯格已照亮，数字线索也全部满足，用时 ${formatTime(session.levels[1].seconds)}。`;
  ui.resultPrimary.textContent = "查看本关结算";
  ui.resultSecondary.textContent = "查看结果";
  ui.result.classList.remove("hidden");
  void persistCompletion();
  ui.resultPrimary.focus();
  syncProgressActions();
}

/** 数独确认开始后允许输入，查看规则或异步重开期间不可修改棋盘。 */
function inputSudoku(value) {
  if (!canPlay(2)) return;
  if (!sudoku) return;
  // 清除操作始终擦除本格内容；1–9 则按当前模式写入笔记或正式答案。
  const noting = sudoku.notesMode && value !== 0;
  if (!(noting ? toggleSudokuNote(sudoku, value) : setSudokuValue(sudoku, value))) return;
  ui.sudokuMessage.textContent = noting ? "候选数已更新。" : sudoku.complete ? "" : sudokuConflicts(sudoku).size > 0 ? "存在重复数字，请检查。" : "";
  renderSudoku();
  if (sudoku.complete) showSudokuResult();
}

/** 仅展示当前关的已保存成绩，胜利音按本次尝试去重。 */
function openSettlement() {
  if (!challenge.saved(currentIndex) || saveBusy || operationBusy) return;
  ui.result.classList.add("hidden");
  $("settlement-title").textContent = `${["扫雷", "照明", "数独"][currentIndex]}通关结算`;
  $("settlement-note").textContent = "本关成绩已保存，可返回首页选择其他挑战。";
  $("settlement-time").textContent = formatTime(challenge.state.levels[currentIndex].seconds);
  $("settlement-dialog").classList.remove("hidden");
  document.dispatchEvent(new CustomEvent(Events.SETTLEMENT_OPENED, { detail: { runId: challenge.state.levels[currentIndex].attempt_id } }));
  $("settlement-home").focus();
  persistProgress();
}

// 棋盘使用事件委托，重新绘制格子后仍能处理点击。
// 登录模块确认会话后才发出入口事件；规则阅读与计时继续由游戏模块管理。
/** 首页可任选一关；先恢复其他关卡进度，无存档时创建进度再进入所选关。 */
async function enterFromHome(index) {
  if (operationBusy || ui.landing.classList.contains("hidden")) return;
  const snapshot = loadProgress(progressStorage, currentUserId);
  if (snapshot) {
    if (!await restoreProgress(snapshot)) return;
    if (currentIndex !== index) {
      [enterGame, enterAkari, enterSudoku][index]();
    }
    return;
  }
  operationBusy = true;
  syncHomeEntries();
  const generation = challenge.generation;
  $("start-button").disabled = true;
  recordStatus("正在创建挑战…");
  try {
    await challenge.start();
    recordStatus();
    development = false;
    operationBusy = false;
    [enterGame, enterAkari, enterSudoku][index]();
  } catch (error) { if (generation === challenge.generation) recordStatus(error.message); }
  finally {
    if (generation === challenge.generation) { operationBusy = false; syncProgressActions(); }
    $("start-button").disabled = false;
  }
}

// 首页按钮只滚动到关卡选择，不再重置整轮进度。
$("challenge-action").addEventListener("click", () => {
  if ($("challenge-action").dataset.action === "select") $("level-select").scrollIntoView({ behavior: "smooth", block: "start" });
});
// 首页三关共用登录后的存档续接。
homeEntries.forEach((entry, index) => entry.button.addEventListener(Events.AUTHORIZED_START, () => enterFromHome(index)));
$("back-button").addEventListener("click", returnHome);
$("restart-button").addEventListener("click", () => requestRestart(0, restartGame));
$("mine-sound").addEventListener("click", () => {
  audioSettings.update({ effectsEnabled: !audioSettings.state.effectsEnabled });
  explosionSound.unlock();
});
$("sudoku-back").addEventListener("click", returnHome);
$("sudoku-restart").addEventListener("click", () => requestRestart(2, restartSudoku));
$("akari-back").addEventListener("click", returnHome);
$("akari-restart").addEventListener("click", () => requestRestart(1, restartAkari));
$("mine-next").addEventListener("click", openSettlement);
$("akari-next").addEventListener("click", openSettlement);
for (const [index, controls] of ruleControls.entries()) {
  controls.open.addEventListener("click", () => {
    if (!controls.open.disabled) showRules(index);
  });
  controls.close.addEventListener("click", () => closeRules(index));
}
ui.board.addEventListener("click", (event) => {
  if (!canPlay(0)) return;
  const button = event.target.closest("button[data-index]");
  if (!button || !game || !selectCell(game, Number(button.dataset.index))) return;
  ui.message.textContent = "格子已选中。";
  renderMine();
});
ui.flag.addEventListener("click", () => {
  if (!canPlay(0)) return;
  if (!game || !toggleFlag(game)) return;
  ui.message.textContent = game.cells[game.selected].flagged ? "已标记。" : "已取消标记。";
  renderMine();
});
ui.reveal.addEventListener("click", () => {
  if (!canPlay(0)) return;
  if (!game) return;
  // 在用户手势内恢复音频，后续连锁由同一个已解锁的音频上下文播放。
  explosionSound.unlock();
  const outcome = revealSelected(game);
  if (outcome === "ignored") return;
  ui.message.textContent = outcome === "revealed" ? "继续选择格子。" : "";
  if (outcome === "lost") {
    mineExplosion = { revealed: new Set(), exploded: new Set(), settled: new Set(), running: true };
    renderMine();
    syncProgressActions();
    ui.caption.textContent = "踩到地雷！连锁爆炸正在蔓延……";
    ui.message.textContent = "地雷正在依次引爆。";
    explosionSequence.start(explosionOrder(game));
    return;
  }
  renderMine();
  if (outcome === "won") showMineResult(outcome);
});
ui.sudokuBoard.addEventListener("click", (event) => {
  if (!canPlay(2)) return;
  const button = event.target.closest("button[data-index]");
  if (!button || !sudoku || !selectSudokuCell(sudoku, Number(button.dataset.index))) return;
  renderSudoku();
});
ui.sudokuKeypad.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-digit]");
  if (button) inputSudoku(Number(button.dataset.digit));
});
ui.sudokuClear.addEventListener("click", () => inputSudoku(0));
ui.sudokuNotes.addEventListener("click", () => {
  if (!sudoku || !canPlay(2)) return;
  sudoku.notesMode = !sudoku.notesMode;
  renderSudoku();
});
ui.sudokuCheck.addEventListener("click", () => {
  if (!sudoku) return;
  const result = checkSudoku(sudoku);
  ui.sudokuMessage.textContent = result.status === "conflict" ? "有重复数字，请检查标红的格子。"
    : result.status === "complete" ? "已完成。" : result.blanks > 0 ? `没有重复数字，还剩 ${result.blanks} 个空格。` : "已填满，但仍有错误。";
});
ui.akariBoard.addEventListener("click", (event) => {
  if (!canPlay(1)) return;
  const button = event.target.closest("button[data-index]");
  if (!button || !akari || !toggleBulb(akari, Number(button.dataset.index))) return;
  renderAkari();
  if (akari.complete) showAkariResult();
});
ui.resultPrimary.addEventListener("click", () => {
  if (resultMode === "mine-lost") void requestRestart(0, restartGame);
  else if (resultMode.endsWith("won")) openSettlement();
});
ui.resultSecondary.addEventListener("click", viewResult);
$("settlement-open").addEventListener("click", openSettlement);
$("settlement-home").addEventListener("click", returnHome);
$("settlement-ranking").addEventListener("click", () => {
  if (challenge.saved(currentIndex)) window.location.assign(`./ranking-${["mine", "akari", "sudoku"][currentIndex]}.html`);
});
for (const id of ["challenge-retry", "save-retry"]) $(id).addEventListener("click", () => { void retryOperation?.(); });
document.addEventListener(Events.AUTH_CHANGED, (event) => {
  const nextUserId = event?.detail?.user?.id ?? null;
  if (nextUserId === currentUserId) return;
  returnHome();
  currentUserId = nextUserId;
  syncHomeEntries();
  const snapshot = loadProgress(progressStorage, currentUserId);
  if (snapshot && !snapshot.atHome) void restoreProgress(snapshot);
});

/** 临时开发入口只完成当前关，动态加载便于后续删除。 */
async function quickComplete() {
  if (!quickEnabled || !canPlay(currentIndex) || saveBusy || !challenge.canEnter(currentIndex)) return;
  const index = currentIndex;
  const generation = challenge.generation;
  operationBusy = true;
  syncProgressActions();
  try {
    const { solveCurrentLevel } = await import("./dev-quick-complete.js");
    if (generation !== challenge.generation) return;
    development = true;
    solveCurrentLevel(index, [game, akari, sudoku][index]);
    [renderMine, renderAkari, renderSudoku][index]();
    [() => showMineResult("won"), showAkariResult, showSudokuResult][index]();
  } catch (error) {
    if (generation === challenge.generation) recordStatus(error.message);
  } finally {
    if (generation === challenge.generation) { operationBusy = false; syncProgressActions(); }
  }
}
for (const id of ["mine-quick", "akari-quick", "sudoku-quick"]) $(id).addEventListener("click", quickComplete);
// 配置读取失败只隐藏开发按钮，正常挑战仍可进行。
void rankingRequest("challenges/config").then((config) => {
  quickEnabled = config.quick_complete_enabled === true;
  syncProgressActions();
}).catch(() => {});
document.addEventListener("keydown", (event) => {
  // 规则和结算弹窗内循环键盘焦点，防止 Tab 落到背后的棋盘。
  const activeDialog = [$("settlement-dialog"), ...ruleControls.map(controls => controls.dialog)]
    .find((dialog) => !dialog.classList.contains("hidden"));
  if (activeDialog && event.key === "Tab") {
    const controls = [...activeDialog.querySelectorAll("button:not(:disabled)")];
    const first = controls[0];
    const last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    return;
  }
  if (event.key === "Escape") {
    const ruleIndex = ruleControls.findIndex(controls => !controls.dialog.classList.contains("hidden"));
    if (ruleIndex !== -1) {
      // 首次规则不能用 Esc 绕过开始确认；已开始后 Esc 只关闭规则，计时继续。
      if (session.levels[ruleIndex].startedAt !== null || session.levels[ruleIndex].seconds !== null) closeRules(ruleIndex);
      else event.preventDefault();
      return;
    }
    if (!$("settlement-dialog").classList.contains("hidden")) {
      $("settlement-dialog").classList.add("hidden");
      document.dispatchEvent(new CustomEvent(Events.SETTLEMENT_CLOSED));
      viewResult();
      return;
    }
    if (!ui.result.classList.contains("hidden")) {
      viewResult();
    }
  } else if (sudoku && !ui.sudokuScreen.classList.contains("hidden") && ui.sudokuRules.classList.contains("hidden") && ui.result.classList.contains("hidden")) {
    if (/^[1-9]$/.test(event.key)) inputSudoku(Number(event.key));
    else if (event.key === "Backspace" || event.key === "Delete") inputSudoku(0);
  }
});

// 计时器只更新三关用时，不会每秒重画棋盘。
window.setInterval(updateTimer, 1000);
// 规则、结果弹窗及选中状态同样保存；事件冒泡到 document 时棋局操作已完成。
document.addEventListener("click", () => persistProgress());
document.addEventListener("keyup", () => persistProgress());
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") persistProgress();
  else updateTimer();
});
window.addEventListener?.("pagehide", () => persistProgress());
window.addEventListener?.("pageshow", updateTimer);
