/** 新版选关页的展示元数据与稳定入口；新关卡设计完成前不包含任何旧题目。 */
export const GAME_PAGES = Object.freeze({
  mine: Object.freeze({ id: 'mine', name: '扫雷', english: 'MINESWEEPER', title: '每一步，都离答案更近。', description: '新的推理旅程正在准备。未来从这里选择关卡，记录每一次进步。', art: 'minesweeper.webp' }),
  akari: Object.freeze({ id: 'akari', name: '照明', english: 'AKARI', title: '让光，抵达每一个角落。', description: '新的光影关卡正在准备。未来从这里点亮关卡，积累属于你的星星。', art: 'bulb.webp' }),
  sudoku: Object.freeze({ id: 'sudoku', name: '数独', english: 'SUDOKU', title: '在数字之间，发现秩序。', description: '新的九宫格挑战正在准备。未来从这里选择关卡，慢慢找到答案。', art: null }),
});

/** 兼容旧资格深链接，只定位游戏；不读取旧关卡、尝试或浏览器棋盘存档。 */
export function gameFromSearch(search = '') {
  const params = new URLSearchParams(search);
  const legacyGame = params.get('level')?.split('-')[0];
  const key = params.get('game_id') || legacyGame || 'akari';
  return Object.hasOwn(GAME_PAGES, key) ? GAME_PAGES[key] : GAME_PAGES.akari;
}

/** 使用原生链接导航，保留新标签页、浏览器返回及原生跨页动画。 */
export function gameLink(id) {
  return `./journey.html?game_id=${Object.hasOwn(GAME_PAGES, id) ? id : 'akari'}`;
}
