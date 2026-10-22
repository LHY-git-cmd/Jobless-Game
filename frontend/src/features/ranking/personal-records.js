/** 首页个人通关记录：仅随登录、分类切换、保存和手动刷新请求，不进行轮询。 */
import { cacheIds } from "../../shared/dom.js";
import { Events } from "../../shared/events.js";
import { rankingRequest } from "./client.js";
import { formatTime } from "../../shared/time.js";

const CATEGORIES = ["mine", "akari", "sudoku"];
const LABELS = { mine: "扫雷", akari: "照明", sudoku: "数独" };

/** 服务器时间为 UTC，补齐无时区响应后按浏览器本地时间显示。 */
function recordDate(value) {
  const utc = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
  const date = new Date(utc);
  return Number.isNaN(date.getTime()) ? "时间未知" : new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(date);
}

/** 初始化固定在首页的记录面板，账号和请求可注入以验证异步隔离。 */
export function initPersonalRecords({ request = rankingRequest, onLogin, dom = document } = {}) {
  const ui = cacheIds({
    personalRecords: "personal-records",
    recordsBest: "records-best",
    recordsRecent: "records-recent",
    recordsBestTime: "records-best-time",
    recordsBestDate: "records-best-date",
    recordsList: "records-list",
    recordsStatus: "records-status",
    recordsLogin: "records-login",
    recordsRefresh: "records-refresh",
    recordsRetry: "records-retry",
    recordsPanel: "records-panel",
    recordsBestLabel: "records-best-label"
  }, dom);
  const categoryButtons = cacheIds({ mine: "records-mine", akari: "records-akari", sudoku: "records-sudoku" }, dom);
  if (!ui.personalRecords) return null;
  let user = null;
  let category = "mine";
  let generation = 0;

  /** 隐藏并删除旧值，退出、换号、切换分类和请求失败时不残留私人成绩。 */
  function clearRecords() {
    ui.recordsBest.classList.add("hidden");
    ui.recordsRecent.classList.add("hidden");
    ui.recordsBestTime.textContent = "";
    ui.recordsBestDate.textContent = "";
    ui.recordsList.replaceChildren();
  }

  /** 统一登录态控件；未登录不查询私人接口。 */
  function showLoggedOut(message = "登录后查看你的最佳成绩和最近三次通关。") {
    clearRecords();
    ui.recordsStatus.textContent = message;
    ui.recordsLogin.classList.remove("hidden");
    ui.recordsRefresh.classList.add("hidden");
    ui.recordsRetry.classList.add("hidden");
    ui.recordsPanel.setAttribute("aria-busy", "false");
  }

  /** 所有动态成绩使用 textContent，最近记录中的最佳仅加标签，不虚构额外记录。 */
  function render(data) {
    if (data.category !== category || !Array.isArray(data.recent) || data.recent.length > 3 ||
        ![data.best, ...data.recent].every(record => record === null ||
          (Number.isInteger(record.id) && Number.isInteger(record.duration_seconds) && record.duration_seconds >= 0))) {
      throw new Error("通关记录返回异常，请重试。");
    }
    if (!data.best && data.recent.length === 0) {
      ui.recordsStatus.textContent = `还没有${LABELS[category]}通关记录，完成挑战后会显示在这里。`;
      return;
    }
    ui.recordsStatus.textContent = "";
    if (data.best) {
      ui.recordsBestLabel.textContent = "最佳";
      ui.recordsBestTime.textContent = formatTime(data.best.duration_seconds);
      ui.recordsBestDate.textContent = recordDate(data.best.completed_at);
      ui.recordsBest.classList.remove("hidden");
    }
    const rows = data.recent.map((record, index) => {
      const row = dom.createElement("li");
      const position = dom.createElement("span");
      position.className = "records-position";
      position.textContent = String(index + 1).padStart(2, "0");
      const description = dom.createElement("div");
      const date = dom.createElement("span");
      date.className = "records-date";
      date.textContent = recordDate(record.completed_at);
      description.append(date);
      if (record.id === data.best?.id) {
        const badge = dom.createElement("span");
        badge.className = "records-badge";
        badge.textContent = "最佳";
        description.append(badge);
      }
      const time = dom.createElement("strong");
      time.textContent = formatTime(record.duration_seconds);
      row.append(position, description, time);
      return row;
    });
    ui.recordsList.replaceChildren(...rows);
    ui.recordsRecent.classList.remove("hidden");
  }

  /** 每次加载独立编号，旧账号或旧分类响应即使晚到也不能渲染。 */
  async function refresh() {
    if (!user) return;
    const current = ++generation;
    clearRecords();
    ui.recordsStatus.textContent = "正在读取通关记录…";
    ui.recordsLogin.classList.add("hidden");
    ui.recordsRetry.classList.add("hidden");
    ui.recordsRefresh.classList.remove("hidden");
    ui.recordsRefresh.disabled = true;
    ui.recordsPanel.setAttribute("aria-busy", "true");
    try {
      const data = await request(`records/me?category=${category}`);
      if (current === generation) render(data);
    } catch (error) {
      if (current !== generation) return;
      clearRecords();
      if (error.status === 401) {
        user = null;
        showLoggedOut("登录已过期，请重新登录查看通关记录。");
      } else {
        ui.recordsStatus.textContent = error.message;
        ui.recordsRetry.classList.remove("hidden");
      }
    } finally {
      if (current === generation) {
        ui.recordsRefresh.disabled = false;
        ui.recordsPanel.setAttribute("aria-busy", "false");
      }
    }
  }

  /** 账号切换同步清空内容，重复校验同一账号不重复请求。 */
  function setUser(value) {
    if (value?.id === user?.id) return;
    generation++;
    user = value ? { id: value.id } : null;
    clearRecords();
    if (!user) return showLoggedOut();
    return refresh();
  }

  /** 分类按钮使用标准 tab 语义及单一键盘焦点。 */
  function select(value) {
    category = value;
    for (const name of CATEGORIES) {
      const selected = name === category;
      categoryButtons[name].setAttribute("aria-selected", String(selected));
      categoryButtons[name].tabIndex = selected ? 0 : -1;
    }
    ui.recordsPanel.setAttribute("aria-labelledby", `records-${category}`);
    return refresh();
  }

  for (const [index, name] of CATEGORIES.entries()) {
    categoryButtons[name].addEventListener("click", () => select(name));
    categoryButtons[name].addEventListener("keydown", event => {
      const next = { ArrowRight: (index + 1) % CATEGORIES.length,
        ArrowLeft: (index + CATEGORIES.length - 1) % CATEGORIES.length, Home: 0, End: CATEGORIES.length - 1 }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      categoryButtons[CATEGORIES[next]].focus();
      return select(CATEGORIES[next]);
    });
  }
  ui.recordsRefresh.addEventListener("click", refresh);
  ui.recordsRetry.addEventListener("click", refresh);
  ui.recordsLogin.addEventListener("click", async () => {
    try { await onLogin?.(setUser); }
    catch (error) { ui.recordsStatus.textContent = error.message; }
  });
  dom.addEventListener(Events.AUTH_CHANGED, event => setUser(event.detail?.user || null));
  dom.addEventListener(Events.RECORDS_UPDATED, refresh);
  showLoggedOut();
  return { setUser, refresh };
}
