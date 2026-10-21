/** 首页账号档案：绿色经验环、底部等级牌及右侧真实星数，不在本地推算权益。 */
import { requestJson } from './lib/http.js';
import { Events } from './lib/events.js';

/** 只在登录或主动返回页面时读取，账号变化立即废弃旧响应，不轮询。 */
export function createProfileProgress({ request = () => requestJson('/api/v1/me/progression'), onChange = () => {}, onUnauthorized = () => {} } = {}) {
  let userId = null, epoch = 0, busy = false;
  /** 不可用时保留null，不把读取失败伪造成0星或默认等级。 */
  function publish(status, progression = null) { onChange({ userId, status, progression }); }
  /** 校验有限整数，避免损坏响应影响进度条尺寸或账号显示。 */
  function valid(value) {
    return value && ['xp', 'total_stars', 'level'].every(key => Number.isSafeInteger(value[key]) && value[key] >= (key === 'level' ? 1 : 0)) &&
      (value.next_level_xp === null || Number.isSafeInteger(value.next_level_xp) && value.next_level_xp > value.xp);
  }
  /** 请求期间保持一个读取任务；切号后的旧任务不能覆盖新账号。 */
  async function refresh() {
    if (userId === null || busy) return;
    const stamp = epoch; busy = true;
    try {
      const value = await request();
      if (stamp !== epoch) return;
      if (!valid(value)) throw new Error('成长数据无效');
      publish('ready', value);
    } catch (error) {
      if (stamp !== epoch) return;
      publish(error.status === 404 ? 'unavailable' : 'error');
      if (error.status === 401) onUnauthorized();
    } finally { if (stamp === epoch) busy = false; }
  }
  return {
    /** 更换头像或用户名不会重置同一账号已读成长。 */
    setUser(user) {
      const next = user?.id ?? null;
      if (next === userId) return;
      userId = next; epoch++; busy = false; publish(next === null ? 'guest' : 'loading');
      if (next !== null) void refresh();
    },
    refresh,
    /** 只接受当前账号的服务端结算快照，同时失效较早发出的成长读取。 */
    accept(uid,value) {
      if(uid!==userId||userId===null||!valid(value))return false;
      epoch++;busy=false;publish('ready',value);return true;
    },
    /** 页面销毁使所有尚未返回的读取失效。 */
    destroy() { epoch++; userId = null; busy = false; },
  };
}

/** 移动原头像按钮，经验环只展示服务器成长，头像点击保持独立更换入口。 */
export function initPlayerProfile({ host, userButton, openButton, avatarImage, usernameLabel }) {
  const portrait = document.createElement('span'); portrait.className = 'player-portrait';
  const level = document.createElement('span'); level.className = 'player-level'; level.textContent = 'Lv.—';
  level.id = 'header-player-level'; userButton.setAttribute('aria-describedby', level.id);
  const ring = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  ring.classList.add('player-xp-ring'); ring.setAttribute('viewBox', '0 0 70 70'); ring.setAttribute('aria-hidden', 'true');
  ring.innerHTML = '<circle class="player-ring-track" cx="35" cy="35" r="32"/><circle class="player-ring-fill" cx="35" cy="35" r="32" pathLength="100"/>';
  portrait.append(avatarImage, ring, level); avatarImage.width = avatarImage.height = 58;
  userButton.replaceChildren(portrait); usernameLabel.hidden = true;
  const stars = document.createElement('div'); stars.className = 'player-stars'; stars.hidden = true;
  stars.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 2 3 6.2 6.8 1-4.9 4.8 1.2 6.8L12 17.6l-6.1 3.2 1.2-6.8-4.9-4.8 6.8-1Z"/></svg><strong>—</strong><span>星</span>';
  const experience = document.createElement('div'); experience.className = 'player-experience sr-only'; experience.hidden = true;
  const bar = document.createElement('progress'); bar.className = 'player-xp'; bar.max = 1; bar.value = 0;
  bar.setAttribute('aria-label', '累计经验');
  const label = document.createElement('span'); label.className = 'player-xp-label';
  experience.append(bar, label); host.replaceChildren(openButton, userButton, usernameLabel, stars, experience);
  const model = createProfileProgress({
    onUnauthorized: () => document.dispatchEvent(new CustomEvent(Events.AUTH_EXPIRED)),
    onChange: state => {
      const signedIn = state.userId !== null;
      stars.hidden = experience.hidden = !signedIn;
      usernameLabel.hidden = !signedIn;
      const value = state.progression;
      level.textContent = value ? `Lv.${value.level}` : 'Lv.—';
      stars.querySelector('strong').textContent = value ? String(value.total_stars) : '—';
      stars.setAttribute('aria-label', value ? `累计获得${value.total_stars}颗星` : '星数暂未读取');
      bar.max = value ? value.next_level_xp ?? Math.max(1, value.xp) : 1;
      bar.value = value ? value.next_level_xp === null ? bar.max : value.xp : 0;
      ring.querySelector('.player-ring-fill').style.strokeDashoffset = String(100 - bar.value / bar.max * 100);
      label.textContent = value ? value.next_level_xp === null ? `${value.xp} 经验 · 已满级` : `经验 ${value.xp} / ${value.next_level_xp}`
        : state.status === 'loading' ? '经验读取中…' : state.status === 'unavailable' ? '成长暂未开放' : '经验暂不可用';
      bar.setAttribute('aria-valuetext', label.textContent);
      experience.title = value ? '累计经验 / 下一级所需累计经验' : label.textContent;
      portrait.title = label.textContent;
    },
  });
  /** 页面重新可见才刷新一次，不给游戏计时增加逐秒请求。 */
  function visible() { if (!document.hidden) void model.refresh(); }
  document.addEventListener('visibilitychange', visible);
  document.addEventListener(Events.RECORDS_UPDATED, visible);
  /** 汇聚结束后使用服务端总数，旧身份的迟到动画不能修改当前账号。 */
  function confirmed(event){model.accept(event.detail?.userId,event.detail?.progression);}
  document.addEventListener(Events.PROGRESSION_CONFIRMED,confirmed);
  window.addEventListener('pageshow', visible);
  window.addEventListener('pagehide', event => {
    if (event.persisted) return;
    model.destroy(); document.removeEventListener('visibilitychange', visible); document.removeEventListener(Events.RECORDS_UPDATED, visible);
    document.removeEventListener(Events.PROGRESSION_CONFIRMED,confirmed);
    window.removeEventListener('pageshow', visible);
  }, { once: true });
  return model;
}
