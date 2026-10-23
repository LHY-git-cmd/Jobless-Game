/** 登录规则和 API 客户端测试：字符边界、原样密码、错误与网络失败均有明确语义。 */
import test from "node:test";
import assert from "node:assert/strict";
import { usernameUnits, validateUsername, validatePassword } from "../../../src/features/account/validation.js";
import { authRequest, AuthError } from "../../../src/features/account/client.js";

test("用户名 Unicode 权重与后端一致，英文长度和非法字符覆盖边界", () => {
  for (const value of ["中文123456789", "一二三四五六七八", "abc123ABC123", "𠀀1234567890"]) assert.equal(validateUsername(value), "", value);
  for (const value of ["", "中文1234567890", "九".repeat(9), " a", "a_b", "a😀", "a\n", "\ufaff", "\u{2a6e0}"]) assert.notEqual(validateUsername(value), "", value);
  assert.equal(usernameUnits("中文123456789"), 24);
  assert.equal(usernameUnits("𠀀"), 3);
});

test("密码按 Unicode 字符计数并保留空格", () => {
  assert.notEqual(validatePassword("12345"), "");
  assert.equal(validatePassword("      "), "");
  assert.equal(validatePassword("😀😀😀😀😀😀"), "");
});

test("API 使用同源 Cookie，不修改密码，不暴露 Cookie token", async (t) => {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  let sent;
  globalThis.fetch = async (url, options) => { sent = { url, options }; return { ok: true, status: 200, json: async () => ({ user: { id: 1, username: "Player1" } }) }; };
  await authRequest("login", { method: "POST", body: { username: "Player1", password: " Abc12 " } });
  assert.equal(sent.url, "/api/auth/login");
  assert.equal(sent.options.credentials, "same-origin");
  assert.equal(JSON.parse(sent.options.body).password, " Abc12 ");
});

test("认证失败、过载、非 JSON 代理错误与网络错误都允许重试", async (t) => {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => ({ ok: false, status: 401, json: async () => ({ detail: "用户名或密码错误。" }) });
  await assert.rejects(authRequest("login"), (error) => error instanceof AuthError && error.status === 401);
  globalThis.fetch = async () => ({ ok: false, status: 429, json: async () => { throw new Error("nginx html"); } });
  await assert.rejects(authRequest("login"), /繁忙/);
  globalThis.fetch = async () => { throw new TypeError("network"); };
  await assert.rejects(authRequest("login"), /连接失败/);
});
