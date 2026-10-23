/** 预设头像公共能力：固定站内图片路径、清单读取和按账号隔离的保存状态，不保存图片数据。 */
import { authRequest } from "./client.js";

const BASE = "/assets/avatars/v1/";

/** 只允许无符号字节编号进入固定资源目录，其他输入回退默认头像。 */
export function avatarUrl(id) {
  const number = Number.isInteger(id) && id > 0 && id <= 255 ? id : 1;
  return `${BASE}${String(number).padStart(3, "0")}.webp`;
}

/** 按站内清单提供选择项；失败不缓存，调用方可以明确重试。 */
export async function loadAvatarCatalog(fetcher = globalThis.fetch) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetcher(`${BASE}catalog.json`, { credentials: "same-origin", signal: controller.signal });
    if (!response.ok) throw new Error();
    const catalog = await response.json();
    if (catalog.default_id !== 1 || !Array.isArray(catalog.avatars) || !catalog.avatars.length || catalog.avatars.length > 255 ||
        !catalog.avatars.some(entry => entry.id === 1) || new Set(catalog.avatars.map(entry => entry.id)).size !== catalog.avatars.length ||
        catalog.avatars.some(entry => !Number.isInteger(entry.id) || entry.id < 1 || entry.id > 255 || entry.src !== avatarUrl(entry.id))) throw new Error();
    return catalog.avatars;
  } catch {
    throw new Error("头像列表加载失败，请重试。");
  } finally {
    clearTimeout(timer);
  }
}

/** 图片错误最多回退一次，默认图也不可用时保留有尺寸的占位，避免无限请求。 */
export function updateAvatarImage(image, id) {
  image.classList.remove("avatar-unavailable");
  image.onerror = () => {
    if (image.getAttribute("src") !== avatarUrl(1)) image.src = avatarUrl(1);
    else { image.onerror = null; image.classList.add("avatar-unavailable"); }
  };
  image.src = avatarUrl(id);
}

/** 相邻用户名已说明身份，图片作为装饰；显式尺寸避免加载时挤动布局。 */
export function createAvatarImage(id, { dom = document, size = 32, className = "" } = {}) {
  const image = dom.createElement("img");
  image.className = `avatar-image ${className}`.trim();
  image.alt = "";
  image.width = image.height = size;
  image.decoding = "async";
  updateAvatarImage(image, id);
  return image;
}

/** 独立管理保存流程，使网络响应无法跨账号更新，并让界面在失败后保留选择供重试。 */
export function createAvatarSelection({ request = authRequest, onSaved = () => {}, onChange = () => {}, onUnauthorized = () => {} } = {}) {
  let user = null, selected = 1, busy = false, message = "", epoch = 0;
  /** 发布状态快照，调用方不能直接修改保存中的账号。 */
  function publish() { onChange({ user: user ? { ...user } : null, selected, busy, message }); }
  return {
    /** 暴露只含公开字段的状态副本。 */
    get state() { return { user: user ? { ...user } : null, selected, busy, message }; },
    /** 换号、退出或重新打开时使旧请求失效，不依赖是否成功取消网络请求。 */
    setUser(value) { epoch++; user = value ? { ...value } : null; selected = user?.avatar_id ?? 1; busy = false; message = ""; publish(); },
    /** 保存期间固定待提交编号，防止成功响应与预览不一致。 */
    select(id) { if (!busy && user && Number.isInteger(id) && id > 0 && id <= 255) { selected = id; message = ""; publish(); } },
    /** 仅在服务器确认成功后替换当前头像，失败和晚到响应都不进行乐观写入。 */
    async save() {
      if (busy || !user || selected === user.avatar_id) return;
      const current = epoch, id = user.id, choice = selected;
      busy = true; message = "正在保存头像…"; publish();
      try {
        const result = await request("avatar", { method: "PUT", body: { avatar_id: choice } });
        if (current !== epoch) return;
        if (result?.id !== id || result.avatar_id !== choice || typeof result.username !== "string") throw new Error("头像服务返回异常，请重试。");
        user = { id: result.id, player_id: result.player_id ?? user.player_id, username: result.username, avatar_id: result.avatar_id };
        busy = false; message = "头像已保存。"; publish(); onSaved({ ...user });
      } catch (error) {
        if (current !== epoch) return;
        busy = false; message = error.status === 401 ? "登录已失效，请重新登录。" : error.message; publish();
        if (error.status === 401) onUnauthorized();
      } finally {
        if (current === epoch && busy) { busy = false; publish(); }
      }
    },
  };
}
