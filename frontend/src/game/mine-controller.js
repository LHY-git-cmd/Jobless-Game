/** 扫雷控制器：独立拥有棋盘、事件委托、连锁爆炸与音效。 */
import { createGame, revealSelected, selectCell, toggleFlag } from '../game.js';
import { createExplosionSequence, createExplosionSound, explosionOrder } from '../mine-effects.js';
import { createScope } from '../lib/lifecycle.js';

/** canPlay 和结果回调连接共享流程；settings 为当前页面共用音频偏好。 */
export function createMineController({ ui, dom, settings, canPlay, onChange, onComplete, onBusyChange }) {
  const scope = createScope();
  let game = null;
  let mineExplosion = null;
  const explosionSound = createExplosionSound(new URL("../../assets/audio/explosion.wav", import.meta.url));
  // 设置窗口与棋盘音效按钮共享同一偏好，修改开关或音量立即影响爆炸声音。
  scope.add(settings.subscribe(({ effectsEnabled, effectsVolume }) => {
    explosionSound.setMuted(!effectsEnabled);
    explosionSound.setVolume(effectsVolume);
    ui.mineSound.textContent = effectsEnabled ? "音效：开" : "音效：关";
    ui.mineSound.setAttribute("aria-label", effectsEnabled ? "关闭游戏音效" : "开启游戏音效");
    ui.mineSound.setAttribute("aria-pressed", String(!effectsEnabled));
  }));
  const explosionSequence = createExplosionSequence({
    /** 时间线先显示当前地雷，不提前泄露后续雷的位置。 */
    reveal(index) {
      mineExplosion.revealed.add(index);
      const cell = ui.board.children[index];
      cell.classList.remove("cell-flagged", "cell-selected");
      cell.classList.add("cell-mine");
      cell.setAttribute("aria-label", `第 ${Math.floor(index / 10) + 1} 行第 ${index % 10 + 1} 列，地雷`);
    },
    /** step 决定音调变化，所有声音共用已解锁的音频上下文。 */
    explode(index, step) {
      mineExplosion.exploded.add(index);
      ui.board.children[index].classList.add("cell-exploded", "cell-blasting");
      ui.board.children[index].setAttribute("aria-label", `第 ${Math.floor(index / 10) + 1} 行第 ${index % 10 + 1} 列，地雷已爆炸`);
      void explosionSound.play(step);
    },
    /** 每颗雷结束后保留终盘标记并移除瞬时爆炸样式。 */
    settle(index) {
      mineExplosion.settled.add(index);
      ui.board.children[index].classList.remove("cell-blasting");
      ui.board.children[index].classList.add("cell-spent");
    },
    /** 全部动画结束后才通知外层展示失败结果。 */
    finish() {
      mineExplosion.running = false;
      ui.caption.textContent = "连锁爆炸结束。全部地雷已显示。";
      ui.message.textContent = "10 颗地雷已引爆。";
      onComplete("lost");
    },
  });


  /** 清理旧局的计时器和尾音，避免重开或离开后继续爆炸。 */
  function cancelMineExplosion() {
    explosionSequence.stop();
    explosionSound.stop();
    mineExplosion = null;
  }

  /** 未揭开的扫雷格子不展示雷或数字。 */
  function renderMineBoard() {
    const fragment = dom.createDocumentFragment();
    game.cells.forEach((cell, index) => {
      const row = Math.floor(index / 10) + 1;
      const col = index % 10 + 1;
      const button = dom.createElement("button");
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
    onChange();
  }

  scope.listen(ui.board, "click", (event) => {
    if (!canPlay()) return;
    const button = event.target.closest("button[data-index]");
    if (!button || !game || !selectCell(game, Number(button.dataset.index))) return;
    ui.message.textContent = "格子已选中。";
    renderMine();
  });
  scope.listen(ui.flag, "click", () => {
    if (!canPlay()) return;
    if (!game || !toggleFlag(game)) return;
    ui.message.textContent = game.cells[game.selected].flagged ? "已标记。" : "已取消标记。";
    renderMine();
  });
  scope.listen(ui.reveal, "click", () => {
    if (!canPlay()) return;
    if (!game) return;
    // 在用户手势内恢复音频，后续连锁由同一个已解锁的音频上下文播放。
    explosionSound.unlock();
    const outcome = revealSelected(game);
    if (outcome === "ignored") return;
    ui.message.textContent = outcome === "revealed" ? "继续选择格子。" : "";
    if (outcome === "lost") {
      mineExplosion = { revealed: new Set(), exploded: new Set(), settled: new Set(), running: true };
      renderMine();
      onBusyChange();
      ui.caption.textContent = "踩到地雷！连锁爆炸正在蔓延……";
      ui.message.textContent = "地雷正在依次引爆。";
      explosionSequence.start(explosionOrder(game));
      return;
    }
    renderMine();
    if (outcome === "won") onComplete(outcome);
  });

  scope.listen(ui.mineSound, 'click', () => {
    settings.update({ effectsEnabled: !settings.state.effectsEnabled });
    explosionSound.unlock();
  });
  return {
    /** 棋盘引用仅供快照和规则读取，重建通过 reset/restore 明确执行。 */
    get state() { return game; },
    /** 爆炸期间阻止共享规则按钮操作。 */
    get busy() { return Boolean(mineExplosion?.running); },
    /** 新棋盘不修改共享计时，外层确认服务端重开后调用。 */
    reset() {
      cancelMineExplosion(); game = createGame();
      ui.message.textContent = ''; ui.viewport.scrollTo(0, 0);
      renderMine();
    },
    /** 恢复失败终盘直接显示全部雷，不重复播放爆炸。 */
    restore(board) {
      cancelMineExplosion(); game = board;
      if (game?.status === 'lost') {
        const mines = game.cells.flatMap((cell, index) => cell.mine ? [index] : []);
        mineExplosion = { revealed: new Set(mines), exploded: new Set(mines), settled: new Set(mines), running: false };
      }
    },
    /** 首次确认规则时让引擎使用共享的绝对计时起点。 */
    start(at) { if (game && game.startedAt === null) game.startedAt = at; },
    /** 重新展示已有棋盘。 */
    render: renderMine,
    /** 进入关卡时在用户手势内解锁音频。 */
    unlock() { explosionSound.unlock(); },
    /** 切关或重开立即取消旧动画和尾音。 */
    stopEffects: cancelMineExplosion,
    /** 返回首页前外层已保存快照；清空当前棋盘。 */
    clear() { cancelMineExplosion(); game = null; },
    /** 解除监听、取消音频设置订阅并停止爆炸。 */
    destroy() { scope.dispose(); cancelMineExplosion(); },
  };
}
