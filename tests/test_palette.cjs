const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const src = fs.readFileSync(path.join(__dirname, "../easyread/web/js/common/palette.js"), "utf8");

/* 假的浏览器：documentElement 记录每次 setProperty / removeProperty，localStorage 用 Map */
function env(prefs, theme = "light") {
  const style = new Map(), calls = { set: 0, remove: 0 }, store = new Map();
  if (prefs !== undefined) store.set("easyread-prefs", JSON.stringify(prefs));
  const root = { dataset: { theme }, style: { setProperty(k, v) { calls.set++; style.set(k, v); }, removeProperty(k) { calls.remove++; style.delete(k); } } };
  const PR = {
    t: (s, v) => (v ? s.replace(/\{(\w+)\}/g, (_, k) => v[k]) : s),
    ls: { get: (k, d) => { try { return store.has(k) ? JSON.parse(store.get(k)) : d; } catch (e) { return d; } }, set: (k, v) => store.set(k, JSON.stringify(v)) },
    applyTheme(t) { root.dataset.theme = t === "dark" ? "dark" : "light"; },
    savePrefs(section, obj) { PR.saved = { section, obj }; },
  };
  const ctx = { window: { PR }, document: { documentElement: root } };
  vm.runInNewContext(src, ctx);
  return { PR, P: PR.palette, root, style, calls, store };
}
const J = (x) => JSON.parse(JSON.stringify(x));  // vm 里造的对象原型不同，比较前先转一遍
const { P } = env();

test("WCAG 对比度：黑白 21:1，同色 1:1，已知值", () => {
  assert.equal(P.contrast("#000000", "#ffffff").toFixed(2), "21.00");
  assert.equal(P.contrast("#777777", "#777777").toFixed(2), "1.00");
  assert.equal(P.contrast("#767676", "#ffffff").toFixed(2), "4.54");  // 公认的 AA 临界灰
});

test("每组现成配色达标：ink/bg ≥ 7，ink-2/bg ≥ 4.5，ink-3/bg ≥ 3", () => {
  for (const mode of ["light", "dark"]) for (const p of P.PRESETS[mode]) {
    if (!p.bg) continue;
    const v = P.derive(p.bg, p.ink);
    assert.ok(P.contrast(v["--ink"], v["--bg"]) >= 7, mode + p.id + " ink");
    assert.ok(P.contrast(v["--ink-2"], v["--bg"]) >= 4.5, mode + p.id + " ink-2");
    assert.ok(P.contrast(v["--ink-3"], v["--bg"]) >= 3, mode + p.id + " ink-3");
  }
});

