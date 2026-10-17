/**
 * 无职游戏页面入口：管理扫雷、数独、照明三关与对应的规则弹窗。
 * 三关均可从入口直接进入，在浏览器运行；不保存进行中的棋局。
 */

import { createGame, revealSelected, selectCell, toggleFlag } from "./game.js";
import { createSudoku, selectSudokuCell, setSudokuValue, sudokuConflicts, checkSudoku } from "./sudoku.js";
import { AKARI_SIZE, akariCell, createAkari, inspectAkari, toggleBulb } from "./akari.js";
import { createExplosionSequence, createExplosionSound, explosionOrder } from "./mine-effects.js";
import { createSession, restartLevel, startLevel, completeLevel, levelSeconds, sessionSummary, formatTime } from "./session.js";

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
let soundMuted = false;
let session = createSession();
const explosionSound = createExplosionSound(new URL("../assets/audio/explosion.wav", import.meta.url));
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

/** 新局或返回首页时隐藏上一局的下一关入口。 */
function resetCompletionActions() {
  $("mine-next").classList.add("hidden");
  $("akari-next").classList.add("hidden");
  $("settlement-open").classList.add("hidden");
  $("settlement-dialog").classList.add("hidden");
}

/** 关闭结果弹窗并保留终盘，通关后在棋盘下方右侧提供下一关入口。 */
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
}

/** 从入口进入扫雷时显示规则，重新开始扫雷时不重复弹出。 */
function enterGame() {
  if (!ui.landing.classList.contains("hidden")) session = createSession();
  explosionSound.unlock();
  sudoku = null;
  akari = null;
  restartGame();
  ui.landing.classList.add("hidden");
  ui.sudokuScreen.classList.add("hidden");
  ui.akariScreen.classList.add("hidden");
  ui.mineScreen.classList.remove("hidden");
  ui.mineRules.classList.remove("hidden");
  $("rules-close").focus();
  window.scrollTo(0, 0);
}

function restartGame() {
  restartLevel(session, 0);
  resetCompletionActions();
  cancelMineExplosion();
  game = createGame();
  ui.result.classList.add("hidden");
  ui.message.textContent = "";
  ui.viewport.scrollTo(0, 0);
  renderMine();
}

/** 进入固定数独题盘；每次进入或重新开始都从原题开始。 */
function enterSudoku() {
  if (!ui.landing.classList.contains("hidden")) session = createSession();
  cancelMineExplosion();
  game = null;
  akari = null;
  restartSudoku();
  ui.landing.classList.add("hidden");
  ui.mineScreen.classList.add("hidden");
  ui.akariScreen.classList.add("hidden");
  ui.sudokuScreen.classList.remove("hidden");
  ui.sudokuRules.classList.remove("hidden");
  $("sudoku-rules-close").focus();
  window.scrollTo(0, 0);
}

function restartSudoku() {
  restartLevel(session, 2);
  resetCompletionActions();
  sudoku = createSudoku();
  ui.result.classList.add("hidden");
  ui.sudokuMessage.textContent = "";
  renderSudoku();
}

/** 进入照明关时显示规则；重新开始只重置灯泡，不再弹规则。 */
function enterAkari() {
  if (!ui.landing.classList.contains("hidden")) session = createSession();
  cancelMineExplosion();
  game = null;
  sudoku = null;
  restartAkari();
  ui.landing.classList.add("hidden");
  ui.mineScreen.classList.add("hidden");
  ui.sudokuScreen.classList.add("hidden");
  ui.akariScreen.classList.remove("hidden");
  ui.akariRules.classList.remove("hidden");
  $("akari-rules-close").focus();
  window.scrollTo(0, 0);
}

function restartAkari() {
  restartLevel(session, 1);
  resetCompletionActions();
  akari = createAkari();
  ui.result.classList.add("hidden");
  ui.akariMessage.textContent = "";
  renderAkari();
}

function returnHome() {
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
}

function updateTimer() {
  if (game) ui.timer.textContent = formatTime(levelSeconds(session, 0, game.endedAt ?? Date.now()));
  if (akari) $("akari-timer").textContent = formatTime(levelSeconds(session, 1));
  if (sudoku) $("sudoku-timer").textContent = formatTime(levelSeconds(session, 2));
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
    button.setAttribute("aria-label", `第 ${row + 1} 行第 ${col + 1} 列，${value === 0 ? "空格" : value}${sudoku.givens[index] ? "，题目数字" : ""}`);
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
  ui.sudokuKeypad.querySelectorAll("button").forEach((button) => { button.disabled = !editable; });
  ui.sudokuClear.disabled = !editable;
  // 操作时也同步用时，页面后台节流后无需等下一次定时刷新。
  updateTimer();
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
}

