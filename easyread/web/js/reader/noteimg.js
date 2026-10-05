/* 笔记里放图片：在笔记输入框里粘贴截图、点“图片”按钮选文件、把图片文件拖进来，都会传到本地服务，
   成功后把 ![](note-images/xxx.png) 插在光标处。类型和大小以服务端检查为准，这里只是先挡一道、给出明白的提示。
   输入框有三种：页边卡片、笔记面板里的卡片、论文笔记（#paperNote）。离线版没有地方存图，只拦住拖放避免页面被带走。 */
(function (PR) {
  "use strict";
  const S = PR.state;
  const MAX = 10 * 1024 * 1024;
  const TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
  const SEL = "#margin .card textarea, .inline-notes .card textarea, #notespanel .card textarea, #paperNote";
  let picking = false, uploading = 0;
  /* 选图或上传期间，笔记编辑框失去焦点不算“编辑结束”（margin.js / notespanel.js 的 focusout 会问这个） */
  PR.noteImgBusy = () => picking || uploading > 0;

  const online = () => PR.store.mode === "server";
  const tell = (msg) => PR.toast(msg, null, 6000);
  const target = (ta) => { if (ta.id === "paperNote") return { paper: true }; const c = ta.closest(".card"); return { id: c && c.dataset.note }; };
  const textareaOf = (t) => (t.paper ? PR.$("#paperNote") : t.id && PR.$('.card[data-note="' + t.id + '"] textarea'));

  function insert(t, md, pos) {
    const ta = textareaOf(t);
    if (ta) {
      const v = ta.value;
      const at = document.activeElement === ta ? ta.selectionStart : Math.min(pos, v.length);
      const before = v.slice(0, at), after = v.slice(at);
      const ins = (before && !before.endsWith("\n") ? "\n" : "") + md + (after && !after.startsWith("\n") ? "\n" : "");
      ta.value = before + ins + after;
      ta.focus();
      ta.setSelectionRange(before.length + ins.length, before.length + ins.length);
      ta.dispatchEvent(new Event("input", { bubbles: true }));  // 走原有的自动保存、自动增高
      return;
    }
    /* 上传期间编辑框被重画掉了：直接把图片接在笔记末尾存起来，图不会丢 */
    if (t.paper) {
      const cur = (S.reader.paper_note || {}).body || "";
      PR.commit({ op: "paper_note", body: cur + (cur ? "\n\n" : "") + md });
    } else {
      const n = (S.reader.notes || {})[t.id];
      if (!n || n.deleted) return tell(PR.t("图片已上传，但这条笔记已经不在了"));
      PR.saveNote(Object.assign({}, n, { body: (n.body ? n.body + "\n\n" : "") + md, kind: n.kind === "highlight" ? "note" : n.kind }));
    }
    PR.renderMargin(); PR.applyMarks && PR.applyMarks();
    PR.notesPanelOpen && PR.notesPanelOpen() && PR.renderNotesPanel();
  }

  async function uploadAll(files, ta) {
    if (!online()) return tell(PR.t("离线版不能插入图片"));
    const t = target(ta);
    let pos = ta.selectionStart || 0;
    uploading++;
    ta.classList.add("uploading");
    try {
      for (const f of files) {
        if (!TYPES.includes(f.type)) { tell(PR.t("只支持 PNG、JPEG、WebP、GIF 图片")); continue; }
        if (f.size > MAX) { tell(PR.t("图片太大（上限 {mb} MB）", { mb: MAX / 1024 / 1024 })); continue; }
        tell(PR.t("正在上传图片…"));
        try {
          const r = await PR.api("/api/p/" + PR.pid + "/note-image", { method: "POST", body: f, headers: { "Content-Type": "application/octet-stream" } });
          insert(t, r.md, pos);
          pos = Infinity;
          const toast = PR.$("#toast"); toast && toast.classList.remove("open");
        } catch (err) {
          tell(PR.t("图片没有插入：{msg}", { msg: PR.esc(err.message) }));
        }
      }
    } finally {
      uploading--;
      ta.classList.remove("uploading");
      const now = textareaOf(t); now && now.classList.remove("uploading");
    }
  }

  /* 点“图片”按钮：弹出系统的选文件窗口 */
  let input = null;
  let pendingTa = null;
  PR.pickNoteImage = function (ta) {
    if (!ta || !online()) return;
    if (!input) {
      input = document.createElement("input");
      input.type = "file";
      input.accept = TYPES.join(",");
      input.multiple = true;
      input.hidden = true;
      input.addEventListener("change", () => {
        const files = [...input.files];
        input.value = "";
        const ta2 = pendingTa; pendingTa = null;
        if (files.length && ta2) { uploadAll(files, ta2); }
        picking = false;
      });
      input.addEventListener("cancel", () => { picking = false; });
      window.addEventListener("focus", () => setTimeout(() => { if (picking && !input.files.length) picking = false; }, 1000));  // 不支持 cancel 事件的浏览器
      document.body.appendChild(input);
    }
    pendingTa = ta;
    picking = true;
    input.click();
  };

  /* 粘贴截图：剪贴板里只有图片才接管；同时带文字（从网页、表格复制）就照常粘贴文字 */
  document.addEventListener("paste", (e) => {
    const ta = e.target.closest && e.target.closest(SEL);
    if (!ta || !online() || !e.clipboardData) return;
    const files = [...e.clipboardData.items].filter((i) => i.kind === "file" && i.type.startsWith("image/")).map((i) => i.getAsFile()).filter(Boolean);
    if (!files.length || e.clipboardData.getData("text/plain").trim()) return;
    e.preventDefault();
    uploadAll(files, ta);
  });

  /* 拖放图片文件到输入框 */
  const hasFiles = (e) => e.dataTransfer && [...(e.dataTransfer.types || [])].includes("Files");
  document.addEventListener("dragover", (e) => {
    const ta = e.target.closest && e.target.closest(SEL);
    if (!ta || !hasFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = online() ? "copy" : "none";
    ta.classList.add("drop");
  });
  document.addEventListener("dragleave", (e) => { e.target.classList && e.target.classList.remove("drop"); });
  document.addEventListener("drop", (e) => {
    const ta = e.target.closest && e.target.closest(SEL);
    if (!ta || !hasFiles(e)) return;
    e.preventDefault();  // 不拦的话浏览器会把文件当网页打开，离开阅读页
    ta.classList.remove("drop");
    uploadAll([...e.dataTransfer.files], ta);
  });
})(window.PR);
