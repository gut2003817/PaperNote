// 界面语言 zh-TW：PR.t 用注入的繁体词典、缺的词条退回简体原文；zh（简体）不查词典；en 照旧。  node tests/test_i18n_zhtw.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const SRC = fs.readFileSync(path.join(__dirname, "..", "easyread", "web", "js", "common", "i18n.js"), "utf8");

function load(htmlLang, dict) {
  const body = { nodeType: 1 };
  const document = {
    documentElement: { lang: htmlLang, dataset: { langChoice: "auto", target: "zh-TW" } },
    title: "设置", body,
    getElementById: (id) => (id === "pr-i18n" && dict ? { textContent: JSON.stringify(dict) } : null),
    addEventListener() {},
    createTreeWalker: () => ({ nextNode: () => null }),
  };
  body.querySelectorAll = () => [];
  const window = {};
  vm.runInNewContext(SRC, { window, document, NodeFilter: { SHOW_TEXT: 4 }, console });
  return { PR: window.PR, document };
}

test("zh-TW：用繁体词典，缺的词条退回简体原文", () => {
  const { PR, document } = load("zh-TW", { "设置": "設定", "已导入 {n} 篇": "已匯入 {n} 篇" });
  assert.equal(PR.lang, "zh-TW");
  assert.equal(PR.target, "zh-TW");
  assert.equal(PR.t("设置"), "設定");
  assert.equal(PR.t("已导入 {n} 篇", { n: 3 }), "已匯入 3 篇");
  assert.equal(PR.t("词典里没有 {n}", { n: 1 }), "词典里没有 1");
  assert.equal(document.title, "設定");
});

test("zh（zh-CN）：简体原文，不查词典", () => {
  const { PR } = load("zh-CN", { "设置": "SHOULD NOT BE USED" });
  assert.equal(PR.lang, "zh");
  assert.equal(PR.t("设置"), "设置");
});

test("en：用英文词典", () => {
  const { PR } = load("en", { "设置": "Settings" });
  assert.equal(PR.lang, "en");
  assert.equal(PR.t("设置"), "Settings");
});
