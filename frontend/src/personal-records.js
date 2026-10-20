/** 首页个人通关记录：仅随登录、分类切换、保存和手动刷新请求，不进行轮询。 */
import { rankingRequest } from "./ranking-client.js";
import { formatTime } from "./session.js";

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
  const $ = id => dom.getElementById(id);
  if (!$("personal-records")) return null;
  let user = null;
  let category = "mine";
  let generation = 0;

  /** 隐藏并删除旧值，退出、换号、切换分类和请求失败时不残留私人成绩。 */
  function clearRecords() {
    $("records-best").classList.add("hidden");
    $("records-recent").classList.add("hidden");
    $("records-best-time").textContent = "";
    $("records-best-date").textContent = "";
    $("records-list").replaceChildren();
  }

  /** 统一登录态控件；未登录不查询私人接口。 */
  function showLoggedOut(message = "登录后查看你的最佳成绩和最近三次通关。") {
    clearRecords();
    $("records-status").textContent = message;
    $("records-login").classList.remove("hidden");
    $("records-refresh").classList.add("hidden");
    $("records-retry").classList.add("hidden");
    $("records-panel").setAttribute("aria-busy", "false");
  }

  /** 所有动态成绩使用 textContent，最近记录中的最佳仅加标签，不虚构额外记录。 */
  function render(data) {
    if (data.category !== category || !Array.isArray(data.recent) || data.recent.length > 3 ||
        ![data.best, ...data.recent].every(record => record === null ||
          (Number.isInteger(record.id) && Number.isInteger(record.duration_seconds) && record.duration_seconds >= 0))) {
      throw new Error("通关记录返回异常，请重试。");
    }
    if (!data.best && data.recent.length === 0) {
      $("records-status").textContent = `还没有${LABELS[category]}通关记录，完成挑战后会显示在这里。`;
      return;
    }
    $("records-status").textContent = "";
    if (data.best) {
      $("records-best-label").textContent = `${LABELS[category]}最佳`;
      $("records-best-time").textContent = formatTime(data.best.duration_seconds);
      $("records-best-date").textContent = recordDate(data.best.completed_at);
      $("records-best").classList.remove("hidden");
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
    $("records-list").replaceChildren(...rows);
    $("records-recent").classList.remove("hidden");
  }

  /** 每次加载独立编号，旧账号或旧分类响应即使晚到也不能渲染。 */
  async function refresh() {
    if (!user) return;
    const current = ++generation;
    clearRecords();
    $("records-status").textContent = "正在读取通关记录…";
    $("records-login").classList.add("hidden");
    $("records-retry").classList.add("hidden");
    $("records-refresh").classList.remove("hidden");
    $("records-refresh").disabled = true;
    $("records-panel").setAttribute("aria-busy", "true");
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
        $("records-status").textContent = error.message;
        $("records-retry").classList.remove("hidden");
      }
    } finally {
      if (current === generation) {
        $("records-refresh").disabled = false;
        $("records-panel").setAttribute("aria-busy", "false");
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
      $(`records-${name}`).setAttribute("aria-selected", String(selected));
      $(`records-${name}`).tabIndex = selected ? 0 : -1;
    }
    $("records-panel").setAttribute("aria-labelledby", `records-${category}`);
    return refresh();
  }

  for (const [index, name] of CATEGORIES.entries()) {
    $(`records-${name}`).addEventListener("click", () => select(name));
    $(`records-${name}`).addEventListener("keydown", event => {
      const next = { ArrowRight: (index + 1) % CATEGORIES.length,
        ArrowLeft: (index + CATEGORIES.length - 1) % CATEGORIES.length, Home: 0, End: CATEGORIES.length - 1 }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      $(`records-${CATEGORIES[next]}`).focus();
      return select(CATEGORIES[next]);
    });
  }
  $("records-refresh").addEventListener("click", refresh);
  $("records-retry").addEventListener("click", refresh);
  $("records-login").addEventListener("click", async () => {
    try { await onLogin?.(setUser); }
    catch (error) { $("records-status").textContent = error.message; }
  });
  dom.addEventListener("auth-changed", event => setUser(event.detail?.user || null));
  dom.addEventListener("records-updated", refresh);
  showLoggedOut();
  return { setUser, refresh };
}
