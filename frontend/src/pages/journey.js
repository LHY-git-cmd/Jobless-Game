/** 独立选关页：扫雷/数独五档正式游戏，照明保留占位；账号成长集中在顶部头像。 */
import { initAuth } from '../features/account/auth.js';
import { Events } from '../shared/events.js';
import { api } from '../features/progression/client.js';
import { gameFromSearch, gameLink } from '../games/catalog.js';
import { createMineJourney } from '../games/mine/controller.js';
import { createSudokuJourney } from '../games/sudoku/controller.js';

const $ = id => document.getElementById(id);
const game = gameFromSearch(location.search);
const auth = initAuth();
let gameJourney;
let uid, epoch = 0, readVersion = 0, cosmetics = [], equipped = 'default', themeBusy = false;

/** URL决定游戏身份，刷新和返回不恢复任何已下线的题目。 */
function renderGame() {
  document.title = `${game.name}选关 · 无职游戏`;
  document.body.dataset.game = game.id;
  $('levels-title').textContent = game.id==='mine'?'扫雷':`${game.name}关卡`;
  document.querySelector('.site-nav [aria-current="page"]').href = gameLink(game.id);
  $('catalog-empty-title').textContent = `${game.name}关卡重新设计中`;
  if (game.art) {
    const image = document.createElement('img'); image.src = `./assets/${game.art}`; image.alt = ''; image.width = image.height = 96;
    $('catalog-art').append(image);
  } else {
    const grid = document.createElement('span'); grid.className = 'sudoku-art catalog-sudoku-art';
    for (const digit of ['1', '2', '', '', '5', '6', '7', '', '9']) { const cell = document.createElement('span'); cell.textContent = digit; grid.append(cell); }
    $('catalog-art').append(grid);
  }
  if(game.id==='mine'||game.id==='sudoku') {
    $('catalog-empty').hidden=true;
    const host=document.createElement('div');host.className=game.id==='mine'?'mine-host':'sudoku-host';host.id=game.id+'-journey';
    $('catalog-empty').after(host);
    gameJourney=(game.id==='mine'?createMineJourney:createSudokuJourney)({host,auth,onReward:()=>void refresh()});
  }
}

/** 旧资格链接进入对应游戏目录，不自动打开历史版本的旧棋盘。 */
function renderQualifications(value) {
  $('journey-qualifications').replaceChildren();
  for (const item of value.requirements) {
    const link = document.createElement('a');
    link.href = gameLink(gameFromSearch(`?level=${encodeURIComponent(item.level_id)}`).id);
    link.textContent = `${item.name}　${item.completed ? '已通过' : /^(mine|sudoku)-/.test(item.level_id) ? '前往简单关挑战' : '新关卡待开放'}`;
    $('journey-qualifications').append(link);
  }
}

/** 主题预览与永久权益仍按既有服务端结果显示。 */
function renderCosmetics() {
  $('journey-cosmetics').replaceChildren();
  for (const item of cosmetics) {
    const button = document.createElement('button'); button.type = 'button'; button.disabled = themeBusy;
    button.textContent = `${item.name} · ${uid && item.owned ? item.cosmetic_id === equipped ? '已装备' : '装备' : '预览'}`;
    button.addEventListener('click', () => void changeTheme(item)); $('journey-cosmetics').append(button);
  }
}

/** 401使用共享身份失效事件，旧请求在换号后不得写回页面。 */
function showError(error) {
  $('journey-status').textContent = error.message;
  if (error.status === 401) document.dispatchEvent(new CustomEvent(Events.AUTH_EXPIRED));
}

/** 页面只查询资格/主题；顶部头像独立读取成长，避免重复请求。 */
async function refresh() {
  const stamp = epoch, version = ++readVersion;
  const current = () => stamp === epoch && version === readVersion;
  try {
    const features = (await api('features')).data;
    if (!current()) return;
    if (uid && features.progression) {
      const qualification = await api('me/pk-eligibility');
      if (!current()) return;
      renderQualifications(qualification.data);
      $('journey-status').textContent = '账号资料已同步。';
    } else {
      $('journey-qualifications').textContent = '新的资格关卡正在准备。';
      $('journey-status').textContent = uid ? '账号资料暂不可用。' : '登录后可查看账号资料。';
    }
    if (features.cosmetics) {
      try {
        const [items, appearance] = await Promise.all([api(uid ? 'me/cosmetics' : 'cosmetics'), uid ? api('me/appearance') : Promise.resolve(null)]);
        if (!current()) return;
        cosmetics = items.data.items; equipped = appearance?.data.theme_id || 'default';
        document.documentElement.dataset.theme = equipped; renderCosmetics(); $('theme-message').textContent = '';
      } catch (error) { if (current()) { $('theme-message').textContent = error.message; if (error.status === 401) showError(error); } }
    } else { cosmetics = []; renderCosmetics(); $('theme-message').textContent = '主题暂未开放。'; }
  } catch (error) {
    if (!current()) return;
    if (error.status === 404) $('journey-status').textContent = '账号资料暂不可用。';
    else showError(error);
  }
}

/** 预览不写权益，装备仍校验账号、已有主题和最新ETag。 */
async function changeTheme(item) {
  if (!uid || !item.owned) {
    document.documentElement.dataset.theme = item.cosmetic_id; $('theme-preview-reset').hidden = false;
    $('theme-message').textContent = `正在预览${item.name}主题，未修改账号装备。`; return;
  }
  if (themeBusy) return;
  const stamp = epoch; themeBusy = true; renderCosmetics();
  try {
    const current = await api('me/appearance');
    if (stamp !== epoch) return;
    const saved = await api('me/appearance', { method: 'PUT', body: { theme_id: item.cosmetic_id, mine_skin_id: 'default', akari_skin_id: 'default', sudoku_skin_id: 'default' }, headers: { 'If-Match': current.etag } });
    if (stamp !== epoch) return;
    equipped = saved.data.theme_id; document.documentElement.dataset.theme = equipped;
    $('theme-preview-reset').hidden = true; $('theme-message').textContent = '主题已保存。';
  } catch (error) { if (stamp === epoch) { $('theme-message').textContent = error.message; if (error.status === 401) showError(error); } }
  finally { if (stamp === epoch) { themeBusy = false; renderCosmetics(); } }
}

/** 换号清空显示并失效旧读取，不触碰旧游戏本地存档。 */
async function identityChanged() {
  const next = auth.currentUser?.id ?? null;
  if (uid === next) return;
  uid = next; epoch++; readVersion++; themeBusy = false; cosmetics = []; equipped = 'default';
  document.documentElement.dataset.theme = 'default'; $('journey-login').hidden = Boolean(uid); $('theme-preview-reset').hidden = true;
  $('journey-qualifications').replaceChildren(); renderCosmetics();
  await Promise.all([refresh(),gameJourney?.setUser(uid)]);
}

renderGame();
$('journey-refresh').addEventListener('click', () => {void refresh();void gameJourney?.refresh();});
$('journey-login').addEventListener('click', () => void auth.requireLogin(refresh));
$('theme-preview-reset').addEventListener('click', () => { document.documentElement.dataset.theme = equipped; $('theme-preview-reset').hidden = true; $('theme-message').textContent = ''; });
document.addEventListener(Events.AUTH_CHANGED, () => void identityChanged());
window.addEventListener('pagehide', () => { epoch++; readVersion++; gameJourney?.destroy(); });
window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
void auth.ready.then(identityChanged);
