/** 双人竞速页面：REST写操作、SSE通知后GET快照、账号隔离及原终盘重试。 */
import { initAuth } from '../features/account/auth.js';
import { Events } from '../shared/events.js';
import { api, createResource } from '../features/progression/client.js';
import { subscribeEvents } from '../features/pk/events.js';
import { createFormalBoard } from '../games/formal-board.js';
import { formatTime } from '../shared/time.js';

const $ = id => document.getElementById(id);
const auth = initAuth();
let uid, generation = 0, refreshVersion = 0, busy = false, subscription = null, refreshTimer = null;
let features = {}, eligible = false, room = null, ticket = null, boardRoom = null, offset = 0;
let memory = { requests: {}, drafts: {}, lastRoom: null }, storage = null;
try { storage = localStorage; } catch { /* 存储禁用时仍允许本页对局，提示刷新可能丢草稿。 */ }
const board = createFormalBoard({ host: $('pk-board'), onChange: draft => {
  if (room) { memory.drafts[room.data.room_id] = { ...memory.drafts[room.data.room_id], draft }; save(); }
} });

/** 每账号最多保留一局本地草稿和少量创建重试凭据。 */
function save() {
  if (!uid) return;
  try { storage?.setItem(`jobless-pk-v1:${uid}`, JSON.stringify(memory)); }
  catch { $('pk-message').textContent = '本地存储不可用，刷新后未提交布局可能丢失。'; }
}
/** 401立即广播身份失效，销毁订阅与棋盘。 */
function showError(error) {
  $('pk-message').textContent = error.message;
  if (error.status === 401) document.dispatchEvent(new CustomEvent(Events.AUTH_EXPIRED));
}
/** 写请求期间按钮不可重复触发，等待和终态保持可读。 */
function controls() {
  $('pk-lobby').hidden = !uid || !eligible || Boolean(ticket?.data.status === 'waiting') || Boolean(room && ['waiting', 'countdown', 'playing'].includes(room.data.status));
  for (const id of ['pk-create', 'pk-match', 'pk-ready', 'pk-leave', 'pk-cancel', 'pk-submit']) $(id).disabled = busy;
  $('pk-match').disabled ||= !features.matchmaking;
  $('pk-join-form').querySelector('button').disabled = busy;
  const me = room?.data.members.find(member => member.is_me);
  const pending = room && memory.drafts[room.data.room_id]?.pending;
  board.setDisabled(busy || !room || room.data.status !== 'playing' || Boolean(me?.completed) || Boolean(pending));
  $('pk-submit').hidden = !room || room.data.status !== 'playing';
  $('pk-submit').disabled ||= Boolean(me?.completed);
  $('pk-submit').textContent = me?.completed ? '解答已确认，等待结算' : pending ? '重试确认原解答' : '提交解答';
}
/** 三项缺失状态直接显示服务器表示，链接进入正式入口。 */
function requirements(value) {
  eligible = value.eligible; $('pk-locked').hidden = eligible;
  $('pk-requirements').replaceChildren();
  for (const item of value.requirements) {
    const link = document.createElement('a'); link.href = `./journey.html?level=${encodeURIComponent(item.level_id)}`;
    link.textContent = `${item.name}　${item.completed ? '已通过' : '去挑战 →'}`; $('pk-requirements').append(link);
  }
}
/** 房间快照不覆盖正在填写的本地解答；地图首次下发时才绑定棋盘。 */
function renderRoom(value) {
  room = value; const data = value.data;
  offset = Date.parse(data.server_now) - Date.now(); memory.lastRoom = data.room_id; save();
  $('pk-room').hidden = false; $('pk-room-code').textContent = data.room_code;
  const statuses = { waiting: '等待朋友加入，双方准备后开始。', countdown: '双方已准备，倒计时中…', playing: '对局进行中，请点亮全部白格后提交。', finished: '对局已结束。', cancelled: '本次对局已作废。', expired: '房间等待已超时。' };
  $('pk-room-status').textContent = statuses[data.status] || data.status;
  $('pk-members').replaceChildren();
  for (const member of data.members) {
    const element = document.createElement('div'); element.className = 'pk-member';
    element.textContent = `${member.username}${member.is_me ? '（你）' : ''} · ${member.completed ? '有效解答已提交' : member.ready ? '已准备' : '未准备'} · ${member.online ? '在线' : '连接恢复中'}`;
    $('pk-members').append(element);
  }
  const me = data.members.find(member => member.is_me);
  $('pk-ready').hidden = data.status !== 'waiting'; $('pk-ready').textContent = me?.ready ? '取消准备' : '我准备好了';
  $('pk-leave').textContent = data.status === 'playing' ? '退出对局（将判负）' : '离开房间';
  if (data.puzzle && boardRoom !== data.room_id) {
    boardRoom = data.room_id;
    const saved = memory.drafts[data.room_id];
    memory.drafts = { [data.room_id]: saved || {} }; save();
    board.load('akari', data.puzzle, saved?.draft);
  } else if (!data.puzzle) { boardRoom = null; board.clear(); }
  $('pk-board').hidden = !data.puzzle;
  $('pk-result').hidden = !data.result;
  if (data.result) {
    const result = data.result;
    const mine = me?.user_id;
    const reasons = { server_restart: '服务重启', both_offline: '双方离线', waiting_timeout: '等待超时', match_timeout: '比赛超时', player_left: '玩家主动离开', opponent_disconnected: '对手断线超时', empty_room: '房间已空' };
    $('pk-result').textContent = `${result.outcome === 'draw' ? '本局平局' : result.outcome === 'win' ? result.winner_id === mine ? '你赢得了本局竞速' : '同行者先一步完成' : '对局作废'}${reasons[result.reason] ? ` · ${reasons[result.reason]}` : ''}。对局不发放成长奖励。`;
  }
  if (me?.completed && memory.drafts[data.room_id]?.pending) { memory.drafts[data.room_id].pending = null; save(); }
  controls(); updateClock();
}
/** 刷新/重连只读本人当前资源，事件丢失也不丢最终结果。 */
async function refreshState() {
  if (!uid || !features.pk_rooms) return;
  const stamp = generation, version = ++refreshVersion;
  try {
    const current = await api('me/rooms?status=active');
    if (stamp !== generation || version !== refreshVersion) return;
    if (current.data.items.length) {
      const response = await api(current.data.items[0].links.self);
      if (stamp !== generation || version !== refreshVersion) return;
      ticket = null; $('pk-waiting').hidden = true; memory.requests = {}; save(); renderRoom(response); return;
    }
    if (features.matchmaking) {
      try {
        const currentTicket = await api('me/matchmaking-ticket');
        if (stamp !== generation || version !== refreshVersion) return;
        ticket = currentTicket;
        if (currentTicket.data.status === 'waiting') {
          room = null; boardRoom = null; board.clear(); $('pk-room').hidden = true;
          $('pk-waiting').hidden = false; $('pk-ticket-status').textContent = '正在寻找同行者…';
          memory.requests = {}; save(); controls(); return;
        }
      } catch (error) { if (error.status !== 404) throw error; }
    }
    if (stamp !== generation || version !== refreshVersion) return;
    if (ticket) {
      const previous = await api(ticket.data.links.self);
      if (stamp !== generation || version !== refreshVersion) return;
      ticket = previous;
      $('pk-message').textContent = previous.data.status === 'expired' ? '暂时没有匹配到同行者，可再次尝试。' : '匹配已结束。';
    }
    ticket = null; $('pk-waiting').hidden = true;
    if (memory.lastRoom) {
      try {
        const previous = await api(`rooms/${memory.lastRoom}`);
        if (stamp !== generation || version !== refreshVersion) return;
        renderRoom(previous);
      } catch (error) { if (error.status !== 404) throw error; if (stamp !== generation || version !== refreshVersion) return; room = null; $('pk-room').hidden = true; }
    }
    controls();
  } catch (error) { if (stamp === generation && version === refreshVersion) showError(error); }
}
/** 合并短时间内同一资源的多条通知，避免准备/开始通知形成GET突发。 */
function scheduleRefresh() {
  if (refreshTimer) return;
  refreshTimer = setTimeout(() => { refreshTimer = null; void refreshState(); }, 80);
}
/** 原创建键跨刷新保留；负载不同使用新的请求身份。 */
function intent(kind, data) {
  const previous = memory.requests[kind];
  if (!previous || JSON.stringify(previous.data) !== JSON.stringify(data)) {
    memory.requests[kind] = { data, key: crypto.randomUUID() }; save();
  }
  return memory.requests[kind].key;
}
/** 房间、加入、排队统一通过HTTP创建，SSE不承载命令。 */
async function create(kind, data) {
  if (busy || !uid || !eligible) return;
  const stamp = generation; busy = true; controls(); $('pk-message').textContent = '正在确认…';
  try {
    const value = await createResource(kind, data, intent(kind, data));
    if (stamp !== generation) return;
    delete memory.requests[kind]; save();
    if (kind === 'matchmaking-tickets') {
      // 幂等POST重放的是创建时快照；再GET当前票，避免已配对后被旧waiting响应覆盖。
      const currentTicket = await api(value.data.links.self);
      if (stamp !== generation) return;
      ticket = currentTicket;
      if (currentTicket.data.room_id) { const current = await api(currentTicket.data.links.room); if (stamp !== generation) return; renderRoom(current); }
      else { room = null; $('pk-room').hidden = true; $('pk-waiting').hidden = false; $('pk-ticket-status').textContent = '正在寻找同行者…'; }
    } else { const current = await api(value.data.links.self); if (stamp !== generation) return; renderRoom(current); }
    if (stamp !== generation) return;
    $('pk-message').textContent = '状态已确认。';
  } catch (error) {
    if (stamp !== generation) return;
    showError(error);
    if (kind === 'room-memberships') $('pk-code-error').textContent = error.message;
    if (error.code === 'pk_occupied') await refreshState();
  } finally { if (stamp === generation) { busy = false; controls(); } }
}
/** 条件更新准备，不把前端倒计时作为开始比赛的授权。 */
async function ready() {
  if (busy || !room || room.data.status !== 'waiting') return;
  const stamp = generation, current = room;
  const desired = !current.data.members.find(member => member.is_me)?.ready;
  busy = true; controls();
  try {
    let value;
    try {
      value = await api(current.data.links.readiness, { method: 'PUT', body: { ready: desired }, headers: { 'If-Match': current.etag } });
    } catch (error) {
      if (error.status !== 412 || stamp !== generation) throw error;
      // 两人几乎同时准备时，读取最新ETag，仅对仍在等待的同一房间重试原意图一次。
      const latest = await api(current.data.links.self);
      if (stamp !== generation) return;
      value = latest.data.status === 'waiting' && latest.data.members.find(member => member.is_me)?.ready !== desired
        ? await api(latest.data.links.readiness, { method: 'PUT', body: { ready: desired }, headers: { 'If-Match': latest.etag } }) : latest;
    }
    if (stamp === generation) renderRoom(value);
  } catch (error) { if (stamp === generation) { showError(error); await refreshState(); } }
  finally { if (stamp === generation) { busy = false; controls(); } }
}
/** 有效提交不可改写；网络失败保持原解答，明确422才允许继续修改。 */
async function submit() {
  if (busy || !room || room.data.status !== 'playing') return;
  const stamp = generation, id = room.data.room_id, current = room;
  const entry = memory.drafts[id] ||= { draft: board.snapshot() };
  entry.pending ||= board.payload(); save(); busy = true; controls();
  try {
    await api(current.data.links.submission, { method: 'PUT', body: entry.pending });
    if (stamp !== generation) return;
    entry.pending = null; save(); $('pk-message').textContent = '解答已确认，正在等待竞速结果。'; await refreshState();
  } catch (error) { if (stamp === generation) { if (error.status === 422) { entry.pending = null; save(); } showError(error); } }
  finally { if (stamp === generation) { busy = false; controls(); } }
}
/** 取消和退出均发DELETE；已配对冲突会恢复房间，引导使用房间退出。 */
async function remove(kind) {
  if (busy || !uid) return;
  const path = kind === 'ticket' ? ticket?.data.links.self : room?.data.links.membership;
  if (!path) return;
  const stamp = generation; busy = true; controls();
  try {
    await api(path, { method: 'DELETE' });
    if (stamp !== generation) return;
    if (kind === 'room') { memory.lastRoom = null; room = null; boardRoom = null; board.clear(); $('pk-room').hidden = true; }
    else ticket = null;
    save(); $('pk-message').textContent = kind === 'room' ? '已离开房间。' : '已取消匹配。'; await refreshState();
  } catch (error) { if (stamp === generation) { showError(error); await refreshState(); } }
  finally { if (stamp === generation) { busy = false; controls(); } }
}
/** 仅在本地平滑显示权威starts_at/ends_at，零点时仍等待服务端发题。 */
function updateClock() {
  const now = Date.now() + offset;
  if (ticket?.data.status === 'waiting') {
    const left = Math.max(0, Date.parse(ticket.data.expires_at)-Date.now());
    $('pk-ticket-status').textContent = `正在寻找同行者… 剩余 ${Math.ceil(left/1000)} 秒${left ? '' : '，正在确认超时结果'}`;
  }
  if (!room) return;
  const data = room.data;
  $('pk-countdown').textContent = data.status === 'countdown' ? `距开始 ${Math.max(0, Math.ceil((Date.parse(data.starts_at)-now)/1000))} 秒` : data.status === 'playing' ? `剩余 ${formatTime(Math.max(0, Date.parse(data.ends_at)-now)/1000)}` : '';
}
/** 换号销毁订阅/旧请求/草稿内存，之后才恢复新账号正式资源。 */
async function identityChanged() {
  const next = auth.currentUser?.id ?? null;
  if (uid === next) return;
  uid = next; generation++; refreshVersion++; subscription?.close(); subscription = null;
  if (refreshTimer) clearTimeout(refreshTimer); refreshTimer = null;
  room = null; ticket = null; boardRoom = null; eligible = false; busy = false; board.clear();
  memory = { requests: {}, drafts: {}, lastRoom: null }; document.documentElement.dataset.theme = 'default';
  if (uid) {
    try { const saved = JSON.parse(storage?.getItem(`jobless-pk-v1:${uid}`) || 'null'); if (saved?.requests && saved?.drafts) memory = saved; }
    catch { $('pk-message').textContent = '本地草稿读取失败，正在恢复服务器资源。'; }
  }
  for (const id of ['pk-room', 'pk-waiting', 'pk-locked']) $(id).hidden = true;
  $('pk-login').hidden = Boolean(uid); $('pk-connection').textContent = ''; controls();
  const stamp = generation;
  try {
    features = (await api('features')).data;
    if (stamp !== generation) return;
    if (!features.pk_rooms || !features.progression) { $('pk-message').textContent = '双人竞速暂未开放，可先前往灯塔之旅。'; return; }
    if (!uid) { $('pk-message').textContent = '登录后确认三项正式通关资格。'; return; }
    const value = await api('me/pk-eligibility');
    if (stamp !== generation) return;
    requirements(value.data); controls(); $('pk-message').textContent = eligible ? '竞速资格已解锁。邀请朋友或开始匹配。' : '完成三项初级正式挑战后即可参与。';
    if (features.cosmetics) {
      try { const current = await api('me/appearance'); if (stamp === generation) document.documentElement.dataset.theme = current.data.theme_id; }
      catch { /* 主题加载失败不阻止可用的正式对局。 */ }
    }
    if (stamp !== generation) return;
    subscription = subscribeEvents({ onResource: scheduleRefresh, onReconnect: scheduleRefresh,
      onState: text => { if (stamp === generation) $('pk-connection').textContent = text; } });
    await refreshState();
  } catch (error) { if (stamp === generation) showError(error); }
}
$('pk-login').addEventListener('click', () => void auth.requireLogin(identityChanged));
$('pk-refresh').addEventListener('click', () => void (uid ? (async () => {
  const stamp = generation;
  try { const value = await api('me/pk-eligibility'); if (stamp !== generation) return; requirements(value.data); controls(); await refreshState(); } catch (error) { if (stamp === generation) showError(error); }
})() : identityChanged()));
$('pk-create').addEventListener('click', () => void create('rooms', { game_id: 'akari', difficulty: 'normal' }));
$('pk-match').addEventListener('click', () => void create('matchmaking-tickets', { game_id: 'akari', difficulty: 'normal' }));
$('pk-join-form').addEventListener('submit', event => { event.preventDefault(); $('pk-code-error').textContent = ''; void create('room-memberships', { room_code: $('pk-code').value.trim().toUpperCase() }); });
$('pk-ready').addEventListener('click', () => void ready()); $('pk-submit').addEventListener('click', () => void submit());
$('pk-leave').addEventListener('click', () => void remove('room')); $('pk-cancel').addEventListener('click', () => void remove('ticket'));
document.addEventListener(Events.AUTH_CHANGED, () => void identityChanged());
const timer = setInterval(updateClock, 250);
window.addEventListener('pagehide', () => { generation++; subscription?.close(); clearInterval(timer); if (refreshTimer) clearTimeout(refreshTimer); board.destroy(); });
window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
void auth.ready.then(identityChanged);
