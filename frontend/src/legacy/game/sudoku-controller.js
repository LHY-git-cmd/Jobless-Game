/** 数独控制器：题盘渲染、候选笔记、输入与冲突检查。 */
import { createSudoku, selectSudokuCell, setSudokuValue, toggleSudokuNote, sudokuConflicts, checkSudoku } from '../../games/sudoku/rules.js';
import { createScope } from '../../shared/lifecycle.js';

/** onChange 由外层协调计时与保存，onComplete 仅报告通关。 */
export function createSudokuController({ ui, dom, canPlay, onChange, onComplete }) {
  const scope = createScope();
  let sudoku = null;
  /** 显示数独棋盘；重复数字用颜色标识，题目数字不能修改。 */
  function renderSudoku() {
    if (!sudoku) return;
    const conflicts = sudokuConflicts(sudoku);
    const selected = sudoku.selected;
    const fragment = dom.createDocumentFragment();
    sudoku.values.forEach((value, index) => {
      const row = Math.floor(index / 9);
      const col = index % 9;
      const button = dom.createElement("button");
      button.type = "button";
      button.className = "sudoku-cell";
      button.dataset.index = String(index);
      button.textContent = value === 0 ? "" : String(value);
      const mask = value === 0 ? sudoku.notes[index] : 0;
      const digits = Array.from({ length: 9 }, (_, offset) => offset + 1).filter(digit => mask & (1 << (digit - 1)));
      if (mask) {
        const notes = dom.createElement("span");
        notes.className = "sudoku-notes";
        notes.setAttribute("aria-hidden", "true");
        // 每个候选数使用固定九宫位置，空位仍占格，方便快速扫视与比较。
        for (let digit = 1; digit <= 9; digit++) {
          const slot = dom.createElement("span");
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
    onChange();
  }

  /** 数独确认开始后允许输入，查看规则或异步重开期间不可修改棋盘。 */
  function inputSudoku(value) {
    if (!canPlay()) return;
    if (!sudoku) return;
    // 清除操作始终擦除本格内容；1–9 则按当前模式写入笔记或正式答案。
    const noting = sudoku.notesMode && value !== 0;
    if (!(noting ? toggleSudokuNote(sudoku, value) : setSudokuValue(sudoku, value))) return;
    ui.sudokuMessage.textContent = noting ? "候选数已更新。" : sudoku.complete ? "" : sudokuConflicts(sudoku).size > 0 ? "存在重复数字，请检查。" : "";
    renderSudoku();
    if (sudoku.complete) onComplete("won");
  }

  scope.listen(ui.sudokuBoard, "click", (event) => {
    if (!canPlay()) return;
    const button = event.target.closest("button[data-index]");
    if (!button || !sudoku || !selectSudokuCell(sudoku, Number(button.dataset.index))) return;
    renderSudoku();
  });
  scope.listen(ui.sudokuKeypad, "click", (event) => {
    const button = event.target.closest("button[data-digit]");
    if (button) inputSudoku(Number(button.dataset.digit));
  });
  scope.listen(ui.sudokuClear, "click", () => inputSudoku(0));
  scope.listen(ui.sudokuNotes, "click", () => {
    if (!sudoku || !canPlay()) return;
    sudoku.notesMode = !sudoku.notesMode;
    renderSudoku();
  });
  scope.listen(ui.sudokuCheck, "click", () => {
    if (!sudoku) return;
    const result = checkSudoku(sudoku);
    ui.sudokuMessage.textContent = result.status === "conflict" ? "有重复数字，请检查标红的格子。"
      : result.status === "complete" ? "已完成。" : result.blanks > 0 ? `没有重复数字，还剩 ${result.blanks} 个空格。` : "已填满，但仍有错误。";
  });

  return {
    /** 读取本关规则状态供快照保存。 */
    get state() { return sudoku; },
    /** 服务端确认重开后创建固定题盘。 */
    reset() { sudoku = createSudoku(); ui.sudokuMessage.textContent = ''; renderSudoku(); },
    /** 应用已经过存档校验的题盘和笔记。 */
    restore(board) { sudoku = board; },
    /** 重绘本关，不接触其他关卡。 */
    render: renderSudoku,
    /** 键盘和屏幕数字键共享输入校验。 */
    input: inputSudoku,
    /** 离开当前账号时清空棋盘。 */
    clear() { sudoku = null; },
    /** 解除棋盘、键盘、清除、笔记与检查按钮监听。 */
    destroy() { scope.dispose(); },
  };
}
