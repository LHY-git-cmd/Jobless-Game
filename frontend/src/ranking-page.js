/** 三个单关排行榜共用的分页、空榜、失败重试和头像渲染。 */
import { cacheIds } from "./lib/dom.js";
import { Events } from "./lib/events.js";
import { initAuth } from "./auth.js";
import { rankingRequest } from "./ranking-client.js";
import { formatTime } from "./session.js";
import { createAvatarImage, updateAvatarImage } from "./avatar.js";

const ui = cacheIds({
  rankingRows: 'ranking-rows',
  rankingStatus: 'ranking-status',
  rankingTable: 'ranking-table',
  rankingRetry: 'ranking-retry',
  rankingPrev: 'ranking-prev',
  rankingNext: 'ranking-next',
  rankingPage: 'ranking-page'
});

const category = document.body.dataset.ranking;
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

/** 渲染各玩家的单关历史最佳成绩。 */
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
    strong.textContent = formatTime(entry.duration_seconds);
    result.append(strong);
    row.append(result);
    fragment.append(row);
  }
  ui.rankingRows.replaceChildren(fragment);
}

/** 每次加载有独立代数，过期响应不能覆盖最新分页或重试结果。 */
async function load() {
  const current = ++generation;
  ui.rankingStatus.textContent = "正在读取冒险记录…";
  ui.rankingTable.setAttribute("aria-busy", "true");
  ui.rankingRetry.classList.add("hidden");
  ui.rankingPrev.disabled = ui.rankingNext.disabled = true;
  try {
    const data = await rankingRequest(`rankings/${category}?page=${page}&page_size=20`);
    if (current !== generation) return;
    if (!Array.isArray(data.entries) || !Number.isInteger(data.total)) throw new Error("榜单返回异常，请重试。");
    pages = Math.max(1, Math.ceil(data.total / 20));
    if (page > pages) { page = pages; return void load(); }
    renderRows(data.entries);
    ui.rankingStatus.textContent = data.total ? `共 ${data.total} 位玩家 · 每位玩家展示最佳成绩` : "榜单还没有记录。完成挑战，留下你的第一次通关。";
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
void load();
