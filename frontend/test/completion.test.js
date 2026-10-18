/** 页面通关流程测试：用轻量 DOM 替身执行真实入口事件，验证终盘与下一关入口。 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { SUDOKU_PUZZLE, SUDOKU_SOLUTION } from "../src/sudoku.js";

/** 仅模拟页面代码使用的 DOM 接口，不替换游戏规则或通关判断。 */
class Element {
  constructor() {
    const classes = new Set();
    this.classList = {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      contains: (name) => classes.has(name),
    };
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.textContent = "";
  }
  set className(value) { this.classList.add(...value.split(/\s+/)); }
  setAttribute(name, value) { this.attributes[name] = value; }
  append(child) { this.children.push(child); }
  replaceChildren(fragment) { this.children = [...fragment.children]; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  querySelectorAll() { return this.children; }
  querySelector() { return this.children.find((child) => !child.disabled); }
  closest() { return this; }
  focus() { this.focused = true; }
  scrollTo() {}
  click(target = this) { if (!this.disabled) this.listeners.click?.({ target }); }
}

test("通关可查看终盘并继续下一关，重开和返回会清理入口", async (t) => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
  const nodes = new Map();
  for (const match of html.matchAll(/<[\w-]+\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const element = new Element();
    const className = match[1].match(/\bclass="([^"]+)"/)?.[1];
    if (className) element.className = className;
    if (/\bdisabled\b/.test(match[1])) element.disabled = true;
    nodes.set(match[2], element);
  }
  const $ = (id) => nodes.get(id);
  for (let digit = 1; digit <= 9; digit += 1) {
    const button = new Element();
    button.dataset.digit = String(digit);
    $("sudoku-keypad").append(button);
  }
  const keys = {};
  let timerTick;
  const originals = { document: globalThis.document, window: globalThis.window, random: Math.random, now: Date.now };
  let now = 100000;
  Date.now = () => now;
  globalThis.document = {
    getElementById: $,
    createElement: () => new Element(),
    createDocumentFragment: () => new Element(),
    addEventListener: (name, callback) => { keys[name] = callback; },
  };
  globalThis.window = { scrollTo() {}, setInterval(callback) { timerTick = callback; } };
  // 固定雷在第一行，通过真实排雷操作可验证扫雷通关，无需直接调用结果函数。
  Math.random = () => 0;
  t.after(() => {
    Math.random = originals.random;
    Date.now = originals.now;
    if (originals.document === undefined) delete globalThis.document;
    else globalThis.document = originals.document;
    if (originals.window === undefined) delete globalThis.window;
    else globalThis.window = originals.window;
  });
  await import("../src/main.js");
  const authorize = (id) => $(id).listeners["authorized-start"]();
  const visible = (id) => !$(id).classList.contains("hidden");
  const solveMine = () => {
    $("board").click($("board").children[99]);
    $("reveal-button").click();
  };
  const solveAkari = () => {
    for (const index of [0, 2, 11, 19, 28, 30, 36, 41, 45, 48, 54, 61, 66, 73, 80, 89, 92, 97]) {
      $("akari-board").click($("akari-board").children[index]);
    }
  };
  const fillSudoku = (indices) => {
    for (const index of indices) {
      $("sudoku-board").click($("sudoku-board").children[index]);
      const key = new Element();
      key.dataset.digit = SUDOKU_SOLUTION[index];
      $("sudoku-keypad").click(key);
    }
  };
  const sudokuBlanks = [...SUDOKU_PUZZLE].flatMap((value, index) => value === "0" ? [index] : []);

  await t.test("扫雷通关后查看结果保留终盘，右侧入口进入照明", () => {
    authorize("start-button");
    $("rules-close").click();
    assert.equal(visible("mine-next"), false);
    solveMine();
    assert.equal(visible("result-dialog"), true);
    assert.equal($("result-title").textContent, "第一关通关成功");
    assert.equal($("result-secondary").textContent, "查看结果");
    const board = $("board").children;
    $("result-secondary").click();
    assert.equal(visible("game-screen"), true);
    assert.equal(visible("result-dialog"), false);
    assert.equal(visible("mine-next"), true);
    assert.equal($("board").children, board);
    $("mine-next").click();
    assert.equal(visible("akari-screen"), true);
    assert.equal(visible("akari-rules-dialog"), true);
    assert.equal(visible("mine-next"), false);
  });

  await t.test("截图中的全亮未通关棋盘会明确提示缺灯，不提前显示下一关", () => {
    $("akari-rules-close").click();
    for (const index of [0, 2, 9, 11, 15, 28, 30, 36, 41, 48, 54, 61, 65, 73, 80, 86, 89, 92, 98]) {
      $("akari-board").click($("akari-board").children[index]);
    }
    assert.match($("akari-status").textContent, /66 \/ 66/);
    assert.equal(visible("result-dialog"), false);
    assert.equal(visible("akari-next"), false);
    assert.equal($("akari-board").children[56].classList.contains("error"), true);
    assert.match($("akari-message").textContent, /第 6 行第 7 列需 1 盏相邻灯，目前 0 盏/);
    // 调整截图中的灯位为合法摆法，确认最后一次修正会实际触发通关弹窗。
    for (const index of [9, 15, 19, 45, 65, 66, 86, 98, 97]) {
      $("akari-board").click($("akari-board").children[index]);
    }
    assert.equal(visible("result-dialog"), true);
    assert.equal($("result-title").textContent, "第二关通关成功");
    $("result-secondary").click();
    assert.equal(visible("akari-next"), true);
    $("akari-restart").click();
  });

  await t.test("照明查看结果保留灯泡，重开后隐藏下一关", () => {
    $("akari-rules-close").click();
    solveAkari();
    assert.equal($("result-title").textContent, "第二关通关成功");
    assert.equal($("result-primary").textContent, "进入第三关");
    const board = $("akari-board").children;
    $("result-secondary").click();
    assert.equal(visible("akari-screen"), true);
    assert.equal(visible("akari-next"), true);
    assert.equal($("akari-board").children, board);
    assert.match($("akari-status").textContent, /66 \/ 66/);
    $("akari-restart").click();
    assert.equal(visible("akari-next"), false);
    assert.match($("akari-status").textContent, /已放灯：0/);
  });

  await t.test("Escape 查看结果后仍可从棋盘下方进入数独", () => {
    solveAkari();
    keys.keydown({ key: "Escape" });
    assert.equal(visible("result-dialog"), false);
    assert.equal(visible("akari-next"), true);
    $("akari-next").click();
    assert.equal(visible("sudoku-screen"), true);
    assert.equal(visible("sudoku-rules-dialog"), true);
    assert.equal(visible("akari-next"), false);
  });

  await t.test("通关弹窗可直接进入下一关，返回首页不保留旧入口", () => {
    $("sudoku-back").click();
    authorize("start-button");
    $("rules-close").click();
    solveMine();
    $("result-primary").click();
    assert.equal(visible("akari-screen"), true);
    assert.equal(visible("result-dialog"), false);
    $("akari-back").click();
    assert.equal(visible("landing"), true);
    assert.equal(visible("mine-next"), false);
    assert.equal(visible("akari-next"), false);
  });

  await t.test("连续三关计时、祝贺、点击开始结算、逐关合计与返回首页", () => {
    authorize("start-button");
    now += 50000; // 规则阅读不计入游戏用时。
    $("rules-close").click();
    $("board").click($("board").children[0]);
    $("flag-button").click();
    now += 65000;
    solveMine();
    assert.equal($("timer").textContent, "01:05");
    now += 60000; // 通关弹窗和关卡间停留不计时。
    $("result-primary").click();
    $("akari-rules-close").click();
    const bulbs = [0, 2, 11, 19, 28, 30, 36, 41, 45, 48, 54, 61, 66, 73, 80, 89, 92, 97];
    $("akari-board").click($("akari-board").children[bulbs[0]]);
    now += 130000;
    for (const index of bulbs.slice(1)) $("akari-board").click($("akari-board").children[index]);
    assert.equal($("akari-timer").textContent, "02:10");
    now += 60000;
    $("result-primary").click();
    $("sudoku-rules-close").click();
    fillSudoku(sudokuBlanks.slice(0, 1));
    now += 245000;
    fillSudoku(sudokuBlanks.slice(1));
    assert.equal(visible("result-dialog"), true);
    assert.equal(visible("settlement-dialog"), false);
    assert.match($("result-title").textContent, /恭喜/);
    assert.equal($("result-primary").textContent, "开始结算");
    now += 90000;
    $("result-primary").click();
    assert.equal(visible("result-dialog"), false);
    assert.equal(visible("settlement-dialog"), true);
    assert.equal($("settlement-mine").textContent, "01:05");
    assert.equal($("settlement-akari").textContent, "02:10");
    assert.equal($("settlement-sudoku").textContent, "04:05");
    assert.equal($("settlement-total").textContent, "07:20");
    assert.equal($("settlement-ranking").disabled, true);
    // 关结算回看终盘，再次结算保持冻结结果。
    keys.keydown({ key: "Escape" });
    assert.equal(visible("settlement-open"), true);
    now += 90000;
    $("settlement-open").click();
    assert.equal($("settlement-total").textContent, "07:20");
    $("settlement-home").click();
    assert.equal(visible("landing"), true);
    assert.equal(visible("settlement-dialog"), false);
  });

  await t.test("从首页直进末关仅结算本关，未挑战关卡不伪造零秒；重开清空本关", () => {
    authorize("sudoku-entry");
    $("sudoku-rules-close").click();
    fillSudoku(sudokuBlanks.slice(0, 1));
    now += 20000;
    $("sudoku-restart").click();
    assert.equal($("sudoku-timer").textContent, "00:00");
    now += 60000;
    fillSudoku(sudokuBlanks.slice(0, 1));
    now += 8000;
    fillSudoku(sudokuBlanks.slice(1));
    $("result-secondary").click();
    assert.equal(visible("settlement-open"), true);
    $("settlement-open").click();
    assert.equal($("settlement-mine").textContent, "未挑战");
    assert.equal($("settlement-akari").textContent, "未挑战");
    assert.equal($("settlement-sudoku").textContent, "00:08");
    assert.equal($("settlement-total").textContent, "00:08");
    assert.match($("settlement-note").textContent, /跳关/);
    $("settlement-home").click();
  });

  await t.test("照明游戏过程中定时刷新，下一次点击也同步时间，未操作和重开时保持零秒", () => {
    authorize("akari-entry");
    $("akari-rules-close").click();
    now += 5000;
    timerTick();
    assert.equal($("akari-timer").textContent, "00:00");
    $("akari-board").click($("akari-board").children[0]);
    now += 3000;
    timerTick();
    assert.equal($("akari-timer").textContent, "00:03");
    // 即使周期回调暂未运行，操作棋盘也会刷新显示。
    now += 2000;
    $("akari-board").click($("akari-board").children[2]);
    assert.equal($("akari-timer").textContent, "00:05");
    $("akari-restart").click();
    assert.equal($("akari-timer").textContent, "00:00");
    $("akari-back").click();
  });
});
