/** 四个排行榜页面共用的分页、空榜、失败重试和快照明细渲染。 */
import { initAuth } from "./auth.js";
import { rankingRequest } from "./ranking-client.js";
import { formatTime } from "./session.js";

const $ = (id) => document.getElementById(id);
const category = document.body.dataset.ranking;
let page = 1;
let pages = 1;
let generation = 0;
initAuth();

/** 使用 textContent 处理所有用户名和成绩，不把服务端字段拼进 HTML。 */
function cell(text, className = "") {
  const element = document.createElement("td");
  element.textContent = text;
  element.className = className;
  return element;
}

/** 总榜明细始终取最佳轮次的三个秒数，不读取单项历史最佳。 */
function renderRows(entries) {
  const fragment = document.createDocumentFragment();
  for (const entry of entries) {
    const row = document.createElement("tr");
    if (entry.rank <= 3) row.className = "ranking-podium";
    row.append(cell(String(entry.rank), "ranking-position"), cell(entry.username, "ranking-player"));
    const result = cell("", "ranking-time");
    const strong = document.createElement("strong");
    strong.textContent = formatTime(entry.duration_seconds);
    result.append(strong);
    if (category === "total" && Array.isArray(entry.times)) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "本轮三关用时";
      const breakdown = document.createElement("p");
      breakdown.textContent = entry.times.map((seconds, index) => `${["扫雷", "照明", "数独"][index]} ${formatTime(seconds)}`).join(" · ");
      details.append(summary, breakdown);
      result.append(details);
    }
    row.append(result);
    fragment.append(row);
  }
  $("ranking-rows").replaceChildren(fragment);
}

/** 每次加载有独立代数，过期响应不能覆盖最新分页或重试结果。 */
async function load() {
  const current = ++generation;
  $("ranking-status").textContent = "正在读取冒险记录…";
  $("ranking-table").setAttribute("aria-busy", "true");
  $("ranking-retry").classList.add("hidden");
  $("ranking-prev").disabled = $("ranking-next").disabled = true;
  try {
    const data = await rankingRequest(`rankings/${category}?page=${page}&page_size=20`);
    if (current !== generation) return;
    if (!Array.isArray(data.entries) || !Number.isInteger(data.total)) throw new Error("榜单返回异常，请重试。");
    pages = Math.max(1, Math.ceil(data.total / 20));
    if (page > pages) { page = pages; return void load(); }
    renderRows(data.entries);
    $("ranking-status").textContent = data.total ? `共 ${data.total} 位玩家 · 每位玩家展示最佳成绩` : "榜单还没有记录。完成挑战，留下你的第一次通关。";
    $("ranking-page").textContent = `${page} / ${pages}`;
    $("ranking-prev").disabled = page <= 1;
    $("ranking-next").disabled = page >= pages;
  } catch (error) {
    if (current !== generation) return;
    $("ranking-status").textContent = error.message;
    $("ranking-retry").classList.remove("hidden");
    // 失败时清理旧行，避免上一页被误认作当前页。
    renderRows([]);
  } finally {
    if (current === generation) $("ranking-table").setAttribute("aria-busy", "false");
  }
}

$("ranking-prev").addEventListener("click", () => { if (page > 1) { page--; void load(); } });
$("ranking-next").addEventListener("click", () => { if (page < pages) { page++; void load(); } });
$("ranking-retry").addEventListener("click", () => { void load(); });
void load();
