const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const WEB = path.join(__dirname, "..", "..", "easyread", "web", "js");
const tree = () => {
  const window = { PR: {} };
  vm.runInNewContext(fs.readFileSync(path.join(WEB, "library", "cat-tree.js"), "utf8"), { window });
  return window.PR.catTree;
};

test("paths: leaf, parent, depth, under", () => {
  const T = tree();
  assert.equal(T.leaf("ML/Transformer"), "Transformer");
  assert.equal(T.parent("ML/Transformer"), "ML");
  assert.equal(T.parent("ML"), "");
  assert.equal(T.depth("A/B/C"), 2);
  assert.ok(T.under("ML/Transformer", "ML"));
  assert.ok(T.under("ML", "ML"));
  assert.ok(!T.under("MLOps", "ML"), "同前缀的兄弟不算子分类");
  assert.equal(T.label("A/B"), "A › B");
});

test("clean trims each level and drops empty ones", () => {
  const T = tree();
  assert.equal(T.clean(" A / /B "), "A/B");
  assert.equal(T.clean("/A/"), "A");
  assert.equal(T.clean("x".repeat(40)), "x".repeat(30));
});

test("ordered fills in ancestors and keeps children right after their parent", () => {
  const T = tree();
  assert.deepEqual(Array.from(T.ordered(["B", "A/x", "B/y", "A"])), ["B", "B/y", "A", "A/x"]);
  assert.deepEqual(Array.from(T.ordered(["A/B/C"])), ["A", "A/B", "A/B/C"]);
});

test("move renames a whole subtree and leaves look-alike siblings alone", () => {
  const T = tree();
  assert.equal(T.move("A/B", "A", "Z"), "Z/B");
  assert.equal(T.move("AB", "A", "Z"), "AB");
  assert.equal(T.move("A/B/C", "A/B", "X/B"), "X/B/C");
});

test("shift swaps a category with its sibling, children travel along", () => {
  const T = tree();
  const list = ["A", "A/1", "B", "B/1", "C"];
  assert.deepEqual(Array.from(T.shift(list, "B", -1)), ["B", "B/1", "A", "A/1", "C"]);
  assert.deepEqual(Array.from(T.shift(list, "A", 1)), ["B", "B/1", "A", "A/1", "C"]);
  assert.deepEqual(Array.from(T.shift(["P", "P/a", "P/b", "Q"], "P/b", -1)), ["P", "P/b", "P/a", "Q"]);
  assert.deepEqual(Array.from(T.shift(list, "A", -1)), list, "已经在最前面");
});

const ids = (rows) => rows.map((r) => (r.type === "cat" ? "c:" + r.c : r.type === "paper" ? "p:" + r.item.id + "@" + r.cat : "+" + r.n + "@" + r.cat));

test("direct lists only papers tagged with the category itself", () => {
  const T = tree();
  const items = [{ id: 1, tags: ["A"] }, { id: 2, tags: ["A/B"] }, { id: 3 }];
  assert.deepEqual(T.direct(items, "A").map((i) => i.id), [1]);
});

test("rows: an open category lists sub-categories first, then its own papers", () => {
  const T = tree();
  const cats = T.ordered(["A", "A/B", "C"]);
  const items = [{ id: 1, tags: ["A"] }, { id: 2, tags: ["A/B", "C"] }, { id: 3 }];
  const rows = Array.from(T.rows(cats, items, { open: () => true }));
  assert.deepEqual(ids(rows), ["c:A", "c:A/B", "p:2@A/B", "p:1@A", "c:C", "p:2@C"], "多个分类的论文每处都出现，没分类的不进树");
  assert.equal(rows[2].depth, 2, "论文和同级子分类一样深");
  assert.equal(rows[3].depth, 1);
});

test("rows: collapsed by default, kids counts papers too, skip hides a subtree", () => {
  const T = tree();
  const cats = T.ordered(["A", "A/B", "E", "H", "H/x"]);
  const items = [{ id: 1, tags: ["A/B"] }];
  const rows = Array.from(T.rows(cats, items, { skip: (c) => c === "H" }));
  assert.deepEqual(ids(rows), ["c:A", "c:E"]);
  assert.equal(rows[0].kids, true);
  assert.equal(rows[0].open, false);
  assert.equal(rows[1].kids, false, "空分类没有箭头");
  const ab = Array.from(T.rows(cats, items, { open: (c) => c === "A" }));
  assert.deepEqual(ids(ab), ["c:A", "c:A/B", "c:E", "c:H"]);
  assert.equal(ab[1].kids, true, "只有论文也算有子项");
});

test("rows: long categories show the first `limit` papers and a 'more' row", () => {
  const T = tree();
  const items = Array.from({ length: 7 }, (_, k) => ({ id: k, tags: ["A"] }));
  const rows = Array.from(T.rows(["A"], items, { open: () => true, limit: 5 }));
  assert.equal(rows.length, 1 + 5 + 1);
  assert.deepEqual(ids(rows).slice(-1), ["+2@A"]);
  const all = Array.from(T.rows(["A"], items, { open: () => true, limit: 5, full: (c) => c === "A" }));
  assert.equal(all.length, 8);
  assert.equal(all[all.length - 1].type, "paper");
});
