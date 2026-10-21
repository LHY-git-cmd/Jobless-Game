/** 成长页面装配：服务器成长、账号隔离草稿、正式开始/恢复/结算和主题预览装备。 */
import { initAuth } from '../auth.js';
import { Events } from '../lib/events.js';
import { api, createResource } from '../progression/client.js';
import { createJourneyStore } from '../progression/journey-store.js';
import { createFormalBoard } from '../games/formal-board.js';
import { formatTime } from '../session.js';

const $ = id => document.getElementById(id);
const auth = initAuth();
const instructions = {
  akari: '点击白格放置或撤下灯泡。灯光沿行列传播，墙格挡光；灯泡不能互照，数字墙格相邻灯数必须符合，照亮全部白格后提交通关。',
  mine: '棋盘为10×10、10颗雷。点击格子排雷；用操作按钮切换标记。排开全部90个安全格后提交通关。首次点击也可能踩雷，揭格须等待服务器确认。',
  sudoku: '在空格填写1至9，行、列和每个3×3宫都必须包含1至9且不重复。给定数字不可修改，填写完整后提交通关。',
};
let uid, generation = 0, selection = 0, levels = [], progress = new Map(), active = null;
let store = null, pending = null, busy = false, offset = 0, resultMs = null, ruleLevel = null;
let cosmetics = [], appearance = null, equipped = 'default', featureSet = {};
let storage = null;
try { storage = localStorage; } catch { /* 本地存储不可用时仍能完成正式服务器结算。 */ }
const board = createFormalBoard({ host: $('formal-board'),
  onChange: draft => { if (active && store) store.save(active.data, draft); }, onReveal: index => void reveal(index) });

