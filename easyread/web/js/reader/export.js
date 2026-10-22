/* 导出笔记：勾选要哪些（我的笔记、划线、我的问题、AI 的回答和解释、论文笔记、问 AI 的对话），导出 Markdown。 */
(function (PR) {
  "use strict";
  const S = PR.state;
  const KINDS = [
    ["paper", PR.t("论文笔记（整篇的感悟）")], ["note", PR.t("我的笔记")], ["highlight", PR.t("我的划线")], ["question", PR.t("我的问题")],
    ["ai", PR.t("AI 的回答和解释（页边）")], ["chat", PR.t("问 AI 的对话记录")], ["quote", PR.t("每条附上原文引用")],
  ];

  function counts() {
    const notes = PR.myNotes();
    return {
      paper: (S.reader.paper_note || {}).body ? 1 : 0,
      note: notes.filter((n) => n.kind === "note" || (n.kind !== "question" && n.kind !== "highlight")).length,
      highlight: notes.filter((n) => n.kind === "highlight").length,
      question: notes.filter((n) => n.kind === "question").length,
      ai: (S.discussion.entries || []).length,
    };
  }

  PR.openExport = function () {
    const c = counts();
    const saved = PR.ls.get("easyread-export", { paper: true, note: true, highlight: true, question: true, ai: true, chat: false, quote: true });
    const dlg = PR.$("#readerDlg");
    dlg.querySelector(".dialog").innerHTML = "<h2>" + PR.t("导出笔记") + "</h2><div class=\"exp-opts\">" +
      KINDS.map(([k, l]) => '<label><input type="checkbox" data-exp="' + k + '"' + (saved[k] ? " checked" : "") + ">" + l +
        (c[k] != null ? '<span class="n">' + PR.t("{n} 条", { n: c[k] }) + "</span>" : "") + "</label>").join("") +
      '</div><p class="hint">' + PR.t("导出成 Markdown，按原文章节顺序排，可以直接放进 Obsidian、Notion。") + PR.t("笔记里有图片时导出成 zip（含图片文件）。") + "</p>" +
      (pdfOk() ? '<p class="hint">' + PR.t("也可以把划线标到英文原 PDF 上，另存一份副本（原文件不动）：译文上的划线标对应的整句英文，原文上的划线标原话。") + "</p>" : "") +
      (obsOk() ? '<p class="hint"><button class="btn line" data-exp-obs' + (obsRunning ? " disabled" : "") + ">" + PR.t("写进 Obsidian") + '</button> <span data-obs-status>' + (obsRunning ? PR.t("模型思考中，约需一两分钟") : "") + "</span><br>" +
        PR.t("会用到你的 AI 额度，只有按下才会执行；不会覆盖已有的文件。") + "</p>" : "") +
      '<div class="actions">' + (pdfOk() ? '<button class="btn line" data-exp-pdf style="margin-right:auto">' + PR.t("导出带划线的 PDF") + "</button>" : "") +
      '<button class="btn" data-exp-close>' + PR.t("取消") + '</button><button class="btn primary" data-exp-go>' + PR.t("导出") + "</button></div>";
    dlg.classList.add("open");
  };

  /* 带划线的 PDF 要服务端读原 PDF 生成：离线单文件版和在线演示没有服务，不显示这个入口 */
  const pdfOk = () => PR.store.mode === "server" && !S.demo;

  /* 写进 Obsidian 要服务端调模型：离线单文件版和在线演示没有服务，不显示 */
  const obsOk = () => PR.store.mode === "server" && !S.demo;
  let obsRunning = false;
  const obsStatus = (text, busy) => {
    const el = PR.$("[data-obs-status]"), b = PR.$("[data-exp-obs]");
    if (el) el.textContent = text || "";
    if (b) b.disabled = !!busy;
  };

  PR.exportToObsidian = async function () {
    if (obsRunning) { PR.toast(PR.t("正在写进 Obsidian，进行中，请稍候")); return; }
    obsRunning = true;
    try {
      let cfg = null;
      try { cfg = (await PR.api("/api/config")).config; } catch (err) { cfg = null; }  // 读不到设置就直接请求，让服务端判断
      if (cfg && !(cfg.obsidian_vault || "").trim()) {
        PR.toast(PR.t("请先到 设置 → 阅读 设置 Obsidian 文件夹"), null, 7000);
        return;
      }
      if (PR.store.pending) await PR.flush();  // 刚划的线可能还在待存队列里，先写进文献库
      obsStatus(PR.t("模型思考中，约需一两分钟"), true);
      PR.toast(PR.t("模型思考中，约需一两分钟"), null, 6000);
      const job = await PR.api("/api/p/" + PR.pid + "/obsidian-note", { method: "POST", body: {} });
      const deadline = Date.now() + 25 * 60 * 1000;
      while (Date.now() < deadline) {
        await new Promise((res) => setTimeout(res, PR.obsidianPollMs || 1500));
        let j = null;
        try { j = ((await PR.api("/api/jobs?pid=" + encodeURIComponent(PR.pid))).jobs || []).find((x) => x.kind === "obsidian" && x.id === job.id); } catch (err) { j = null; }  // 偶发读取失败就下一轮再试
        if (!j) continue;
        if (j.state === "done") {
          let msg = PR.t("已写入：{path}", { path: PR.esc(j.path || "") });
          if (j.skipped > 0) msg += "<br>" + PR.t("有 {n} 张图没能截取，已略过", { n: j.skipped });
          PR.toast(msg, null, 12000);
          return;
        }
        if (j.state === "error") { PR.toast(PR.t("写进 Obsidian 失败：{msg}", { msg: PR.esc(j.message || "") }), null, 12000); return; }
      }
      PR.toast(PR.t("等了很久还没完成，请到任务状态里查看"), null, 12000);
    } catch (err) {
      PR.toast(PR.t("写进 Obsidian 失败：{msg}", { msg: PR.esc(err.message) }), null, 12000);
    } finally {
      obsRunning = false;
      obsStatus("", false);
    }
  };

  function dispositionName(r, fallback) {
    const m = /filename\*=UTF-8''([^;]+)/i.exec(r.headers.get("Content-Disposition") || "");
    try { return m ? decodeURIComponent(m[1]) : fallback; } catch (err) { return fallback; }
  }

  PR.exportAnnotatedPdf = async function () {
    if (!pdfOk()) return;
    if (!PR.myNotes().some((n) => n.quote)) {
      PR.toast(PR.t("这篇还没有划线：先在正文里选中文字划线，再导出带划线的 PDF"));
      return;
    }
    if (PR.store.pending) await PR.flush();  // 刚划的线可能还在待存队列里，先写进文献库
    const left = PR.store.pending;
    let r;
    try {
      r = await fetch("/api/p/" + PR.pid + "/annotated-pdf", { method: "POST", headers: { "Content-Type": "application/json", "X-Token": PR.token || "" }, body: "{}" });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
    } catch (err) { PR.toast(PR.t("导出失败：{msg}", { msg: PR.esc(err.message) })); return; }
    const blob = await r.blob();
    const a = PR.el("a", { href: URL.createObjectURL(blob), download: dispositionName(r, "annotated.pdf") });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
    const written = +r.headers.get("X-EasyRead-Written") || 0, skipped = +r.headers.get("X-EasyRead-Skipped") || 0;
    let msg = PR.t("已导出 {n} 条划线", { n: written });
    if (skipped) {
      let detail = [];
      try { detail = JSON.parse(decodeURIComponent(r.headers.get("X-EasyRead-Skipped-Detail") || "[]")); } catch (err) { detail = []; }
      msg += PR.t("；{n} 条因找不到对应位置未导出", { n: skipped }) + "<br>" + detail.slice(0, 5).map((d) =>
        PR.esc(PR.t("第 {page} 页「{quote}」", { page: d.page == null ? "?" : d.page, quote: d.quote || "" }))).join("<br>") + (skipped > 5 ? "<br>…" : "");
    }
    if (left) msg += "<br>" + PR.t("还有 {n} 条修改没写进文献库，这次导出不含它们", { n: left });
    PR.toast(msg, null, skipped || left ? 12000 : 4200);
  };

  PR.$("#readerDlg").addEventListener("click", async (e) => {
    const dlg = PR.$("#readerDlg");
    if (e.target.closest("[data-exp-close]")) return dlg.classList.remove("open");
    if (e.target.closest("[data-exp-obs]")) return PR.exportToObsidian();
    if (e.target.closest("[data-exp-pdf]")) { dlg.classList.remove("open"); return PR.exportAnnotatedPdf(); }
    if (!e.target.closest("[data-exp-go]")) return;
    const pick = {};
    PR.$$("[data-exp]", dlg).forEach((i) => (pick[i.dataset.exp] = i.checked));
    PR.ls.set("easyread-export", pick);
    let chat = [];
    if (pick.chat) {
      let data = S.chat || {};
      if (PR.store.mode === "server") {
        try { data = await PR.api("/api/p/" + PR.pid + "/chat"); }
        catch (err) { PR.toast(PR.t("读不到对话记录：{msg}", { msg: PR.esc(err.message) })); return; }
      }
      chat = data.threads ? data.threads.flatMap((t) => t.messages || []) : data.messages || [];
    }
    let text = PR.notesMarkdown(pick, chat);
    const stem = ((S.paper.meta || {}).short_zh || (S.paper.meta || {}).title_zh || PR.t("论文")).replace(/[\\/:*?"<>|]/g, "");
    let blob = new Blob([text], { type: "text/markdown;charset=utf-8" }), name = stem + PR.t("-笔记.md");
    const IMG = /!\[[^\]\n]*\]\(note-images\/[0-9a-f]{32}\.(?:png|jpg|webp|gif)\)/g;
    if (IMG.test(text)) {  // 笔记里有图：Markdown 单文件会留下断掉的图片链接，改导出 zip（notes.md + note-images/）
      IMG.lastIndex = 0;
      if (PR.store.mode === "server") {
        try {
          const r = await fetch("/api/p/" + PR.pid + "/notes-zip", { method: "POST", headers: { "Content-Type": "application/json", "X-Token": PR.token || "" }, body: JSON.stringify({ md: text, stem }) });
          if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
          blob = await r.blob(); name = stem + PR.t("-笔记.zip");
        } catch (err) { PR.toast(PR.t("导出失败：{msg}", { msg: PR.esc(err.message) })); return; }
      } else {  // 离线版没有服务，打不了 zip：图片位置留一句说明，不留断链
        text = text.replace(IMG, PR.t("（图片未导出）"));
        blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
      }
    }
    const a = PR.el("a", { href: URL.createObjectURL(blob), download: name });
    document.body.appendChild(a); a.click(); a.remove();
    dlg.classList.remove("open");
  });
})(window.PR);
