/** 扫雷练习关卡目录：三种尺寸各三档，原10×10 ID/版本保持存档兼容。 */
export const MINE_BOARD_SIZES = Object.freeze([10,15,20]);

export const MINE_LEVELS = Object.freeze([
  Object.freeze({ id: 'mine-easy', version: 1, name: '浅滩初探', difficulty: '入门', rows: 10, cols: 10, mineCount: 10,
    description: '留一点余地，慢慢熟悉数字的线索。' }),
  Object.freeze({ id: 'mine-normal', version: 1, name: '林间寻路', difficulty: '进阶', rows: 10, cols: 10, mineCount: 15,
    description: '线索更加密集，每一次标记都值得推敲。' }),
  Object.freeze({ id: 'mine-hard', version: 1, name: '礁石挑战', difficulty: '挑战', rows: 10, cols: 10, mineCount: 20,
    description: '更高的雷区密度，试试你的判断与耐心。' }),
  Object.freeze({ id: 'mine-15-easy', version: 1, name: '远湾初探', difficulty: '入门', rows: 15, cols: 15, mineCount: 23,
    description: '向更远的海湾出发，沿着线索慢慢探索。' }),
  Object.freeze({ id: 'mine-15-normal', version: 1, name: '松林迷径', difficulty: '进阶', rows: 15, cols: 15, mineCount: 34,
    description: '让数字串起路径，寻找下一处安全落脚点。' }),
  Object.freeze({ id: 'mine-15-hard', version: 1, name: '峭壁挑战', difficulty: '挑战', rows: 15, cols: 15, mineCount: 45,
    description: '在更密集的雷区中，推敲每一步的可能。' }),
  Object.freeze({ id: 'mine-20-easy', version: 1, name: '深海初探', difficulty: '入门', rows: 20, cols: 20, mineCount: 40,
    description: '四百个格子的探索，从眼前的一条线索开始。' }),
  Object.freeze({ id: 'mine-20-normal', version: 1, name: '群岛寻路', difficulty: '进阶', rows: 20, cols: 20, mineCount: 60,
    description: '把分散的线索连起来，找到穿过群岛的路。' }),
  Object.freeze({ id: 'mine-20-hard', version: 1, name: '风暴挑战', difficulty: '挑战', rows: 20, cols: 20, mineCount: 80,
    description: '最大的雷区，最密集的考验，慢一点再落子。' }),
]);

/** 找到明确身份的关卡；不默默把未知 ID 当作默认关卡。 */
export function mineLevel(id) {
  const level = MINE_LEVELS.find(entry => entry.id === id);
  if (!level) throw new Error('扫雷关卡不存在。');
  return level;
}
