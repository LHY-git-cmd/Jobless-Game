/** 照明控制器：灯光、数字墙、冲突提示与棋盘点击。 */
import { AKARI_SIZE, akariCell, createAkari, inspectAkari, toggleBulb } from '../akari.js';
import { createScope } from '../lib/lifecycle.js';

/** 可玩状态和通关保存由外层决定，本模块只拥有本关棋盘。 */
export function createAkariController({ ui, dom, canPlay, onChange, onComplete }) {
  const scope = createScope();
  let akari = null;
  /** 绘制灯光覆盖和错误位置，数字墙格显示当前灯数与目标灯数。 */
  function renderAkari() {
    if (!akari) return;
    const inspection = inspectAkari(akari);
    const fragment = dom.createDocumentFragment();
    for (let index = 0; index < AKARI_SIZE * AKARI_SIZE; index += 1) {
      const type = akariCell(index);
      const row = Math.floor(index / AKARI_SIZE) + 1;
      const col = index % AKARI_SIZE + 1;
      const button = dom.createElement("button");
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
    onChange();
  }

  scope.listen(ui.akariBoard, "click", (event) => {
    if (!canPlay()) return;
    const button = event.target.closest("button[data-index]");
    if (!button || !akari || !toggleBulb(akari, Number(button.dataset.index))) return;
    renderAkari();
    if (akari.complete) onComplete("won");
  });

  return {
    /** 读取本关灯泡和完成状态供快照保存。 */
    get state() { return akari; },
    /** 服务端确认重开后创建无灯泡的新棋盘。 */
    reset() { akari = createAkari(); ui.akariMessage.textContent = ''; renderAkari(); },
    /** 应用存档中已恢复为 Set 的灯泡位置。 */
    restore(board) { akari = board; },
    /** 重新绘制灯光和数字墙提示。 */
    render: renderAkari,
    /** 离开当前账号时清空棋盘。 */
    clear() { akari = null; },
    /** 解除棋盘事件委托。 */
    destroy() { scope.dispose(); },
  };
}