/** 全局状态文字可读屏感知，不覆盖棋盘焦点。 */
function message(text) { $('journey-status').textContent = text; }
/** 401立即销毁旧身份，后续异步回复只能被忽略。 */
function errorMessage(error) {
  message(error.message);
  if (error.status === 401) document.dispatchEvent(new CustomEvent(Events.AUTH_EXPIRED));
}
/** 忙状态覆盖写按钮，既有锁关原因继续由服务端进度控制。 */
function setBusy(value) {
  busy = value;
  for (const id of ['formal-submit', 'formal-restart', 'formal-restore', 'journey-rules-start']) $(id).disabled = value;
  board.setDisabled(value || !active || active.data.status !== 'active' || Boolean(pending));
  if (!value && active?.data.status !== 'active') $('formal-submit').disabled = true;
  renderLevels();
}
/** 显示服务器最高星与解锁原因，不用本地等级推断权限。 */
function renderLevels() {
  $('journey-levels').replaceChildren();
  for (const level of levels.filter(item => item.game_id === 'akari')) {
    const item = progress.get(level.level_id);
    const card = document.createElement('article'); card.className = 'journey-level-card';
    const number = document.createElement('span'); number.textContent = `灯塔 ${String(level.order).padStart(2, '0')}`;
    const title = document.createElement('h3'); title.textContent = level.name;
    const stars = document.createElement('div'); stars.className = 'journey-stars';
    const count = item?.best_stars || 0; stars.textContent = '★'.repeat(count) + '☆'.repeat(3-count); stars.setAttribute('aria-label', `最高${count}星`);
    const details = document.createElement('p'); details.textContent = item?.unlocked === false ? item.locked_reasons.join('，') : `${level.rows} × ${level.cols} · 三星 ${formatTime(level.t3_ms/1000)}`;
    const button = document.createElement('button'); button.type = 'button'; button.dataset.level = level.level_id;
    button.textContent = item?.unlocked === false ? '尚未解锁' : item?.current_attempt ? '继续本关' : '探索本关';
    button.disabled = busy || item?.unlocked === false || !featureSet.progression;
    card.append(number, title, stars, details, button); $('journey-levels').append(card);
  }
}
/** 三项资格入口明确指向正式关卡，旧本地成绩不参与判定。 */
function renderEligibility(value) {
  $('journey-qualifications').replaceChildren();
  for (const item of value.requirements) {
    const link = document.createElement('a'); link.href = `./journey.html?level=${encodeURIComponent(item.level_id)}`;
    link.dataset.level = item.level_id; link.textContent = `${item.name}　${item.completed ? '已通过' : '去挑战 →'}`;
    $('journey-qualifications').append(link);
  }
}
/** 等级进度条只读取服务器累计经验，最大等级有明确终点。 */
function renderSummary(value) {
  $('journey-level').textContent = `Lv.${value.level}`;
  $('journey-summary').textContent = `${value.xp} 经验 · ${value.total_stars} 颗星`;
  $('journey-xp').max = value.next_level_xp || Math.max(1, value.xp); $('journey-xp').value = value.xp;
  $('journey-next').textContent = value.next_level_xp ? `距离下一级还需 ${value.next_level_xp-value.xp} 经验` : '十座灯塔的成长已到达当前最高等级。';
}
/** 已解锁可装备，锁定可本地预览，预览不会写入账号权益。 */
function renderCosmetics() {
  $('journey-cosmetics').replaceChildren();
  for (const item of cosmetics) {
    const button = document.createElement('button'); button.type = 'button';
    button.textContent = `${item.name} · ${uid && item.owned ? equipped === item.cosmetic_id ? '已装备' : '装备' : '预览'}`;
    button.addEventListener('click', () => void changeTheme(item)); $('journey-cosmetics').append(button);
  }
}
/** 所有服务器读取都绑定身份代次，换号后不展示迟到旧数据。 */
async function refresh() {
  const stamp = generation;
  try {
    const features = (await api('features')).data;
    if (stamp !== generation) return;
    featureSet = features;
    if (!features.progression) { levels = []; renderLevels(); message('灯塔之旅暂未开放，请先体验首页挑战与扫雷练习。'); return; }
    const catalog = await api('levels');
    if (stamp !== generation) return;
    levels = catalog.data.items;
    if (uid) {
      const [summary, entries, qualification] = await Promise.all([api('me/progression'), api('me/level-progress?limit=50'), api('me/pk-eligibility')]);
      if (stamp !== generation) return;
      progress = new Map(entries.data.items.map(item => [item.level_id, item]));
      renderSummary(summary.data); renderEligibility(qualification.data);
    } else {
      renderEligibility({ requirements: levels.filter(item => ['mine-beginner-001', 'akari-001', 'sudoku-beginner-001'].includes(item.level_id)).map(item => ({ ...item, completed: false })) });
    }
    renderLevels();
    message(uid ? '旅程已同步。首次通关与提星获得一次性经验。' : '可先查看关卡，登录后开始正式挑战。');
    if (features.cosmetics) {
      try {
        const [items, current] = await Promise.all([api(uid ? 'me/cosmetics' : 'cosmetics'), uid ? api('me/appearance') : Promise.resolve(null)]);
        if (stamp !== generation) return;
        cosmetics = items.data.items; appearance = current; equipped = current?.data.theme_id || 'default';
        document.documentElement.dataset.theme = equipped; renderCosmetics();
      } catch (error) { if (stamp === generation) $('theme-message').textContent = error.message; }
    } else $('theme-message').textContent = '主题暂未开放。';
  } catch (error) { if (stamp === generation) errorMessage(error); }
}
/** 规则查看不创建尝试；明确确认“开始”才发POST。 */
function openRules(level, started = false) {
  ruleLevel = started ? null : level;
  $('journey-rules-title').textContent = `${level.name} · 规则`;
  $('journey-rules-body').textContent = instructions[level.game_id];
  $('journey-rules-timing').textContent = started ? '本次已开始，查看规则期间继续计时。' : '本次阅读不计时，点击开始后由服务器计时；之后离开也继续。';
  $('journey-rules-start').hidden = started; $('journey-rules-cancel').textContent = started ? '返回棋盘' : '返回';
  $('journey-rules').showModal();
}
/** 恢复前必须核验服务端资源，无法把任意本地终盘兑换为奖励。 */
async function selectLevel(levelId) {
  if (busy) return;
  return auth.requireLogin(async () => {
    const stamp = generation, view = ++selection;
    const level = levels.find(item => item.level_id === levelId);
    if (!level) return;
    const item = progress.get(levelId);
    if (item?.unlocked === false) { message(item.locked_reasons.join('，')); return; }
    try {
      if (item?.current_attempt) {
        const response = await api(item.current_attempt);
        if (stamp === generation && view === selection) await showAttempt(response);
      } else openRules(level);
    } catch (error) {
      if (stamp !== generation || view !== selection) return;
      if (error.status === 410 || error.status === 404) { await refresh(); openRules(level); }
      else errorMessage(error);
    }
  });
}
/** 权威状态绑定本地草稿；中间盘可恢复，已完成显示原结算。 */
async function showAttempt(response) {
  active = response; const value = response.data;
  const saved = store.load(value); pending = saved?.pending || null;
  offset = Date.parse(value.server_now) - Date.now();
  resultMs = value.ended_at ? Math.max(0, Date.parse(value.ended_at)-Date.parse(value.started_at)) : null;
  $('formal-play').hidden = false; $('formal-result').hidden = true;
  $('formal-title').textContent = levels.find(item => item.level_id === value.level_id)?.name || value.level_id;
  $('formal-instruction').textContent = instructions[value.game_id];
  const level = levels.find(item => item.level_id === value.level_id);
  $('formal-threshold').textContent = value.mode === 'campaign' ? `三星 ≤ ${formatTime(level.t3_ms/1000)} · 二星 ≤ ${formatTime(level.t2_ms/1000)}` : '正式初级资格关 · 不发成长经验';
  board.load(value.game_id, value.puzzle, saved?.draft, value.board);
  store.save(value, board.snapshot());
  $('formal-submit').textContent = pending ? '重试确认原终盘' : '提交通关';
  $('formal-message').textContent = value.status === 'lost' ? '踩到地雷，本次未获资格。可以重新开始。' : pending ? '有尚未确认的提交，请重试或从服务器恢复。' : '棋盘已恢复，正式结果由服务器确认。';
  setBusy(false);
  if (value.status === 'completed') {
    const stamp = generation, id = value.attempt_id;
    const completion = await api(value.links.completion);
    if (stamp === generation && active?.data.attempt_id === id) displayResult(completion.data);
  }
  $('formal-play').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
/** 原始结算显示奖励差值，随后另GET最新账号摘要。 */
function displayResult(value) {
  resultMs = value.duration_ms; pending = null; store.clearPending(active.data);
  active.data.status = 'completed'; board.setDisabled(true); $('formal-submit').disabled = true;
  $('formal-result').hidden = false;
  $('formal-result').textContent = `${value.stars ? `${value.stars}星通关` : '正式资格已确认'} · 用时 ${formatTime(value.duration_ms/1000)}。本次增加 ${value.awarded_stars} 星、${value.awarded_xp} 经验。${value.newly_unlocked_level_ids.length ? '已解锁新的灯塔。' : ''}${value.newly_unlocked_cosmetic_ids.includes('starlight') ? '星光主题已解锁。' : ''}`;
  $('formal-result').focus(); $('formal-message').textContent = '结果已由服务器保存。';
}
/** 开始重试复用持久UUID；服务端已有尝试时直接恢复。 */
async function begin() {
  if (busy || !ruleLevel || !uid) return;
  const stamp = generation, level = ruleLevel;
  setBusy(true);
  try {
    const response = await createResource('attempts', { level_id: level.level_id, level_version: level.level_version, mode: level.modes[0] }, store.startKey(level.level_id));
    if (stamp !== generation) return;
    store.clearStart(level.level_id); $('journey-rules').close();
    const current = await api(response.data.links.self);
    if (stamp !== generation) return;
    await showAttempt(current); if (stamp === generation) await refresh();
  } catch (error) {
    if (stamp !== generation) return;
    if (error.code === 'attempt_active') {
      $('journey-rules').close();
      try {
        const current = await api(error.problem.links.attempt);
        if (stamp !== generation) return;
        await showAttempt(current); store.clearStart(level.level_id);
      } catch (recoveryError) { if (stamp === generation) errorMessage(recoveryError); }
    } else { errorMessage(error); $('journey-rules-timing').textContent = error.message; }
  } finally { if (stamp === generation) setBusy(false); }
}
/** 扫雷等待服务器揭格，不允许本地推断胜利或接收隐藏地图。 */
async function reveal(index) {
  if (busy || pending || !active || active.data.status !== 'active') return;
  const stamp = generation, id = active.data.attempt_id; setBusy(true);
  $('formal-message').textContent = '正在确认揭格…';
  try {
    const response = await api(`${active.data.links.self}/reveals/${index}`, { method: 'PUT', body: {} });
    if (stamp !== generation || active?.data.attempt_id !== id) return;
    active = response; board.setMine(response.data.board);
    if (response.data.ended_at) resultMs = Math.max(0, Date.parse(response.data.ended_at)-Date.parse(response.data.started_at));
    $('formal-message').textContent = response.data.board.outcome === 'won' ? '已排开全部安全格，请提交通关确认资格。' : response.data.board.outcome === 'lost' ? '踩到地雷，可以重新开始。' : '揭格已确认。';
  } catch (error) { if (stamp === generation) { errorMessage(error); $('formal-message').textContent = '揭格未确认，请从服务器恢复后继续。'; } }
  finally { if (stamp === generation) setBusy(false); }
}
/** 冻结终盘后PUT重试，明确422才解除冻结让玩家继续修改。 */
async function submit() {
  if (busy || !active || active.data.status !== 'active') return;
  const stamp = generation, id = active.data.attempt_id;
  pending ||= board.payload(); store.freeze(active.data, pending); setBusy(true);
  $('formal-message').textContent = '正在确认终盘与成长…';
  try {
    const value = await api(active.data.links.completion, { method: 'PUT', body: pending });
    if (stamp !== generation || active?.data.attempt_id !== id) return;
    displayResult(value.data); await refresh();
  } catch (error) {
    if (stamp !== generation) return;
    if (error.status === 422) { pending = null; store.clearPending(active.data); }
    errorMessage(error); $('formal-message').textContent = error.message;
    $('formal-submit').textContent = pending ? '重试确认原终盘' : '提交通关';
  } finally { if (stamp === generation) setBusy(false); }
}
/** 重开先条件放弃旧活跃尝试，再给玩家首次规则确认；不影响其他关卡。 */
async function restart() {
  if (busy || !active) return;
  const stamp = generation, level = levels.find(item => item.level_id === active.data.level_id); setBusy(true);
  try {
    if (active.data.status === 'active') {
      let latest;
      try { latest = await api(active.data.links.self); }
      catch (error) { if (![404, 410].includes(error.status)) throw error; }
      if (stamp !== generation) return;
      // 已过期/清理的旧尝试无需再放弃，可以直接确认规则并创建新尝试。
      if (latest?.data.status === 'active') await api(latest.data.links.self, { method: 'PATCH', body: { status: 'abandoned' }, headers: { 'If-Match': latest.etag } });
    }
    if (stamp !== generation) return;
    pending = null; active = null; board.clear(); $('formal-play').hidden = true; await refresh(); openRules(level);
  } catch (error) { if (stamp === generation) errorMessage(error); }
  finally { if (stamp === generation) setBusy(false); }
}
/** 预览仅改变本页CSS，装备必须经所有权和ETag校验。 */
async function changeTheme(item) {
  if (!uid || !item.owned) {
    document.documentElement.dataset.theme = item.cosmetic_id; $('theme-preview-reset').hidden = false;
    $('theme-message').textContent = `正在预览${item.name}主题，未修改账号装备。`; return;
  }
  if (busy || !appearance) return;
  const stamp = generation;
  try {
    const current = await api('me/appearance');
    if (stamp !== generation) return;
    const saved = await api('me/appearance', { method: 'PUT', body: { theme_id: item.cosmetic_id, mine_skin_id: 'default', akari_skin_id: 'default', sudoku_skin_id: 'default' }, headers: { 'If-Match': current.etag } });
    if (stamp !== generation) return;
    appearance = saved;
    equipped = appearance.data.theme_id; document.documentElement.dataset.theme = equipped; renderCosmetics();
    $('theme-message').textContent = '主题已保存。'; $('theme-preview-reset').hidden = true;
  } catch (error) { if (stamp === generation) $('theme-message').textContent = error.message; }
}
/** 换号清空棋盘/请求资格/预览，旧异步结果无法复用到新账号。 */
async function identityChanged() {
  const next = auth.currentUser?.id ?? null;
  if (uid === next) return;
  uid = next; generation++; selection++; busy = false; active = null; pending = null; ruleLevel = null;
  progress = new Map(); board.clear(); cosmetics = []; appearance = null; equipped = 'default';
  store = uid ? createJourneyStore(storage, uid, message) : null;
  document.documentElement.dataset.theme = 'default'; $('journey-rules').close(); $('formal-play').hidden = true;
  $('journey-login').hidden = Boolean(uid); $('theme-preview-reset').hidden = true;
  renderSummary({ xp: 0, level: 1, total_stars: 0, next_level_xp: 90 }); renderCosmetics(); setBusy(false);
  const stamp = generation; await refresh();
  if (stamp !== generation || !uid || !featureSet.progression) return;
  const target = new URLSearchParams(location.search).get('level') || store.selected;
  if (target && (progress.get(target)?.current_attempt || new URLSearchParams(location.search).has('level'))) await selectLevel(target);
}
$('journey-levels').addEventListener('click', event => { const target = event.target.closest('[data-level]'); if (target) void selectLevel(target.dataset.level); });
$('journey-qualifications').addEventListener('click', event => { const target = event.target.closest('[data-level]'); if (target) { event.preventDefault(); void selectLevel(target.dataset.level); } });
$('journey-login').addEventListener('click', () => void auth.requireLogin(refresh));
$('journey-refresh').addEventListener('click', () => void refresh());
$('journey-rules-start').addEventListener('click', () => void begin());
$('journey-rules-cancel').addEventListener('click', () => $('journey-rules').close());
$('formal-rules').addEventListener('click', () => { if (active) openRules(levels.find(item => item.level_id === active.data.level_id), true); });
$('formal-submit').addEventListener('click', () => void submit());
$('formal-restart').addEventListener('click', () => void restart());
$('formal-restore').addEventListener('click', () => void (async () => {
  if (busy || !active) return;
  const stamp = generation, id = active.data.attempt_id;
  try { const value = await api(active.data.links.self); if (stamp === generation && active?.data.attempt_id === id) await showAttempt(value); }
  catch (error) { if (stamp === generation) errorMessage(error); }
})());
$('formal-close').addEventListener('click', () => { if (!busy) { $('formal-play').hidden = true; $('levels-title').scrollIntoView(); } });
$('theme-preview-reset').addEventListener('click', () => { document.documentElement.dataset.theme = equipped; $('theme-preview-reset').hidden = true; $('theme-message').textContent = ''; });
document.addEventListener(Events.AUTH_CHANGED, () => void identityChanged());
const timer = setInterval(() => {
  if (!active) return;
  $('formal-timer').textContent = formatTime((resultMs ?? Math.max(0, Date.now()+offset-Date.parse(active.data.started_at)))/1000);
}, 250);
window.addEventListener('pagehide', () => { clearInterval(timer); generation++; board.destroy(); });
window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
void auth.ready.then(identityChanged);
