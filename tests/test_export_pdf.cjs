// 阅读页“导出带划线的 PDF”入口（web/js/reader/export.js）：服务模式才显示；没有划线先提示；略过的条数和引文要提示出来。
//   node tests/test_export_pdf.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const SRC = fs.readFileSync(path.join(__dirname, "../easyread/web/js/reader/export.js"), "utf8");

function load({ mode = "server", demo = null, notes = [], pending = 0, response = null } = {}) {
  const dialogInner = { innerHTML: "" };
  let clickHandler = null;
  const dlg = {
    querySelector: (sel) => (sel === ".dialog" ? dialogInner : null),
    classList: { add() {}, remove() {} },
    addEventListener: (type, fn) => { if (type === "click") clickHandler = fn; },
  };
  const toasts = [], downloads = [], fetches = [];
  const fmt = (s, v) => String(s).replace(/\{(\w+)\}/g, (m, k) => (v && k in v ? v[k] : m));
  const PR = {
    state: null,
    t: fmt,
    esc: (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    $: (sel) => (sel === "#readerDlg" ? dlg : null),
    $$: () => [],
    ls: { get: (k, d) => d, set() {} },
    store: { mode, pending },
    flush: async () => {},
    myNotes: () => notes,
    toast: (html, action, ms) => toasts.push({ html, ms }),
    el: (tag, attrs) => ({ ...attrs, click() { downloads.push(attrs.download); }, remove() {} }),
    pid: "abc123",
    token: "tok",
  };
  PR.state = { paper: { meta: {} }, reader: { notes: {} }, discussion: { entries: [] }, demo };
  const fetch = async (url, opts) => {
    fetches.push({ url, opts });
    return response;
  };
  const ctx = {
    window: { PR }, fetch, document: { body: { appendChild() {} } },
    URL: { createObjectURL: () => "blob:x", revokeObjectURL() {} }, setTimeout: () => 0, Blob: class {}, decodeURIComponent, JSON,
  };
  vm.runInNewContext(SRC, ctx);
  return { PR, dialogInner, toasts, downloads, fetches, click: (target) => clickHandler({ target }) };
}

function resp({ status = 200, headers = {}, json = {} } = {}) {
  const h = Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]));
  return { ok: status < 400, status, headers: { get: (k) => h[k.toLowerCase()] ?? null }, blob: async () => ({}), json: async () => json };
}

test("button appears only in server mode (not offline single-file, not the online demo)", () => {
  const server = load();
  server.PR.openExport();
  assert.match(server.dialogInner.innerHTML, /data-exp-pdf/);
  const offline = load({ mode: "static" });
  offline.PR.openExport();
  assert.doesNotMatch(offline.dialogInner.innerHTML, /data-exp-pdf/);
  const demo = load({ demo: { id: "x" } });
  demo.PR.openExport();
  assert.doesNotMatch(demo.dialogInner.innerHTML, /data-exp-pdf/);
});

test("no highlights: clear message, no request", async () => {
  const x = load({ notes: [{ id: "n", kind: "note", body: "x" }] });
  await x.PR.exportAnnotatedPdf();
  assert.equal(x.fetches.length, 0);
  assert.equal(x.toasts.length, 1);
  assert.match(x.toasts[0].html, /这篇还没有划线/);
});

test("download uses the RFC 5987 filename, sends the token, and reports skipped quotes", async () => {
  const detail = encodeURIComponent(JSON.stringify([{ page: 3, quote: "<b>引文</b>", reason: "r" }]));
  const x = load({
    notes: [{ id: "a", quote: "q" }],
    response: resp({ headers: { "Content-Disposition": "attachment; filename=\"annotated.pdf\"; filename*=UTF-8''" + encodeURIComponent("论文-划线版.pdf"),
      "X-EasyRead-Written": "4", "X-EasyRead-Skipped": "1", "X-EasyRead-Skipped-Detail": detail } }),
  });
  await x.PR.exportAnnotatedPdf();
  assert.equal(x.fetches.length, 1);
  assert.equal(x.fetches[0].url, "/api/p/abc123/annotated-pdf");
  assert.equal(x.fetches[0].opts.method, "POST");
  assert.equal(x.fetches[0].opts.headers["X-Token"], "tok");
  assert.deepEqual(x.downloads, ["论文-划线版.pdf"]);
  const html = x.toasts[0].html;
  assert.match(html, /已导出 4 条划线/);
  assert.match(html, /1 条因找不到对应位置未导出/);
  assert.match(html, /第 3 页「&lt;b&gt;引文&lt;\/b&gt;」/);  // 引文转义后再放进提示
  assert.ok(!html.includes("<b>"));
});

test("server error is shown, nothing downloaded", async () => {
  const x = load({ notes: [{ id: "a", quote: "q" }], response: resp({ status: 400, json: { error: "这篇还没有划线" } }) });
  await x.PR.exportAnnotatedPdf();
  assert.deepEqual(x.downloads, []);
  assert.match(x.toasts[0].html, /导出失败：这篇还没有划线/);
});

test("dialog button triggers the export", async () => {
  const x = load({ notes: [] });
  x.PR.openExport();
  await x.click({ closest: (sel) => (sel === "[data-exp-pdf]" ? {} : null) });
  assert.match(x.toasts[0].html, /这篇还没有划线/);
});
