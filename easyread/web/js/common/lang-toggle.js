/* 顶栏的中 / EN 切换按钮：中文界面（简体、繁体）显示 EN，英文界面显示“中”，点一下换成另一种并刷新。
   从英文切回中文时回到上次用的那种中文（简体 / 繁体）；没记过就看译文语言设的是不是繁体。
   “跟随系统”在设置 → 阅读 → 界面语言里选。离线单文件版没有服务存设置，不显示。 */
(function (PR) {
  "use strict";
  const btn = PR.$("#langBtn");
  if (!btn) return;
  if (location.protocol === "file:") { btn.hidden = true; return; }
  const VARIANT_KEY = "easyread-zh-variant";
  const zhVariant = () => {
    try { const v = localStorage.getItem(VARIANT_KEY); if (v === "zh" || v === "zh-TW") return v; } catch (e) { /* 读不到就用默认 */ }
    return PR.target === "zh-TW" ? "zh-TW" : "zh";
  };
  if (PR.lang !== "en") { try { localStorage.setItem(VARIANT_KEY, PR.lang); } catch (e) { /* 存不下就算了 */ } }
  btn.textContent = PR.lang === "en" ? "中" : "EN";  // i18n-ok 按钮上写的是要切换到的语言
  btn.title = PR.t("切换到英文界面");
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      await PR.api("/api/prefs", { method: "POST", body: { ui: { lang: PR.lang === "en" ? zhVariant() : "en" } } });
      try { if (PR.lib && PR.lib.lastData) sessionStorage.setItem("easyread-lib-snap", JSON.stringify({ t: Date.now(), d: PR.lib.lastData })); } catch (e) { /* 存不下就普通刷新 */ }
      location.replace(location.href.split("#")[0]);  // 不用 reload：普通跳转才有淡入淡出（library.css 的 @view-transition）
    } catch (e) {
      btn.disabled = false;
      PR.toast(PR.t("保存失败：{msg}", { msg: PR.esc(e.message) }));
    }
  };
})(window.PR);
