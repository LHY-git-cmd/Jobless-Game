/** 正式尝试/竞速共用棋盘视图：本地照明运算，数独编辑，扫雷仅显示权威揭格。 */
import { createAkari, toggleBulb, inspectAkari, akariCell } from './akari/rules.js';

/** onChange仅保存草稿，onReveal必须调用正式服务器；不在本地发放成长。 */
export function createFormalBoard({ host, onChange = () => {}, onReveal = () => {} }) {
  let puzzle, game, draft, akari, disabled = false, mine = { revealed: [], outcome: 'active' };
  let flagMode = false;
  /** 所有玩家输入用DOM属性写入；只对已知静态棋盘节点创建结构。 */
  function render() {
    if (!puzzle) { host.replaceChildren(); return; }
    const focus = host.contains(document.activeElement) ? document.activeElement?.dataset.index : null;
    const board = document.createElement('div');
    board.className = `formal-board formal-${game}`;
    board.style.setProperty('--cols', puzzle.cols);
    board.setAttribute('role', 'group');
    board.setAttribute('aria-label', `${game === 'akari' ? '照明' : game === 'sudoku' ? '数独' : '扫雷'}棋盘`);
    const inspection = game === 'akari' ? inspectAkari(akari) : null;
    const revealed = new Map(mine.revealed.map(cell => [cell.index, cell.value]));
    for (let index = 0; index < puzzle.rows * puzzle.cols; index++) {
      const r = Math.floor(index / puzzle.cols), c = index % puzzle.cols;
      const label = `第${r+1}行第${c+1}列`;
      const cell = document.createElement(game === 'sudoku' ? 'input' : 'button');
      cell.dataset.index = index;
      cell.className = 'formal-cell';
      if (game === 'sudoku') {
        cell.type = 'text'; cell.inputMode = 'numeric'; cell.maxLength = 1;
        cell.value = draft.values[index] || '';
        cell.disabled = disabled || Boolean(puzzle.values[index]);
        cell.classList.toggle('given', Boolean(puzzle.values[index]));
        cell.setAttribute('aria-label', `${label}${puzzle.values[index] ? '，已给数字' : '，填写数字'}`);
        if (c === 2 || c === 5) cell.classList.add('box-right');
        if (r === 2 || r === 5) cell.classList.add('box-bottom');
      } else {
        cell.type = 'button';
        cell.disabled = disabled;
        if (game === 'akari') {
          const type = akariCell(index, akari), bulb = akari.bulbs.has(index);
          cell.classList.add('akari-cell');
          if (type !== '.') { cell.classList.add('wall'); cell.disabled = true; cell.textContent = type === '#' ? '' : type; }
          if (inspection.lit.has(index)) cell.classList.add('lit');
          if (bulb) cell.classList.add('bulb');
          if (inspection.conflictingBulbs.has(index) || inspection.wrongClues.has(index)) cell.classList.add('error');
          cell.setAttribute('aria-label', `${label}，${type !== '.' ? `墙格${type === '#' ? '' : type}` : bulb ? '已放灯' : inspection.lit.has(index) ? '已照亮' : '未照亮'}`);
          if (type === '.') cell.setAttribute('aria-pressed', String(bulb));
        } else {
          const value = revealed.get(index), flagged = draft.flags.includes(index);
          cell.classList.add('mine-cell');
          cell.classList.toggle('revealed', value !== undefined);
          cell.textContent = value === -1 || mine.mines?.includes(index) ? '雷' : value > 0 ? value : value === 0 ? '' : flagged ? '旗' : '';
          cell.disabled ||= value !== undefined || mine.outcome !== 'active';
          cell.setAttribute('aria-label', `${label}，${value === undefined ? flagged ? '已标记' : '未揭开' : value === -1 ? '地雷' : `附近${value}雷`}`);
        }
      }
      board.append(cell);
    }
    host.replaceChildren(board);
    if (game === 'mine') {
      const mode = document.createElement('button'); mode.type = 'button'; mode.className = 'mine-mode';
      mode.textContent = flagMode ? '操作：标记（点击切换排雷）' : '操作：排雷（点击切换标记）';
      mode.setAttribute('aria-pressed', String(flagMode)); mode.disabled = disabled;
      mode.addEventListener('click', () => { flagMode = !flagMode; render(); }); host.append(mode);
    }
    if (focus !== undefined && focus !== null) host.querySelector(`[data-index="${focus}"]`)?.focus({ preventScroll: true });
  }
  /** 一次交互只改变本地终盘或发起一个服务器揭格请求。 */
  function click(event) {
    const target = event.target.closest('[data-index]');
    if (!target || disabled) return;
    const index = Number(target.dataset.index);
    if (game === 'akari') {
      // 允许完成后继续改盘，只有服务端确认成功才冻结正式结果。
      akari.complete = false;
      if (!toggleBulb(akari, index)) return;
      draft.bulbs = [...akari.bulbs]; onChange(snapshot()); render();
    } else if (game === 'mine') {
      if (flagMode) {
        draft.flags = draft.flags.includes(index) ? draft.flags.filter(i => i !== index) : [...draft.flags, index];
        onChange(snapshot()); render();
      } else if (!draft.flags.includes(index)) onReveal(index);
    }
  }
  /** 数独输入只接受1～9；保留焦点，不在每次按键重建棋盘。 */
  function input(event) {
    if (disabled || game !== 'sudoku' || !event.target.matches('[data-index]')) return;
    const index = Number(event.target.dataset.index);
    if (puzzle.values[index]) return;
    const value = /^[1-9]$/.test(event.target.value) ? Number(event.target.value) : 0;
    event.target.value = value || ''; draft.values[index] = value; onChange(snapshot());
  }
  /** 箭头键在可操作格间移动，棋盘超宽时由区域内滚动保留焦点。 */
  function keydown(event) {
    if (!puzzle || !event.target.matches('[data-index]')) return;
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -puzzle.cols, ArrowDown: puzzle.cols }[event.key];
    if (!step) return;
    let index = Number(event.target.dataset.index) + step;
    while (index >= 0 && index < puzzle.rows*puzzle.cols) {
      const next = host.querySelector(`[data-index="${index}"]`);
      if (next && !next.disabled) { event.preventDefault(); next.focus(); break; }
      index += step;
    }
  }
  /** 草稿深拷贝，防止待重试终盘被后续编辑改变。 */
  function snapshot() { return structuredClone(draft); }
  host.addEventListener('click', click); host.addEventListener('input', input); host.addEventListener('keydown', keydown);
  return {
    /** 绑定已GET核验的尝试/对局及匹配版本草稿。 */
    load(kind, data, saved = {}, authority = null) {
      game = kind; puzzle = data; flagMode = false;
      draft = { bulbs: Array.isArray(saved.bulbs) ? saved.bulbs.filter(i => Number.isInteger(i) && data.map?.join('')[i] === '.') : [],
        values: Array.isArray(saved.values) && saved.values.length === 81 ? saved.values.map((v, i) => data.values?.[i] || (Number.isInteger(v) && v >= 0 && v <= 9 ? v : 0)) : [...(data.values || [])],
        flags: Array.isArray(saved.flags) ? saved.flags.filter(i => Number.isInteger(i) && i >= 0 && i < 100) : [] };
      if (kind === 'akari') { akari = createAkari(data); akari.bulbs = new Set(draft.bulbs); }
      mine = authority || { revealed: [], outcome: 'active' }; render();
    },
    /** 短写请求期间禁止重复交互，但不本地假设揭格结果。 */
    setDisabled(value) { disabled = value; render(); },
    /** 恢复扫雷服务器已揭盘，本地只保留未揭格的旗标。 */
    setMine(value) { mine = value; render(); },
    snapshot,
    /** 提交只含该游戏允许的终盘字段。 */
    payload() { return game === 'akari' ? { bulbs: [...akari.bulbs] } : game === 'sudoku' ? { values: [...draft.values] } : {}; },
    /** 账号切换清空所有内存棋盘。 */
    clear() { puzzle = null; draft = {}; render(); },
    /** 页面销毁移除事件监听。 */
    destroy() { host.removeEventListener('click', click); host.removeEventListener('input', input); host.removeEventListener('keydown', keydown); this.clear(); },
  };
}
