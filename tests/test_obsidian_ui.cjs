// 阅读页“写进 Obsidian”：假 PR／假 api 验证逻辑。  node tests/test_obsidian_ui.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function setup({ vault = "/v", jobs = [], post, config, aiChecked } = {}) {
  const toasts = [], calls = [], saved = {};
  const dlg = { addEventListener() {}, querySelector() { return {}; }, classList: { add() {}, remove() {} }, checked: aiChecked };
  const PR = {
    t: (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => (v && k in v ? v[k] : "{" + k + "}")), esc: (s) => String(s),
    pid: "p1", token: "tok", state: {}, store: { mode: "server", pending: 0 }, obsidianPollMs: 1,
    $: () => dlg, $$: () => [], flush: async () => { calls.push("flush"); },
    toast: (html) => toasts.push(html),
    ls: { get: (k, d) => (k in saved ? saved[k] : d), set: (k, v) => { saved[k] = v; } },
    api: async (url, opts) => {
      calls.push((opts && opts.method || "GET") + " " + url);
      if (url === "/api/config") { if (config) return config(); return { config: { obsidian_vault: vault } }; }
      if (url === "/api/p/p1/obsidian-note") { return post ? post(opts) : { id: "j1", kind: "obsidian", pid: "p1", state: "queued" }; }
      if (url.startsWith("/api/jobs")) return { jobs: [jobs.shift() || { id: "j1", kind: "obsidian", state: "running" }] };
      throw new Error("unexpected " + url);
    },
  };
  PR.state = { paper: { meta: {} }, reader: {}, discussion: {} };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/reader/export.js"), "utf8"), { window: { PR }, setTimeout, clearTimeout, URL, Blob, document: {} });
  return { PR, toasts, calls, saved, dlg };
}
const posts = (calls) => calls.filter((c) => c.startsWith("POST"));

test("vault not set: no request, toast points to settings", async () => {
  const { PR, toasts, calls } = setup({ vault: "" });
  await PR.exportToObsidian();
  assert.equal(posts(calls).length, 0);
  assert.ok(toasts.some((t) => t.includes("设置") && t.includes("Obsidian")), toasts.join("|"));
});

test("done: flush first, POST with token, toast has path", async () => {
  const { PR, toasts, calls } = setup({ jobs: [{ id: "j1", kind: "obsidian", state: "running" }, { id: "j1", kind: "obsidian", state: "done", path: "/v/论文笔记/a.md", skipped: 0 }] });
  PR.store.pending = 1;
  await PR.exportToObsidian();
  assert.ok(calls.indexOf("flush") >= 0 && calls.indexOf("flush") < calls.findIndex((c) => c.startsWith("POST")));
  assert.equal(posts(calls).length, 1);
  assert.ok(toasts.some((t) => t.includes("已写入") && t.includes("/v/论文笔记/a.md")), toasts.join("|"));
  assert.ok(!toasts.some((t) => t.includes("略过")));
});

test("done with skipped>0: mentions skipped figures", async () => {
  const { PR, toasts } = setup({ jobs: [{ id: "j1", kind: "obsidian", state: "done", path: "/v/a.md", skipped: 2 }] });
  await PR.exportToObsidian();
  assert.ok(toasts.some((t) => t.includes("2") && t.includes("略过")), toasts.join("|"));
});

test("job error: shows the message", async () => {
  const { PR, toasts } = setup({ jobs: [{ id: "j1", kind: "obsidian", state: "error", message: "模型炸了" }] });
  await PR.exportToObsidian();
  assert.ok(toasts.some((t) => t.includes("模型炸了")), toasts.join("|"));
});

test("POST 400 error is shown, no polling", async () => {
  const { PR, toasts, calls } = setup({ config: () => { throw new Error("offline"); }, post: () => { throw new Error("尚未设置 Obsidian 文件夹"); } });
  await PR.exportToObsidian();
  assert.ok(toasts.some((t) => t.includes("尚未设置 Obsidian 文件夹")));
  assert.ok(!calls.some((c) => c.includes("/api/jobs")));
});

test("pressing again while running does not send a second request", async () => {
  const jobs = [{ id: "j1", kind: "obsidian", state: "running" }, { id: "j1", kind: "obsidian", state: "done", path: "/v/a.md" }];
  const { PR, toasts, calls } = setup({ jobs });
  const first = PR.exportToObsidian();
  await PR.exportToObsidian();
  await first;
  assert.equal(posts(calls).length, 1);
  assert.ok(toasts.some((t) => t.includes("进行中")), toasts.join("|"));
  jobs.push({ id: "j1", kind: "obsidian", state: "done", path: "/v/b.md" });
  await PR.exportToObsidian();  // 结束后可以再按
  assert.equal(posts(calls).length, 2);
});

test("AI illustrations unchecked: body has no ai_images", async () => {
  let body = null;
  const { PR } = setup({ post: (o) => { body = o.body; return { id: "j1" }; }, jobs: [{ id: "j1", kind: "obsidian", state: "done", path: "/v/a.md" }] });
  await PR.exportToObsidian();
  assert.equal(JSON.stringify(body), "{}");
});

test("AI illustrations checked: sends ai_images, remembers choice, reports counts", async () => {
  let body = null;
  const { PR, toasts, saved, dlg } = setup({ aiChecked: true, post: (o) => { body = o.body; return { id: "j1" }; },
    jobs: [{ id: "j1", kind: "obsidian", state: "running", message: "正在生成 AI 示意图（1/3）" },
      { id: "j1", kind: "obsidian", state: "done", path: "/v/a.md", ai_images: 2, ai_skipped: 1, ai_error: "超时" }] });
  const seen = [];
  Object.defineProperty(dlg, "textContent", { set(v) { seen.push(v); }, get() { return ""; } });
  await PR.exportToObsidian();
  assert.equal(JSON.stringify(body), "{\"ai_images\":true}");
  assert.equal(saved["easyread-obs-ai"], true);
  assert.ok(seen.includes("正在生成 AI 示意图（1/3）"), seen.join("|"));
  assert.ok(toasts.some((t) => t.includes("已生成 2 张 AI 示意图") && t.includes("有 1 张 AI 示意图没能生成：超时")), toasts.join("|"));
});
