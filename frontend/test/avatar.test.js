/** 头像状态与请求测试：保存失败可重试，退出/换号后晚到响应不能覆盖新账号。 */
import test from "node:test";
import assert from "node:assert/strict";
import { avatarUrl, loadAvatarCatalog, createAvatarSelection } from "../src/avatar.js";

test("图片路径只能来自预设编号，异常输入使用默认图", () => {
  assert.equal(avatarUrl(17), "/assets/avatars/v1/017.webp");
  for (const value of [undefined, "../../config", true, -1, 999]) assert.equal(avatarUrl(value), "/assets/avatars/v1/001.webp");
});

test("清单加载失败后可以重试，不能接受任意远程图片路径", async () => {
  await assert.rejects(loadAvatarCatalog(async () => ({ ok: false })), /头像/);
  await assert.rejects(loadAvatarCatalog(async () => ({ ok: true, json: async () => ({ default_id: 1, avatars: [{ id: 1, src: "https://evil.example/x" }] }) })), /头像/);
});

test("保存成功才更新账号，重复点击不产生重复请求", async () => {
  let finish, calls = 0, saved;
  const picker = createAvatarSelection({ request: () => { calls++; return new Promise(resolve => { finish = resolve; }); }, onSaved: user => { saved = user; } });
  picker.setUser({ id: 1, username: "甲", avatar_id: 1 });
  picker.select(17);
  const pending = picker.save();
  await picker.save();
  assert.equal(calls, 1);
  assert.equal(picker.state.user.avatar_id, 1);
  finish({ id: 1, username: "甲", avatar_id: 17 });
  await pending;
  assert.equal(saved.avatar_id, 17);
  assert.equal(picker.state.busy, false);
});

test("失败保留原头像和选择，可再次保存", async () => {
  let fail = true;
  const picker = createAvatarSelection({ request: async () => { if (fail) throw new Error("连接失败"); return { id: 1, username: "甲", avatar_id: 25 }; } });
  picker.setUser({ id: 1, username: "甲", avatar_id: 1 });
  picker.select(25);
  await picker.save();
  assert.equal(picker.state.user.avatar_id, 1);
  assert.equal(picker.state.selected, 25);
  assert.match(picker.state.message, /连接失败/);
  fail = false; await picker.save();
  assert.equal(picker.state.user.avatar_id, 25);
});

test("换号及退出时丢弃旧保存响应，错误账号响应也不接受", async () => {
  for (const nextUser of [null, { id: 2, username: "乙", avatar_id: 2 }]) {
    let finish, updates = 0;
    const picker = createAvatarSelection({ request: () => new Promise(resolve => { finish = resolve; }), onSaved: () => { updates++; } });
    picker.setUser({ id: 1, username: "甲", avatar_id: 1 }); picker.select(3);
    const pending = picker.save(); picker.setUser(nextUser);
    finish({ id: 1, username: "甲", avatar_id: 3 }); await pending;
    assert.equal(picker.state.user?.id, nextUser?.id);
    assert.equal(updates, 0);
  }
  const picker = createAvatarSelection({ request: async () => ({ id: 2, username: "乙", avatar_id: 3 }) });
  picker.setUser({ id: 1, username: "甲", avatar_id: 1 }); picker.select(3); await picker.save();
  assert.equal(picker.state.user.id, 1);
  assert.match(picker.state.message, /异常/);
});
