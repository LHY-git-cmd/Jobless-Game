/** 成长排行榜：星数、等级分页和头像渲染；竞技积分仅展示未开放说明。 */
import { cacheIds } from "../shared/dom.js";
import { Events } from "../shared/events.js";
import { initAuth } from "../features/account/auth.js";
import { rankingRequest } from "../features/ranking/client.js";
import { createAvatarImage, updateAvatarImage } from "../features/account/avatar.js";

const ui = cacheIds({
  rankingRows: 'ranking-rows',
  rankingStatus: 'ranking-status',
  rankingTable: 'ranking-table',
  rankingRetry: 'ranking-retry',
  rankingPrev: 'ranking-prev',
  rankingNext: 'ranking-next',
  rankingPage: 'ranking-page'
});

const boards = {
  stars: { title: '星数排行', column: '累计星数', rule: '按闯关累计星数从高到低排名，同星数并列。', empty: '榜单还没有记录。完成闯关，收集你的第一颗星星。' },
  level: { title: '等级排行', column: '等级 / 经验', rule: '按账号等级从高到低排名，同等级按累计经验排序，经验相同并列。', empty: '榜单还没有记录。完成闯关，获得经验并提升等级。' },
  points: { title: '积分排行', column: '竞技积分', rule: '积分将通过竞技模式获得。竞技积分暂未开放，开放后按积分排名。' },
};
const requested = new URLSearchParams(location.search).get('category');
const category = Object.hasOwn(boards, requested) ? requested : 'stars';
const board = boards[category];
document.title = `${board.title} · 无职游戏`;
document.getElementById('ranking-title').textContent = board.title;
document.getElementById('ranking-rule-text').textContent = board.rule;
document.getElementById('ranking-value-heading').textContent = board.column;
document.querySelector('#ranking-table caption').textContent = `${board.title}：名次、玩家与${board.column}`;
for (const link of document.querySelectorAll('.ranking-tabs a')) {
  if (new URL(link.href).searchParams.get('category') === category) link.setAttribute('aria-current', 'page');
  else link.removeAttribute('aria-current');
}
let page = 1;
let pages = 1;
let generation = 0;
const updatedAvatars = new Map();
initAuth();

/** 使用 textContent 处理所有用户名和成绩，不把服务端字段拼进 HTML。 */
function cell(text, className = "") {
  const element = document.createElement("td");
  element.textContent = text;
  element.className = className;
  return element;
}

/** 仅渲染服务端累计星数和等级，积分未开放时不生成占位玩家。 */
function renderRows(entries) {
  const fragment = document.createDocumentFragment();
  for (const entry of entries) {
    const row = document.createElement("tr");
    if (entry.rank <= 3) row.className = "ranking-podium";
    const player = cell("", "ranking-player");
    const identity = document.createElement("div");
    identity.className = "ranking-identity";
    const image = createAvatarImage(updatedAvatars.get(entry.user_id) ?? entry.avatar_id);
    image.dataset.userId = String(entry.user_id);
    const name = document.createElement("span");
    name.textContent = entry.username;
    identity.append(image, name); player.append(identity);
    row.append(cell(String(entry.rank), "ranking-position"), player);
    const result = cell("", "ranking-time");
    const strong = document.createElement("strong");
    strong.textContent = category === 'stars' ? `${entry.total_stars} 星` : `Lv.${entry.level}`;
    result.append(strong);
    if (category === 'level') result.append(document.createElement('br'), `${entry.xp} 经验`);
    row.append(result);
    fragment.append(row);
  }
  ui.rankingRows.replaceChildren(fragment);
}

/** 每次加载有独立代数，过期响应不能覆盖最新分页或重试结果。 */
async function load() {
  const current = ++generation;
  ui.rankingStatus.textContent = "正在读取排行榜…";
  ui.rankingTable.setAttribute("aria-busy", "true");
  ui.rankingRetry.classList.add("hidden");
  ui.rankingPrev.disabled = ui.rankingNext.disabled = true;
  try {
    const data = await rankingRequest(`rankings/growth/${category}?page=${page}&page_size=20`);
    if (current !== generation) return;
    if (!Array.isArray(data.entries) || !Number.isInteger(data.total)) throw new Error("榜单返回异常，请重试。");
    pages = Math.max(1, Math.ceil(data.total / 20));
    if (page > pages) { page = pages; return void load(); }
    renderRows(data.entries);
    ui.rankingStatus.textContent = data.total ? `共 ${data.total} 位玩家 · 展示有闯关成长记录的玩家` : board.empty;
    ui.rankingPage.textContent = `${page} / ${pages}`;
    ui.rankingPrev.disabled = page <= 1;
    ui.rankingNext.disabled = page >= pages;
  } catch (error) {
    if (current !== generation) return;
    ui.rankingStatus.textContent = error.message;
    ui.rankingRetry.classList.remove("hidden");
    // 失败时清理旧行，避免上一页被误认作当前页。
    renderRows([]);
  } finally {
    if (current === generation) ui.rankingTable.setAttribute("aria-busy", "false");
  }
}

ui.rankingPrev.addEventListener("click", () => { if (page > 1) { page--; void load(); } });
ui.rankingNext.addEventListener("click", () => { if (page < pages) { page++; void load(); } });
ui.rankingRetry.addEventListener("click", () => { void load(); });
// 同页更换头像只更新可见图片，不重新提交成绩或改变分页；映射也覆盖在途榜单旧响应。
document.addEventListener(Events.USER_PROFILE_UPDATED, event => {
  const user = event.detail.user;
  updatedAvatars.set(user.id, user.avatar_id);
  for (const image of document.querySelectorAll(".ranking-identity img")) {
    if (image.dataset.userId === String(user.id)) updateAvatarImage(image, user.avatar_id);
  }
});
if (category === 'points') {
  // 积分未实现时明确展示状态，不请求不存在的积分接口或伪造零分排名。
  document.querySelector('.ranking-table-wrap').classList.add('hidden');
  document.querySelector('.ranking-pagination').classList.add('hidden');
  ui.rankingTable.setAttribute('aria-busy', 'false');
  ui.rankingStatus.textContent = '积分排行暂未开放。竞技积分结算功能上线后，将在这里展示排名。';
} else void load();
