const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const WEB = path.join(__dirname, "..", "..", "easyread", "web", "js");
const EN = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "easyread", "web", "i18n", "en.json"), "utf8"));
const util = (lang) => {
  const window = { PR: { lang, t: (s) => (lang === "en" ? EN[s] || s : s) }, addEventListener() {} };
  vm.runInNewContext(fs.readFileSync(path.join(WEB, "common", "util.js"), "utf8"), { window, document: { addEventListener() {} }, location: {}, navigator: {} });
  return window.PR;
};

test("译文语言里有英语（#48）：中文界面叫“英语”，英文界面叫 English", () => {
  assert.equal(util("zh").targetName("en"), "英语");
  assert.equal(util("en").targetName("en"), "English");
  assert.ok(util("zh").TARGETS.some(([k]) => k === "en"));
});

test("译成英文：英文界面主标题用英文译名，原标题不标 lang；原文本来是英文、标题照抄的不重复显示", () => {
  const PR = util("en");
  const de = PR.titles({ title_zh: "Attention Is All You Need", title_en: "Aufmerksamkeit ist alles", target: "en" });
  assert.equal(de.main, "Attention Is All You Need");
  assert.equal(de.sub, "Aufmerksamkeit ist alles");
  assert.equal(de.subLang, "");
  const same = PR.titles({ title_zh: "Deep Learning", title_en: "Deep Learning", target: "en" });
  assert.equal(same.sub, "");
  assert.equal(PR.titles({ title_zh: "Tiefes Lernen", title_en: "Deep Learning", target: "de" }).subLang, "de");
});