function showMineResult(outcome) {
  if (outcome === "won") {
    completeLevel(session, 0);
    updateTimer();
    resultMode = "mine-won";
    ui.resultTitle.textContent = "第一关通关成功";
    ui.resultDescription.textContent = "已排开全部 90 个安全格。可以继续挑战照明。";
    ui.resultPrimary.textContent = "进入第二关";
    ui.resultSecondary.textContent = "查看结果";
  } else {
    resultMode = "mine-lost";
    ui.resultTitle.textContent = "游戏失败";
    ui.resultDescription.textContent = "地雷连锁爆炸，全部地雷已显示。可以查看棋盘，或重新开始。";
    ui.resultPrimary.textContent = "重新开始";
    ui.resultSecondary.textContent = "查看棋盘";
  }
  ui.result.classList.remove("hidden");
  ui.resultPrimary.focus();
}

function showSudokuResult() {
  completeLevel(session, 2);
  updateTimer();
  resultMode = "sudoku-won";
  ui.resultTitle.textContent = "恭喜你，挑战完成！";
  ui.resultDescription.textContent = sessionSummary(session).complete
    ? "你已完成扫雷、照明与数独三关挑战。开始结算，看看这场冒险的用时。"
    : "你已完成最后一关数独。开始结算，查看本轮已完成关卡的用时。";
  ui.resultPrimary.textContent = "开始结算";
  ui.resultSecondary.textContent = "查看结果";
  ui.result.classList.remove("hidden");
  ui.resultPrimary.focus();
}

function showAkariResult() {
  completeLevel(session, 1);
  updateTimer();
  resultMode = "akari-won";
  ui.resultTitle.textContent = "第二关通关成功";
  ui.resultDescription.textContent = "所有可放灯格已照亮，数字线索也全部满足。可以继续挑战数独。";
  ui.resultPrimary.textContent = "进入第三关";
  ui.resultSecondary.textContent = "查看结果";
  ui.result.classList.remove("hidden");
  ui.resultPrimary.focus();
}

function inputSudoku(value) {
  if (!sudoku || !setSudokuValue(sudoku, value)) return;
  startLevel(session, 2);
  ui.sudokuMessage.textContent = sudoku.complete ? "" : sudokuConflicts(sudoku).size > 0 ? "存在重复数字，请检查。" : "";
  renderSudoku();
  if (sudoku.complete) showSudokuResult();
}

/** 最后一关完成后按顺序结算；跳过的关卡明确标记，避免把缺失成绩当成零秒。 */
function openSettlement() {
  if (!sudoku?.complete) return;
  ui.result.classList.add("hidden");
  const summary = sessionSummary(session);
  ["mine", "akari", "sudoku"].forEach((name, index) => {
    $("settlement-" + name).textContent = summary.times[index] === null ? "未挑战" : formatTime(summary.times[index]);
  });
  $("settlement-note").textContent = summary.complete
    ? "三关全部通关，感谢你完成这场解谜之旅。"
    : "本轮包含跳关记录，以下仅统计已完成的关卡。";
  $("settlement-total-label").textContent = summary.complete ? "总共花费时间" : "已完成关卡用时合计";
  $("settlement-total").textContent = formatTime(summary.total);
  $("settlement-dialog").classList.remove("hidden");
  $("settlement-home").focus();
}

