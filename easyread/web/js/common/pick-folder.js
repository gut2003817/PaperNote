/* 选一个文件夹：桌面版用系统窗口；浏览器版让后端弹系统窗口，弹不出来才让人填路径。
   PR.pickFolder({title, body}) → Promise<路径 | null> */
(function (PR) {
  "use strict";
  PR.pickFolder = async function (o) {
    const desktop = window.easyreadDesktop;
    if (desktop && desktop.pickFolder) return (await desktop.pickFolder()) || null;
    const r = await PR.api("/api/library/pick-folder", { method: "POST", body: { title: o.title } }).catch(() => ({ supported: false }));
    if (r.supported) return r.path || null;
    return PR.promptText({ title: o.title, body: o.body || PR.t("填写文件夹的完整路径。"), max: 4096 });
  };
  /* 成批匯入用：只接受這次親手在系統視窗裡選的資料夾，回 {path, nonce}（後端 server/pick_grants.py）。
     彈不出系統視窗就不能匯入：不讓人手打路徑。 */
  PR.pickFolderGranted = async function (o) {
    const desktop = window.easyreadDesktop;
    if (desktop && desktop.pickFolderGranted) return (await desktop.pickFolderGranted()) || null;
    const r = await PR.api("/api/library/pick-folder", { method: "POST", body: { title: o.title } }).catch(() => ({ supported: false }));
    if (r.supported && r.path && r.nonce) return { path: r.path, nonce: r.nonce };
    if (!r.supported || r.path === "") PR.toast(PR.t("这台电脑弹不出选文件夹的窗口，没办法导入：为了安全，只接受在系统窗口里亲手选的文件夹"), null, 8000);
    return null;
  };
})(window.PR);
