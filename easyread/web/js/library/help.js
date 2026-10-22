/* 顶栏的问号：最上面是版本和检查更新（update.js 画，PR.updatePanel），下面是几条常见问题，
   答案直接写在这里，要动手的地方（看日志、打开文献库）就在答案里放按钮；最后是去 GitHub 反馈。按 ? 也能打开。 */
(function (PR) {
  "use strict";
  const ISSUES = "https://github.com/Edwardxlai/easyread/issues/new/choose";
  const dlg = PR.$("#textDlg");
  const btn = PR.$("#helpBtn");
  btn.innerHTML = PR.icon("question") + '<span class="help-dot"></span>';
  btn.title = PR.t("帮助与关于");
  btn.onclick = () => PR.openHelp();

  const act = (name, label) => ' <button class="linkish" data-help-do="' + name + '">' + label + "</button>";
  const faq = () => [
    [PR.t("翻译到一半失败了怎么办？"), PR.t("在文献库里点这篇，右侧“翻译”一栏写着失败的原因和页码，点“重试”就行，已经译好的页不会重译。额度用完了就等额度恢复，或者在“设置 → 模型”里临时换一个模型。") +
      act("log", PR.t("看运行日志"))],
    [PR.t("怎么更新？论文和笔记会丢吗？"), PR.t("点上面的“检查更新”。Windows、macOS 安装版和 Linux 的 AppImage 点“更新”会自动下载并重启装好（macOS 从 1.3.3 起）；从源码运行的照旧下载新版。论文、笔记和设置都不受影响。")],
    [PR.t("论文和笔记存在哪？怎么备份、换电脑？"), PR.t("都在文献库文件夹里，每篇论文一个文件夹，复制整个文件夹就是备份。想在几台电脑上接着读，在“设置 → 云文献库”里把它迁到网盘的同步文件夹。") +
      act("library", PR.t("打开文献库文件夹"))],
    [PR.t("能发给没装 EasyRead 的人看吗？"), PR.t("能。在文献库里右键论文，选“导出离线 HTML”，得到一个网页文件，对方用浏览器打开就能看译文、原页、你的划线和笔记。")],
    [PR.t("用 Claude Code 翻译要挂梯子吗？"), PR.t("和你平时在终端里用 claude 一样：平时要，这里也要。不想折腾就在“设置 → 模型”里加智谱、硅基流动、DeepSeek 这类国内能直连的 API，或者本机 Ollama。")],
  ];

  PR.openHelp = function () {
    dlg.querySelector(".dialog").innerHTML =
      '<div class="help-head">' + PR.logo("hero sm") + '<div><h2>EasyRead</h2><div class="hint">' + PR.t("本地运行，论文和笔记只存在你的电脑上") + "</div></div></div>" +
      (PR.updatePanel ? PR.updatePanel() : "") +
      '<h4 class="help-h">' + PR.t("常见问题") + '</h4><div class="help-faq">' +
      faq().map(([q, a]) => "<details><summary>" + q + "</summary><p>" + a + "</p></details>").join("") + "</div>" +
      '<div class="help-ask"><span>' + PR.t("没找到答案，或者想提建议？") + '</span><a class="btn sm line" href="' + ISSUES + '" target="_blank" rel="noopener">' + PR.t("去 GitHub 反馈") + "</a></div>" +
      '<div class="actions"><button class="btn" data-close>' + PR.t("关闭") + "</button></div>";
    dlg.classList.add("open");
  };

  dlg.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-help-do]");
    if (!b) return;
    e.preventDefault();
    try {
      if (b.dataset.helpDo === "library") return void await PR.api("/api/library/reveal", { method: "POST", body: {} });
      const r = await PR.api("/api/log");  // 和设置底部的“运行日志”一样
      PR.showText(PR.t("运行日志"), r.text + "\n\n" + PR.t("（完整日志：{path}）", { path: r.path }));
    } catch (err) { PR.toast(PR.esc(err.message)); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "?" || e.target.closest("input, textarea, select, [contenteditable]") || PR.$(".dialog-backdrop.open")) return;
    e.preventDefault();
    PR.openHelp();
  });
})(window.PR);
