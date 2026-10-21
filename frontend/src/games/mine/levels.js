/** 扫雷练习关卡目录：稳定 ID/版本用于存档，当前三档均保持10×10。 */
export const MINE_LEVELS = Object.freeze([
  Object.freeze({ id: 'mine-easy', version: 1, name: '浅滩初探', difficulty: '入门', rows: 10, cols: 10, mineCount: 10,
    description: '留一点余地，慢慢熟悉数字的线索。' }),
  Object.freeze({ id: 'mine-normal', version: 1, name: '林间寻路', difficulty: '进阶', rows: 10, cols: 10, mineCount: 15,
    description: '线索更加密集，每一次标记都值得推敲。' }),
  Object.freeze({ id: 'mine-hard', version: 1, name: '礁石挑战', difficulty: '挑战', rows: 10, cols: 10, mineCount: 20,
    description: '更高的雷区密度，试试你的判断与耐心。' }),
]);

/** 找到明确身份的关卡；不默默把未知 ID 当作默认关卡。 */
export function mineLevel(id) {
  const level = MINE_LEVELS.find(entry => entry.id === id);
  if (!level) throw new Error('扫雷关卡不存在。');
  return level;
}