test("衍生色：默认的 bg/ink 算出来和 base.css 原值只差几个色阶；ink-3 即使 ink 偏弱也保证 3:1", () => {
  const css = fs.readFileSync(path.join(__dirname, "../easyread/web/css/base.css"), "utf8");
  const block = (re) => Object.fromEntries([...css.match(re)[1].matchAll(/(--[a-z0-9-]+):\s*(#[0-9a-f]{6});/g)].map((m) => [m[1], m[2]]));
  const light = block(/:root \{([^}]*)\}/), dark = block(/:root\[data-theme="dark"\] \{([^}]*)\}/);
  for (const [mode, ref] of [["light", light], ["dark", dark]]) {
    const v = P.derive(ref["--bg"], ref["--ink"]);
    for (const k of P.VARS) {
      const d = Math.max(...[1, 3, 5].map((i) => Math.abs(parseInt(v[k].slice(i, i + 2), 16) - parseInt(ref[k].slice(i, i + 2), 16))));
      assert.ok(d <= 8, `${mode} ${k} 差 ${d}：${v[k]} vs ${ref[k]}`);
    }
  }
  const weak = P.derive("#ffffff", "#595959");  // 刚好 7:1 的灰字
  assert.ok(P.contrast(weak["--ink-3"], "#ffffff") >= 3 && P.contrast(weak["--ink-2"], "#ffffff") >= 4.5);
});

test("autoInk：保持色相、调明度到达标；已经达标则不动", () => {
  const out = P.autoInk("#ffffff", "#ffd0d0");  // 浅粉字压到 ≥7:1，仍是偏红
  assert.ok(P.contrast(out, "#ffffff") >= 7);
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(out.slice(i, i + 2), 16));
  assert.ok(r > g && r > b);
  assert.equal(P.autoInk("#ffffff", "#000000"), "#000000");
  const lift = P.autoInk("#000000", "#303030");  // 暗背景把字提亮
  assert.ok(P.contrast(lift, "#000000") >= 7);
});

test("未设置：不写任何 inline 变量", () => {
  for (const prefs of [undefined, {}, { palette: {} }, { palette: { light: { preset: "default" } } }]) {
    const e = env(prefs);
    assert.equal(e.calls.set, 0, JSON.stringify(prefs));
    assert.equal(e.style.size, 0);
  }
});

test("套用与清除、深浅切换重套（各自独立）", () => {
  const prefs = { palette: { light: { preset: "white" }, dark: { custom: { bg: "#101820", ink: "#e0e8f0" } } } };
  const e = env(prefs, "light");
  assert.equal(e.style.get("--bg"), "#ffffff");
  assert.equal(e.style.size, 8);
  e.PR.applyTheme("dark");
  assert.equal(e.style.get("--bg"), "#101820");
  assert.equal(e.style.get("--ink"), "#e0e8f0");
  e.root.dataset.theme = "light"; e.P.apply();  // 没经过 applyTheme（系统切换）也能直接重套
  assert.equal(e.style.get("--bg"), "#ffffff");
  // 清除：深色没设 → 切到只设了浅色的情况，深色不残留浅色的值
  const f = env({ palette: { light: { preset: "white" } } }, "light");
  f.PR.applyTheme("dark");
  assert.equal(f.style.size, 0);
  // 预览与还原
  f.P.preview({ dark: { custom: { bg: "#202020", ink: "#f0f0f0" } } });
  assert.equal(f.style.get("--bg"), "#202020");
  f.P.endPreview();
  assert.equal(f.style.size, 0);
});

test("commit：写缓存、写 prefs、写早期变量；非法的抛错且不落地", () => {
  const e = env({}, "light");
  e.P.commit({ light: { preset: "green" } });
  assert.deepEqual(JSON.parse(e.store.get("easyread-prefs")).palette, { light: { preset: "green" } });
  assert.deepEqual(J(e.PR.saved), { section: "reader", obj: { palette: { light: { preset: "green" } } } });
  const vars = JSON.parse(e.store.get("easyread-palette-vars"));
  assert.equal(vars.light["--bg"], "#dcebd5");
  assert.equal(vars.dark, null);
  assert.throws(() => e.P.commit({ light: { custom: { bg: "#ffffff", ink: "#fefefe" } } }));  // 对比度 < 3
  assert.throws(() => e.P.commit({ light: { custom: { bg: "red;}</style><script>", ink: "#000000" } } }));
  assert.deepEqual(JSON.parse(e.store.get("easyread-prefs")).palette, { light: { preset: "green" } });
});

test("输入验证：非法色值、未知 preset、多余键一律拒绝", () => {
  const bad = [
    { light: { custom: { bg: "#fff", ink: "#000000" } } },            // 3 位
    { light: { custom: { bg: "#ffffff\n", ink: "#000000" } } },       // 结尾换行
    { light: { custom: { bg: "#gggggg", ink: "#000000" } } },
    { light: { custom: { bg: "red", ink: "#000000" } } },
    { light: { custom: { bg: "#ffffff;}</style><script>alert(1)</script>", ink: "#000000" } } },
    { light: { custom: { bg: "#ffffff", ink: "#000000", extra: "#000000" } } },
    { light: { custom: { bg: 16777215, ink: "#000000" } } },
    { light: { preset: "nope" } },
    { light: { preset: "oled" } },                                    // 深色的 preset 不能放浅色
    { light: { preset: "white", custom: { bg: "#ffffff", ink: "#000000" } } },
    { sepia: { preset: "white" } },
    { light: "white" },
    [],
    "x",
  ];
  for (const p of bad) assert.equal(P.clean(p), null, JSON.stringify(p));
  assert.deepEqual(J(P.clean({ light: { custom: { bg: "#FFFFFF", ink: "#000000" } } })), { light: { custom: { bg: "#ffffff", ink: "#000000" } } });
  // 被篡改的缓存不会被套用
  const e = env({ palette: { light: { custom: { bg: "#ffffff);x", ink: "#000000" } } } });
  assert.equal(e.calls.set, 0);
});

test("对比度下限：< 3:1 不能 commit，≥ 3:1 可以；预览宽松", () => {
  const e = env({}, "light");
  assert.equal(P.clean({ light: { custom: { bg: "#ffffff", ink: "#bbbbbb" } } }), null);  // ≈1.9:1
  assert.ok(P.clean({ light: { custom: { bg: "#ffffff", ink: "#949494" } } }));            // ≈3.0:1
  e.P.preview({ light: { custom: { bg: "#ffffff", ink: "#bbbbbb" } } });
  assert.equal(e.style.get("--ink"), "#bbbbbb");  // 预览看得到
});
