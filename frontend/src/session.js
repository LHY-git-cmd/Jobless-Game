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

/** 当前关卡重开只清空本关及后续成绩，保留已完成的前序关卡。 */
export function restartLevel(session, index) {
  session.levels.splice(index, session.levels.length - index,
    ...LEVELS.slice(index).map(() => ({ startedAt: null, seconds: null })));
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

/** 合计只累加各关展示的整数秒，保证逐项相加与总时长一致。 */
export function sessionSummary(session) {
  const times = session.levels.map((level) => level.seconds);
  return { times, total: times.reduce((sum, seconds) => sum + (seconds ?? 0), 0), complete: times.every((seconds) => seconds !== null) };
}

/** 计时统一显示为分:秒，超过一小时显示时:分:秒。 */
export function formatTime(seconds) {
  const value = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(value / 60);
  const tail = String(value % 60).padStart(2, "0");
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}:${tail}`
    : `${String(minutes).padStart(2, "0")}:${tail}`;
}
