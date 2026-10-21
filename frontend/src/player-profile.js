/** 首页左上角账号档案：真实星数、头像内等级与绿色累计经验条；不在本地推算权益。 */
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
    /** 页面销毁使所有尚未返回的读取失效。 */
    destroy() { epoch++; userId = null; busy = false; },
  };
}

/** 移动原按钮而非复制按钮，保留游戏设置、头像更新及焦点恢复的原有绑定。 */
export function initPlayerProfile({ host, userButton, openButton, avatarImage, usernameLabel }) {
  const portrait = document.createElement('span'); portrait.className = 'player-portrait';
  const level = document.createElement('span'); level.className = 'player-level'; level.textContent = 'Lv.—';
  level.id = 'header-player-level'; userButton.setAttribute('aria-describedby', level.id);
  portrait.append(avatarImage, level); avatarImage.width = avatarImage.height = 72;
  userButton.replaceChildren(portrait, usernameLabel);
  const stars = document.createElement('div'); stars.className = 'player-stars'; stars.hidden = true;
  stars.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 2 3 6.2 6.8 1-4.9 4.8 1.2 6.8L12 17.6l-6.1 3.2 1.2-6.8-4.9-4.8 6.8-1Z"/></svg><strong>—</strong><span>星</span>';
  const experience = document.createElement('div'); experience.className = 'player-experience'; experience.hidden = true;
  const bar = document.createElement('progress'); bar.className = 'player-xp'; bar.max = 1; bar.value = 0;
  bar.setAttribute('aria-label', '累计经验');
  const label = document.createElement('span'); label.className = 'player-xp-label';
  experience.append(bar, label); host.replaceChildren(openButton, userButton, stars, experience);
  const model = createProfileProgress({
    onUnauthorized: () => document.dispatchEvent(new CustomEvent(Events.AUTH_EXPIRED)),
    onChange: state => {
      const signedIn = state.userId !== null;
      stars.hidden = experience.hidden = !signedIn;
      const value = state.progression;
      level.textContent = value ? `Lv.${value.level}` : 'Lv.—';
      stars.querySelector('strong').textContent = value ? String(value.total_stars) : '—';
      stars.setAttribute('aria-label', value ? `累计获得${value.total_stars}颗星` : '星数暂未读取');
      bar.max = value ? value.next_level_xp ?? Math.max(1, value.xp) : 1;
      bar.value = value ? value.next_level_xp === null ? bar.max : value.xp : 0;
      label.textContent = value ? value.next_level_xp === null ? `${value.xp} 经验 · 已满级` : `经验 ${value.xp} / ${value.next_level_xp}`
        : state.status === 'loading' ? '经验读取中…' : state.status === 'unavailable' ? '成长暂未开放' : '经验暂不可用';
      bar.setAttribute('aria-valuetext', label.textContent);
      experience.title = value ? '累计经验 / 下一级所需累计经验' : label.textContent;
    },
  });
  /** 页面重新可见才刷新一次，不给游戏计时增加逐秒请求。 */
  function visible() { if (!document.hidden) void model.refresh(); }
  document.addEventListener('visibilitychange', visible);
  document.addEventListener(Events.RECORDS_UPDATED, visible);
  window.addEventListener('pageshow', visible);
  window.addEventListener('pagehide', event => {
    if (event.persisted) return;
    model.destroy(); document.removeEventListener('visibilitychange', visible); document.removeEventListener(Events.RECORDS_UPDATED, visible);
    window.removeEventListener('pageshow', visible);
  }, { once: true });
  return model;
}
