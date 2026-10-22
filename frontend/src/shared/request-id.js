/** 生成 UUID v4；公网 HTTP 不提供 randomUUID 时仍使用安全随机数生成幂等编号。 */
export function createRequestId(cryptoApi = globalThis.crypto) {
  if (typeof cryptoApi?.randomUUID === "function") return cryptoApi.randomUUID();
  if (typeof cryptoApi?.getRandomValues !== "function") {
    throw new Error("当前浏览器无法生成请求编号，请更新浏览器后重试。");
  }
  const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
  // 按 UUID v4 规范设置版本和变体，其余位保留浏览器安全随机数。
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

