/* 配色：背景色与文字色，浅色、深色各自独立。
   只覆盖 --bg / --surface / --surface-2 / --ink / --ink-2 / --ink-3 / --rule / --rule-2 这几个变量；强调色、荧光笔、语义色不动。
   没设置（或选“默认”）时一个 inline 变量都不写，外观就是 base.css 里的原样。
   存法：easyread-prefs.palette（localStorage 缓存）＋服务器 prefs.json 的 reader.palette；
   easyread-palette-vars 是算好的变量缓存，页面 <head> 里的小脚本最早读它来避免闪一下。
   数据：{light: {preset:"white"} | {custom:{bg:"#rrggbb", ink:"#rrggbb"}}, dark: {…}}。服务器端（easyread/palette.py）有同样的校验。 */
window.PR = window.PR || {};
(function (PR) {
  "use strict";

  const HEX = /^#[0-9a-fA-F]{6}$/;
  const isHex = (v) => typeof v === "string" && HEX.test(v);
  const VARS = ["--bg", "--surface", "--surface-2", "--ink", "--ink-2", "--ink-3", "--rule", "--rule-2"];
  const MIN_SAVE = 3;      // 文字色／背景色低于它禁止保存
  const WARN_BELOW = 4.5;  // 低于它警告

  /* base.css 里的原值；“默认”就是不覆盖，这里只在选“自定义”时当起点用 */
  const DEFAULTS = { light: { bg: "#f6f3ec", ink: "#23211d" }, dark: { bg: "#1a1917", ink: "#ddd7cb" } };
  const PRESETS = {
    light: [
      { id: "default", name: PR.t("默认米白") },
      { id: "white", name: PR.t("纯白"), bg: "#ffffff", ink: "#1a1a1a" },
      { id: "green", name: PR.t("护眼淡绿"), bg: "#dcebd5", ink: "#1e2b1e" },
      { id: "bluegray", name: PR.t("淡蓝灰"), bg: "#e6ecf2", ink: "#1c2530" },
      { id: "parchment", name: PR.t("暖黄羊皮纸"), bg: "#f4e8cf", ink: "#3a2f1e" },
      { id: "contrast", name: PR.t("高对比"), bg: "#ffffff", ink: "#000000" },
    ],
    dark: [
      { id: "default", name: PR.t("默认深灰") },
      { id: "oled", name: PR.t("纯黑（OLED）"), bg: "#000000", ink: "#d6d6d6" },
      { id: "bluegray", name: PR.t("深蓝灰"), bg: "#1b2230", ink: "#d6dce6" },
      { id: "warm", name: PR.t("暖棕"), bg: "#2a211b", ink: "#e2d5c3" },
      { id: "contrast", name: PR.t("高对比"), bg: "#000000", ink: "#ffffff" },
    ],
  };

  /* ---------- 色彩运算 ---------- */
  const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const hex = (c) => "#" + c.map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");
  const mix = (a, b, t) => { const x = rgb(a), y = rgb(b); return hex(x.map((v, i) => v + (y[i] - v) * t)); };
  function lum(h) {
    const [r, g, b] = rgb(h).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  function contrast(a, b) {
    const x = lum(a), y = lum(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  }
  /* 从 from 往 to 混，混到对 bg 的对比度至少 min（t 只增不减）；到头了还不够就是 to 本身 */
  function mixUntil(bg, ink, t, min) {
    let c = mix(bg, ink, t);
    while (t < 1 && contrast(c, bg) < min) { t = Math.min(1, t + 0.01); c = mix(bg, ink, t); }
    return c;
  }
  /* 由 bg 和 ink 推出其余变量。比例是对着 base.css 的两套默认值量出来的（浅色 t≈.04/.11/.2/.52/.75，深色 .04/.08/.125/.215/.49/.76），
     所以选默认的 bg/ink 时算出来和原值只差几个色阶。ink-2 保证 ≥4.5:1，ink-3 保证 ≥3:1。 */
  function derive(bg, ink) {
    const lightStyle = lum(bg) > lum(ink);  // 背景比文字亮：面板往白里提、凹处往字色里压；反过来则相反
    const surface = lightStyle ? mix(bg, "#ffffff", 0.55) : mix(bg, ink, 0.04);
    const surface2 = lightStyle ? mix(bg, ink, 0.04) : mix(bg, ink, 0.08);
    return {
      "--bg": bg, "--surface": surface, "--surface-2": surface2, "--ink": ink,
      "--ink-2": mixUntil(bg, ink, lightStyle ? 0.75 : 0.76, WARN_BELOW),
      "--ink-3": mixUntil(bg, ink, lightStyle ? 0.52 : 0.49, MIN_SAVE),
      "--rule": mix(bg, ink, lightStyle ? 0.11 : 0.125),
      "--rule-2": mix(bg, ink, lightStyle ? 0.2 : 0.215),
    };
  }

  /* 把一个模式的设置解析成 {bg, ink}；默认／没设返回 null */
  function baseOf(mode, e) {
    if (!e) return null;
    if (e.custom) return e.custom;
    const p = (PRESETS[mode] || []).find((x) => x.id === e.preset);
    return p && p.bg ? { bg: p.bg, ink: p.ink } : null;
  }
  function resolve(mode, e) { const b = baseOf(mode, e); return b ? derive(b.bg, b.ink) : null; }

  /* 校验：不合法返回 null。形状和服务器端一致；只放行 #RRGGBB 与白名单 id。 */
  function clean(p, lenient) {  // lenient：只给设置页预览用（低对比也先看看效果，但存不进去）
    if (!p || typeof p !== "object" || Array.isArray(p)) return null;
    const out = {};
    for (const mode of Object.keys(p)) {
      if (mode !== "light" && mode !== "dark") return null;
      const e = p[mode];
      if (e == null) continue;
      if (typeof e !== "object" || Object.keys(e).length !== 1) return null;
      if ("preset" in e) {
        if (!PRESETS[mode].some((x) => x.id === e.preset)) return null;
        out[mode] = { preset: e.preset };
      } else if (e.custom && typeof e.custom === "object" && Object.keys(e.custom).length === 2 && isHex(e.custom.bg) && isHex(e.custom.ink)) {
        if (!lenient && contrast(e.custom.bg, e.custom.ink) < MIN_SAVE) return null;
        out[mode] = { custom: { bg: e.custom.bg.toLowerCase(), ink: e.custom.ink.toLowerCase() } };
      } else return null;
    }
    return out;
  }

  /* 保持色相、调明度，让文字色对背景达到 target（默认 7:1）；调到黑／白还不够就停在极限 */
  function autoInk(bg, ink, target) {
    target = target || 7;
    if (contrast(ink, bg) >= target) return ink;
    const [r, g, b] = rgb(ink).map((v) => v / 255), mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
    let h = 0, s = 0, l = (mx + mn) / 2;
    if (d) {
      s = d / (1 - Math.abs(2 * l - 1));
      h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
      h *= 60; if (h < 0) h += 360;
    }
    const toRgb = (L) => {
      const c = (1 - Math.abs(2 * L - 1)) * s, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = L - c / 2;
      const [rr, gg, bb] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
      return hex([(rr + m) * 255, (gg + m) * 255, (bb + m) * 255]);
    };
    const dir = lum(bg) > 0.5 ? -1 : 1;  // 亮背景把字压暗，暗背景把字提亮
    let best = ink;
    for (let L = l; L >= 0 && L <= 1; L += dir * 0.005) {
      best = toRgb(L);
      if (contrast(best, bg) >= target) return best;
    }
    return best;
  }

  /* ---------- 套用 ---------- */
  const root = () => document.documentElement;
  const mode = () => (root().dataset.theme === "dark" ? "dark" : "light");
  let draft = null;  // 设置页里正在预览、还没保存的配色

  function saved() {
    const p = clean(((PR.ls && PR.ls.get("easyread-prefs", {})) || {}).palette);
    if (p) return p;
    return (typeof window !== "undefined" && clean(window.ER_PALETTE_EXPORT)) || {};  // 离线导出页：导出当时的配色
  }
  function cache(p) {  // 给 <head> 里的早期脚本：两种模式各自算好的变量
    try { PR.ls.set("easyread-palette-vars", { light: resolve("light", p.light), dark: resolve("dark", p.dark) }); } catch (e) { /* 缓存而已 */ }
  }
  function apply() {
    const p = draft || saved(), vars = resolve(mode(), p[mode()]), st = root().style;
    for (const k of VARS) st.removeProperty(k);
    if (vars) for (const k of VARS) st.setProperty(k, vars[k]);
    if (!draft) cache(p);
  }

  const orig = PR.applyTheme;
  if (orig) PR.applyTheme = function (theme) { orig.call(PR, theme); apply(); };  // 切主题、系统深浅色变化后重套
  const origLoad = PR.loadPrefs;
  if (origLoad) PR.loadPrefs = async function () { const r = await origLoad.apply(PR, arguments); apply(); return r; };  // 服务器的偏好合进缓存后重套
  if (typeof MutationObserver !== "undefined") new MutationObserver(apply).observe(root(), { attributes: true, attributeFilter: ["data-theme"] });

  function commit(p) {
    const c = clean(p);
    if (!c) throw new Error(PR.t("配色不合法"));
    const prefs = PR.ls.get("easyread-prefs", {});
    prefs.palette = c;
    PR.ls.set("easyread-prefs", prefs);
    if (PR.prefs) PR.prefs.palette = c;
    if (PR.savePrefs) PR.savePrefs("reader", { palette: c });
    draft = null;
    apply();
    return c;
  }

  PR.palette = {
    VARS, PRESETS, DEFAULTS, MIN_SAVE, WARN_BELOW, isHex, mix, lum, contrast, derive, resolve, clean, autoInk, apply, saved, commit,
    preview(p) { draft = clean(p, true) || draft; apply(); },
    endPreview() { draft = null; apply(); },
    baseOf,
  };

  if (typeof document !== "undefined" && document.documentElement) apply();
})(window.PR);
