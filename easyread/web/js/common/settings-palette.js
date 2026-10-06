/* 设置 → 阅读 页里的“配色”区块：现成配色卡片 + 自定义背景色／文字色，浅色、深色各一套。
   草稿放在 s.pal，改动即时预览到页面（PR.palette.preview），点“保存”才真正存（PR.palette.commit），取消／关掉对话框就还原。
   颜色一律用 setProperty 设到元素上，不往 HTML／style 字符串里拼。 */
(function (PR) {
  "use strict";
  const P = () => PR.palette;
  const curMode = () => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  const modeName = (m) => (m === "dark" ? PR.t("深色") : PR.t("浅色"));
  const entry = (s) => s.pal[s.palMode] || { preset: "default" };
  const baseOf = (s) => P().baseOf(s.palMode, entry(s)) || P().DEFAULTS[s.palMode];
  const fmt = (r) => (Math.round(r * 10) / 10).toFixed(1) + ":1";

  function init(s) {
    if (!s.pal) s.pal = JSON.parse(JSON.stringify(P().saved()));
    if (!s.palMode) s.palMode = curMode();
  }
  function setEntry(s, e) {
    s.pal[s.palMode] = e;
    P().preview(s.pal);
  }

  const PanelApi = {
    html(s) {
      init(s);
      const m = s.palMode, e = entry(s), isCustom = !!e.custom;
      const card = (id, name, bg, ink, on, attr) => '<button type="button" class="pal-card' + (on ? " on" : "") + '" ' + attr + ' data-bg="' + PR.esc(bg) + '" data-ink="' + PR.esc(ink) + '"><span class="pal-sw">Aa</span><span class="pal-name">' + PR.esc(name) + "</span></button>";
      const D = P().DEFAULTS[m], b = baseOf(s);
      const cards = P().PRESETS[m].map((p) => card(p.id, p.name, p.bg || D.bg, p.ink || D.ink, !isCustom && (e.preset || "default") === p.id, 'data-pal-preset="' + p.id + '"')).join("") +
        card("custom", PR.t("自定义"), isCustom ? b.bg : D.bg, isCustom ? b.ink : D.ink, isCustom, "data-pal-custom");
      const row = (key, label) => '<div class="pal-row"><span>' + label + '</span><input type="color" class="pal-color" data-pal-color="' + key + '" value="' + PR.esc(b[key]) + '"><input class="input pal-hex" data-pal-hex="' + key + '" value="' + PR.esc(b[key]) + '" maxlength="7" spellcheck="false" autocomplete="off"></div>';
      return '<h4 class="set-h">' + PR.t("配色") + '</h4><p class="set-lead">' + PR.t("调整背景和文字的颜色。浅色、深色各自独立；只影响背景和文字，强调色、荧光笔等不变。") + "</p>" +
        '<div class="pal-modes"><span>' + PR.t("正在编辑") + '</span><button type="button" data-pal-mode="light" class="' + (m === "light" ? "on" : "") + '">' + modeName("light") + '</button><button type="button" data-pal-mode="dark" class="' + (m === "dark" ? "on" : "") + '">' + modeName("dark") + "</button>" +
        '<small class="hint">' + (m === curMode() ? PR.t("当前页面正在使用这一套，改动会马上显示。") : PR.t("当前页面是{mode}，这一套切换到{other}时才会生效。", { mode: modeName(curMode()), other: modeName(m) })) + "</small></div>" +
        '<div class="pal-cards">' + cards + "</div>" +
        (isCustom ? '<div class="pal-custom">' + row("bg", PR.t("背景色")) + row("ink", PR.t("文字色")) +
          '<div class="pal-ratio"></div><div class="pal-warn"></div><div class="pal-btns"><button type="button" class="btn sm" data-pal-auto>' + PR.t("自动调整文字色") + "</button></div></div>" : "") +
        '<div class="pal-preview"><b>' + PR.t("预览") + "</b><p>" + PR.t("这是正文的样子，长时间阅读时眼睛会感谢合适的颜色。") + "</p><p class=\"p2\">" + PR.t("次要文字") + "</p><p class=\"p3\">" + PR.t("辅助文字") + "</p></div>" +
        '<div class="keys-foot" style="margin-top:4px"><span class="hint">' + PR.t("保存后才会记住；取消则还原。") + '</span><button type="button" class="btn sm" data-pal-reset>' + PR.t("重设为默认") + "</button></div>";
    },
    /* 渲染后：把色票、预览的颜色设上去（用 setProperty），并刷新对比度读数 */
    after(s, dlg) {
      if (!s.pal) return;
      dlg.querySelectorAll(".pal-card").forEach((c) => { c.style.setProperty("--sw-bg", c.dataset.bg); c.style.setProperty("--sw-ink", c.dataset.ink); });
      PanelApi.refresh(s, dlg);
    },
    refresh(s, dlg) {
      const b = baseOf(s), v = P().derive(b.bg, b.ink), pv = dlg.querySelector(".pal-preview");
      if (pv) { pv.style.setProperty("--pv-bg", v["--bg"]); pv.style.setProperty("--pv-surface", v["--surface"]); pv.style.setProperty("--pv-ink", v["--ink"]); pv.style.setProperty("--pv-ink2", v["--ink-2"]); pv.style.setProperty("--pv-ink3", v["--ink-3"]); pv.style.setProperty("--pv-rule", v["--rule"]); }
      const r = P().contrast(b.bg, b.ink), ratio = dlg.querySelector(".pal-ratio"), warn = dlg.querySelector(".pal-warn");
      if (ratio) ratio.textContent = PR.t("文字色／背景色对比度：{r}", { r: fmt(r) });
      if (warn) {
        warn.textContent = r < P().MIN_SAVE ? PR.t("对比度低于 3:1，字几乎看不清，不能保存。可以点“自动调整文字色”。") : r < P().WARN_BELOW ? PR.t("对比度偏低（建议至少 4.5:1），长时间阅读容易累。") : "";
        warn.className = "pal-warn" + (r < P().MIN_SAVE ? " bad" : r < P().WARN_BELOW ? " warn" : "");
      }
    },
    click(e, s) {
      init(s);
      const mb = e.target.closest("[data-pal-mode]"), pc = e.target.closest("[data-pal-preset]");
      if (mb) { s.palMode = mb.dataset.palMode; return true; }
      if (pc) { setEntry(s, { preset: pc.dataset.palPreset }); return true; }
      if (e.target.closest("[data-pal-custom]")) { if (!entry(s).custom) { const b = baseOf(s); setEntry(s, { custom: { bg: b.bg, ink: b.ink } }); } return true; }
      if (e.target.closest("[data-pal-reset]")) { setEntry(s, { preset: "default" }); return true; }
      if (e.target.closest("[data-pal-auto]") && entry(s).custom) {
        const c = entry(s).custom;
        setEntry(s, { custom: { bg: c.bg, ink: P().autoInk(c.bg, c.ink) } });
        return true;
      }
      return false;
    },
    /* 取色器拖动、输入十六进制：不重绘（重绘会把正在拖的取色器弄丢），只就地更新 */
    input(e, s, dlg) {
      const key = e.target.dataset.palColor || e.target.dataset.palHex;
      if (!key || !s.pal || !entry(s).custom) return false;
      let v = String(e.target.value).trim();
      if (e.target.dataset.palHex) {
        if (v && v[0] !== "#") v = "#" + v;
        const ok = P().isHex(v);
        e.target.classList.toggle("bad", !ok);
        if (!ok) return false;
      }
      v = v.toLowerCase();
      const c = Object.assign({}, entry(s).custom, { [key]: v });
      setEntry(s, { custom: c });
      const other = dlg.querySelector(e.target.dataset.palColor ? '[data-pal-hex="' + key + '"]' : '[data-pal-color="' + key + '"]');
      if (other) { other.value = v; other.classList && other.classList.remove("bad"); }
      const card = dlg.querySelector("[data-pal-custom]");
      if (card) { card.dataset.bg = c.bg; card.dataset.ink = c.ink; card.style.setProperty("--sw-bg", c.bg); card.style.setProperty("--sw-ink", c.ink); }
      PanelApi.refresh(s, dlg);
      return false;
    },
    followTheme(s) { if (s.pal) s.palMode = curMode(); },
    /* 保存前检查：任一模式的自定义配色对比度 < 3:1 就不让存 */
    validate(s) {
      if (!s.pal) return "";
      for (const m of ["light", "dark"]) {
        const c = s.pal[m] && s.pal[m].custom;
        if (c && P().contrast(c.bg, c.ink) < P().MIN_SAVE) return PR.t("{mode}配色的文字色和背景色对比度低于 3:1，看不清，不能保存。", { mode: modeName(m) });
      }
      return "";
    },
    commit(s) { if (s.pal) P().commit(s.pal); },
  };
  PR.palettePanel = PanelApi;

  /* 对话框开着时系统深浅色变了：编辑的模式跟着换 */
  if (typeof MutationObserver !== "undefined") new MutationObserver(() => {
    const d = document.getElementById("settingsDlg"), s = PR.settingsState;
    if (d && d.classList.contains("open") && s && s.pal && s.tab === "reading" && s.palMode !== curMode()) { s.palMode = curMode(); PR.settingsRender && PR.settingsRender(); }
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
})(window.PR);