// 棋盘使用事件委托，重新绘制格子后仍能处理点击。
$("start-button").addEventListener("click", enterGame);
ui.sudokuEntry.addEventListener("click", enterSudoku);
ui.akariEntry.addEventListener("click", enterAkari);
$("back-button").addEventListener("click", returnHome);
$("restart-button").addEventListener("click", restartGame);
$("mine-sound").addEventListener("click", () => {
  soundMuted = !soundMuted;
  explosionSound.unlock();
  explosionSound.setMuted(soundMuted);
  $("mine-sound").textContent = soundMuted ? "音效：关" : "音效：开";
  $("mine-sound").setAttribute("aria-label", soundMuted ? "开启爆炸音效" : "关闭爆炸音效");
  $("mine-sound").setAttribute("aria-pressed", String(soundMuted));
});
$("sudoku-back").addEventListener("click", returnHome);
$("sudoku-restart").addEventListener("click", restartSudoku);
$("akari-back").addEventListener("click", returnHome);
$("akari-restart").addEventListener("click", restartAkari);
$("mine-next").addEventListener("click", enterAkari);
$("akari-next").addEventListener("click", enterSudoku);
$("rules-close").addEventListener("click", () => { ui.mineRules.classList.add("hidden"); ui.viewport.focus(); });
$("sudoku-rules-close").addEventListener("click", () => { ui.sudokuRules.classList.add("hidden"); ui.sudokuBoard.querySelector("button")?.focus(); });
$("akari-rules-close").addEventListener("click", () => { ui.akariRules.classList.add("hidden"); ui.akariBoard.querySelector("button:not(:disabled)")?.focus(); });
ui.board.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-index]");
  if (!button || !game || !selectCell(game, Number(button.dataset.index))) return;
  ui.message.textContent = "格子已选中。";
  renderMine();
});
ui.flag.addEventListener("click", () => {
  if (!game || !toggleFlag(game)) return;
  startLevel(session, 0);
  if (game.startedAt === null) game.startedAt = Date.now();
  ui.message.textContent = game.cells[game.selected].flagged ? "已标记。" : "已取消标记。";
  renderMine();
});
ui.reveal.addEventListener("click", () => {
  if (!game) return;
  // 在用户手势内恢复音频，后续连锁由同一个已解锁的音频上下文播放。
  explosionSound.unlock();
  const outcome = revealSelected(game);
  if (outcome === "ignored") return;
  startLevel(session, 0);
  ui.message.textContent = outcome === "revealed" ? "继续选择格子。" : "";
  if (outcome === "lost") {
    mineExplosion = { revealed: new Set(), exploded: new Set(), settled: new Set(), running: true };
    renderMine();
    ui.caption.textContent = "踩到地雷！连锁爆炸正在蔓延……";
    ui.message.textContent = "地雷正在依次引爆。";
    explosionSequence.start(explosionOrder(game));
    return;
  }
  renderMine();
  if (outcome === "won") showMineResult(outcome);
});
ui.sudokuBoard.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-index]");
  if (!button || !sudoku || !selectSudokuCell(sudoku, Number(button.dataset.index))) return;
  renderSudoku();
});
ui.sudokuKeypad.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-digit]");
  if (button) inputSudoku(Number(button.dataset.digit));
});
ui.sudokuClear.addEventListener("click", () => inputSudoku(0));
ui.sudokuCheck.addEventListener("click", () => {
  if (!sudoku) return;
  const result = checkSudoku(sudoku);
  ui.sudokuMessage.textContent = result.status === "conflict" ? "有重复数字，请检查标红的格子。"
    : result.status === "complete" ? "已完成。" : result.blanks > 0 ? `没有重复数字，还剩 ${result.blanks} 个空格。` : "已填满，但仍有错误。";
});
ui.akariBoard.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-index]");
  if (!button || !akari || !toggleBulb(akari, Number(button.dataset.index))) return;
  startLevel(session, 1);
  renderAkari();
  if (akari.complete) showAkariResult();
});
ui.resultPrimary.addEventListener("click", () => {
  if (resultMode === "mine-won") enterAkari();
  else if (resultMode === "mine-lost") restartGame();
  else if (resultMode === "akari-won") enterSudoku();
  else if (resultMode === "sudoku-won") openSettlement();
});
ui.resultSecondary.addEventListener("click", viewResult);
$("settlement-open").addEventListener("click", openSettlement);
$("settlement-home").addEventListener("click", returnHome);
document.addEventListener("keydown", (event) => {
  // 结算弹窗内循环键盘焦点，防止 Tab 落到后面的棋盘。
  const activeDialog = [$("settlement-dialog")]
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
    if (!$("settlement-dialog").classList.contains("hidden")) {
      $("settlement-dialog").classList.add("hidden");
      viewResult();
      return;
    }
    if (!ui.mineRules.classList.contains("hidden")) { ui.mineRules.classList.add("hidden"); ui.viewport.focus(); }
    else if (!ui.sudokuRules.classList.contains("hidden")) { ui.sudokuRules.classList.add("hidden"); ui.sudokuBoard.querySelector("button")?.focus(); }
    else if (!ui.akariRules.classList.contains("hidden")) { ui.akariRules.classList.add("hidden"); ui.akariBoard.querySelector("button:not(:disabled)")?.focus(); }
    else if (!ui.result.classList.contains("hidden")) {
      viewResult();
    }
  } else if (sudoku && !ui.sudokuScreen.classList.contains("hidden") && ui.sudokuRules.classList.contains("hidden") && ui.result.classList.contains("hidden")) {
    if (/^[1-9]$/.test(event.key)) inputSudoku(Number(event.key));
    else if (event.key === "Backspace" || event.key === "Delete") inputSudoku(0);
  }
});

// 计时器只更新三关用时，不会每秒重画棋盘。
window.setInterval(updateTimer, 1000);
