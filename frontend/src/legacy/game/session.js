/** 三关挑战计时：首次确认开始后持续累计，通关冻结；首次读规则、关卡间和结算停留不计时。 */

export const LEVELS = Object.freeze([
  { id: "mine", name: "扫雷" },
  { id: "akari", name: "照明" },
  { id: "sudoku", name: "数独" },
]);

/** 新的一轮挑战；未玩过或尚未通关的关卡没有成绩。 */
export function createSession() {
  return { levels: LEVELS.map(() => ({ startedAt: null, seconds: null })) };
}

/** 三个关卡独立计时，重开只清空指定关卡。 */
export function restartLevel(session, index) {
  session.levels[index] = { startedAt: null, seconds: null };
}

/** 首次确认开始时启动计时；重看规则或重复确认不会改变起点。 */
export function startLevel(session, index, now = Date.now()) {
  const level = session.levels[index];
  if (level.startedAt === null && level.seconds === null) level.startedAt = now;
}

/** 通关立即冻结秒数，反复打开结算不会继续累加。 */
export function completeLevel(session, index, now = Date.now()) {
  const level = session.levels[index];
  if (level.seconds === null) {
    level.seconds = Math.max(0, Math.floor((now - (level.startedAt ?? now)) / 1000));
  }
}

/** 读取正在进行或已冻结的用时，用于关卡内计时与结算共用同一口径。 */
export function levelSeconds(session, index, now = Date.now()) {
  const level = session.levels[index];
  return level.seconds ?? (level.startedAt === null ? 0 : Math.max(0, Math.floor((now - level.startedAt) / 1000)));
}

export { formatTime } from '../../shared/time.js';
