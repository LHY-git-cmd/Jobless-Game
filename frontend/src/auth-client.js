/** 同源登录 API 客户端；凭据仅由 HttpOnly Cookie 管理，前端不存储密码或 token。 */
export class AuthError extends Error {
  constructor(message, status = 0, field = "") {
    super(message);
    this.status = status;
    this.field = field;
  }
}

/** 请求超时或网络失败时保留失败语义，让表单允许重试。 */
export async function authRequest(path, { method = "GET", body } = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(`/api/auth/${path}`, {
      method, credentials: "same-origin", cache: "no-store", signal: controller.signal,
      headers: body ? { "Content-Type": "application/json" } : {},
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const data = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      const detail = data?.detail;
      const fallback = path === "avatar" ? "头像保存失败，请稍后重试。" : response.status === 429 ? "登录服务繁忙，请稍后重试。" : "登录服务暂时不可用，请稍后重试。";
      throw new AuthError(typeof detail === "string" ? detail : detail?.message || fallback, response.status, detail?.field || "");
    }
    const user = path === "login" ? data?.user : data;
    if ((path === "login" || path === "me" || path === "avatar") && (!user || typeof user.username !== "string" || !Number.isInteger(user.id))) {
      throw new AuthError("登录服务返回异常，请稍后重试。");
    }
    return data;
  } catch (error) {
    if (error instanceof AuthError) throw error;
    throw new AuthError("连接失败，请检查网络后重试。");
  } finally {
    clearTimeout(timeout);
  }
}

