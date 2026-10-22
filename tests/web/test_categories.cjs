const assert = require("node:assert/strict");
const { test } = require("node:test");
const { page } = require("../helpers/library_page.cjs");

const papers = () => [
  { id: "p1", title_zh: "甲", tags: ["ML/Transformer"], added: "2026-01-01", status: "unread" },
  { id: "p2", title_zh: "乙", tags: ["ML"], added: "2026-01-02", status: "unread" },
  { id: "p3", title_zh: "丙", tags: ["MLOps"], added: "2026-01-03", status: "unread" },
];
const boot = async () => { const p = page().library(papers(), ["ML/Transformer", "MLOps"]); await p.boot(); return p; };
const tags = (p, id) => Array.from(p.PR.lib.byId(id).tags);

test("a parent category lists papers in its sub-categories too", async () => {
  const p = await boot(), L = p.PR.lib;
  assert.deepEqual(Array.from(L.cats()), ["ML", "ML/Transformer", "MLOps"]);
  L.tag = "ML";
  assert.deepEqual(L.filtered().map((i) => i.id).sort(), ["p1", "p2"]);
  L.tag = "ML/Transformer";
  assert.deepEqual(L.filtered().map((i) => i.id), ["p1"]);
});

test("renaming a parent carries its sub-categories and papers along", async () => {
  const p = await boot(), L = p.PR.lib;
  L.side.pinned = ["c:ML/Transformer"];
  L.tag = "ML/Transformer";
  L.renameCat("ML", "Deep");
  assert.deepEqual(tags(p, "p1"), ["Deep/Transformer"]);
  assert.deepEqual(tags(p, "p2"), ["Deep"]);
  assert.deepEqual(tags(p, "p3"), ["MLOps"]);
  assert.deepEqual(Array.from(L.side.pinned), ["c:Deep/Transformer"]);
  assert.equal(L.tag, "Deep/Transformer");
});

test("moving a category under another keeps its leaf name; cannot move into itself", async () => {
  const p = await boot(), L = p.PR.lib;
  p.PR.toast = (msg) => { p.toasted = msg; };
  L.moveCatTo("MLOps", "ML");
  assert.deepEqual(tags(p, "p3"), ["ML/MLOps"]);
  L.renameCat("ML", "ML/Transformer/Inner");
  assert.match(p.toasted, /子分类/);
  assert.deepEqual(tags(p, "p2"), ["ML"]);
});

test("adding a sub-category builds the path under the parent", async () => {
  const p = await boot(), L = p.PR.lib;
  L.addCat(" BERT ", "p2", "ML/Transformer");
  assert.ok(L.cats().includes("ML/Transformer/BERT"));
  assert.deepEqual(tags(p, "p2"), ["ML", "ML/Transformer/BERT"]);
});
