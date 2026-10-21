/** 多关卡练习存档：各关独立棋局/规则状态，游客与账号分键，不写正式存档和成绩。 */
import { createGame, elapsedSeconds, neighbors } from '../../game.js';
import { MINE_LEVELS, mineLevel } from './levels.js';

const PREFIX = 'jobless-mine-practice-v1:';

/** 恢复仅接收当前目录与版本的完整棋局；坏单关被丢弃，不影响其他关。 */
function validEntry(entry, level) {
  const game = entry?.game, count = level.rows * level.cols;
  if (entry?.version !== level.version || typeof entry.rulesOpen !== 'boolean' || !game ||
      game.level?.rows !== level.rows || game.level?.cols !== level.cols || game.level?.mineCount !== level.mineCount ||
      !Array.isArray(game.cells) || game.cells.length !== count || !['ready','playing','won','lost'].includes(game.status) ||
      ![game.startedAt, game.endedAt].every(value => value === null || Number.isFinite(value)) ||
      !(game.selected === null || Number.isInteger(game.selected) && game.selected >= 0 && game.selected < count) ||
      !(game.explodedAt === null || Number.isInteger(game.explodedAt) && game.explodedAt >= 0 && game.explodedAt < count)) return false;
  if (!game.cells.every(cell => cell && ['mine','revealed','flagged'].every(key => typeof cell[key] === 'boolean') &&
      Number.isInteger(cell.adjacent) && cell.adjacent >= 0 && cell.adjacent <= 8)) return false;
  if (game.cells.filter(cell=>cell.mine).length !== level.mineCount ||
      game.cells.filter(cell=>cell.flagged).length !== game.flaggedCount ||
      game.cells.filter(cell=>cell.revealed && !cell.mine).length !== game.revealedCount) return false;
  if (game.cells.some((cell,index) => !cell.mine && cell.adjacent !== neighbors(index,level.rows,level.cols).filter(near=>game.cells[near].mine).length)) return false;
  if (['won','lost'].includes(game.status) && (game.endedAt === null || game.startedAt === null || game.endedAt < game.startedAt)) return false;
  if (game.status === 'won' && game.revealedCount !== count-level.mineCount) return false;
  if (game.status === 'lost' && !game.cells[game.explodedAt]?.mine) return false;
  return true;
}

/** now/random 可注入以验证离开计时与确定性布雷；正式棋局始终在另一存储键。 */
export function createMinePracticeStore({ storage, userId = null, now = Date.now, random = Math.random } = {}) {
  let identity = userId, entries = {}, activeId = null;

  /** 用户 ID 只决定本地命名空间；游客固定使用 guest，与登录账号隔离。 */
  function key() { return PREFIX + (identity ?? 'guest'); }

  /** 读取本人的版本化快照，忽略损坏/未知关卡，旧正式存档原文保持不动。 */
  function load() {
    entries = {}; activeId = null;
    try {
      const snapshot = JSON.parse(storage?.getItem(key()) ?? 'null');
      if (snapshot?.version !== 1 || snapshot.userId !== identity) return;
      for (const level of MINE_LEVELS) {
        const entry = snapshot.entries?.[level.id];
        if (validEntry(entry,level)) entries[level.id] = entry;
      }
      if (entries[snapshot.activeId]) activeId = snapshot.activeId;
    } catch { /* 损坏或存储被禁用时保留可玩的内存状态。 */ }
  }

  /** 每次棋局变化同步保存，失败仅返回 false，不中断练习。 */
  function save() {
    try {
      if (!storage) return false;
      storage.setItem(key(),JSON.stringify({version:1,userId:identity,activeId,entries}));
      return true;
    } catch { return false; }
  }

  load();
  return {
    /** 按稳定 ID 访问已打开关卡，页面展示读取这些状态。 */
    get entries() { return entries; },
    /** 上次查看的关卡用于刷新后直接续玩。 */
    get activeId() { return activeId; },
    /** 当前棋盘由复用的扫雷控制器操作，保存时保持同一引用。 */
    get current() { return entries[activeId] ?? null; },
    /** 首次进入才生成随机棋盘，切换关卡不重开。 */
    select(id) {
      const level=mineLevel(id);
      activeId=id;
      entries[id] ??= {version:level.version,game:createGame(random,level),rulesOpen:true};
      save(); return entries[id];
    },
    /** 明确确认规则后开始计时，重复确认不改起点。 */
    start() {
      const entry=entries[activeId];
      if (!entry) return;
      if (entry.game.startedAt===null && !['won','lost'].includes(entry.game.status)) entry.game.startedAt=now();
      entry.rulesOpen=false; save();
    },
    /** 重看规则继续计时；首次规则只能通过 start 确认关闭。 */
    showRules() { if(entries[activeId]) { entries[activeId].rulesOpen=true; save(); } },
    /** 只替换当前关卡棋盘，其他关棋局和计时继续保留。 */
    restart() {
      if (!activeId) return;
      const level=mineLevel(activeId);
      entries[activeId]={version:level.version,game:createGame(random,level),rulesOpen:true};
      save(); return entries[activeId];
    },
    /** 绝对时间在切关、刷新和离开期间累计，游戏结束后使用 endedAt 冻结。 */
    seconds(id) { return entries[id] ? elapsedSeconds(entries[id].game,now()) : 0; },
    /** 换号先保存原身份棋盘，再载入另一命名空间，不跨账号迁移进度。 */
    setUser(id) { if(identity===id)return; save(); identity=id; load(); },
    save,
  };
}
