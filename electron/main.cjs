const { app, BrowserWindow, dialog, Menu, shell, ipcMain } = require("electron");
const { execFileSync, spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const windowState = require("./window-state.cjs");
const { URL } = require("url");
const http = require("http");
const startup = require("./startup-feedback.cjs");
const { registerUpdates } = require("./desktop-updates.cjs");
const deepLink = require("./deep-link.cjs");
const dataDir = require("./data-dir.cjs");

// 窗口缓存等放 %APPDATA%\EasyRead（默认会用 package.json 的 name，叫 easyread-desktop）。
// 论文和设置不放这里：Windows 安装版放 <安装目录>\data（见 data-dir.cjs），其余平台用 ~/EasyRead。
// 环境变量不全（比如从精简环境的脚本里启动）时 getPath("appData") 会直接抛错，
// 这时按 Electron 自己的默认位置算一份，免得一启动就弹主进程报错框。
function appDataDir() {
  try {
    return app.getPath("appData");
  } catch {
    const home = os.homedir();
    if (process.platform === "win32") return process.env.APPDATA || path.join(home, "AppData", "Roaming");
    if (process.platform === "darwin") return path.join(home, "Library", "Application Support");
    return process.env.XDG_CONFIG_HOME || path.join(home, ".config");
  }
}
app.setPath("userData", path.join(appDataDir(), "EasyRead"));
startup.mark(app, "electron-entry");

// 桌面版自己的几句报错跟系统语言走（界面语言由后端决定，见 easyread/app/i18n.py）
const isZh = () => app.getLocale().toLowerCase().startsWith("zh");
// 繁体中文地区（zh-TW、zh-HK、zh-MO、zh-Hant-*）：这几句报错用繁体，别当成简体
const isZhTW = () => /^zh[-_](tw|hk|mo|hant)/i.test(app.getLocale());
const say = (cn, tw, en) => (isZhTW() ? tw : isZh() ? cn : en);
const desktopSecret = require("crypto").randomBytes(24).toString("hex");
let backend;
let mainWindow;
let backendReady;
let windowOpening = false;
let backendUrl;
let quitting = false;
let pendingOpen = deepLink.fromArgv(process.argv);

function projectRoot() {
  return path.resolve(__dirname, "..");
}

function packagedBackend() {
  const name = process.platform === "win32" ? "easyread-backend.exe" : "easyread-backend";
  return path.join(process.resourcesPath, "backend", name);
}

function backendCommand() {
  if (app.isPackaged) {
    const executable = packagedBackend();
    if (!fs.existsSync(executable)) {
      throw new Error(say(`找不到打包后的 EasyRead 后端：${executable}`, `找不到打包後的 EasyRead 後端：${executable}`, `Bundled EasyRead backend not found: ${executable}`));
    }
    return { command: executable, args: ["serve", "--port", "0"], cwd: os.homedir() };
  }

  const root = projectRoot();
  const python = process.platform === "win32"
    ? path.join(root, ".venv", "Scripts", "python.exe")
    : path.join(root, ".venv", "bin", "python");
  const command = fs.existsSync(python) ? python : (process.platform === "win32" ? "python" : "python3");
  return { command, args: ["-m", "easyread", "serve", "--port", "0"], cwd: root };
}

// macOS / Linux 从启动台、桌面图标打开时，拿不到终端里配的 PATH（Homebrew、npm 全局目录），
// 后端会找不到 claude / codex。向用户的登录 shell 要一份 PATH 补上。
function startBackend() {
  // On macOS an app can stay alive after its last window closes. Reopening
  // the window must reuse that backend, rather than orphaning the old one.
  if (backendReady) return backendReady;
  backendReady = (async () => {
  const launch = backendCommand();
  const env = { ...process.env, PYTHONUTF8: "1", EASYREAD_SYSTEM_LANG: app.getLocale(),  // 后端按它决定界面语言
    EASYREAD_DESKTOP_SECRET: desktopSecret };  // 只有主程序知道：替自己彈出的選資料夾視窗換匯入授權（server/pick_grants.py）
  startup.mark(app, "shell-path-start");
  const shellPath = await startup.loginShellPath(process.platform);
  startup.mark(app, "shell-path-ready");
  if (quitting) throw new Error(say("启动已取消", "啟動已取消", "Startup cancelled"));
  const home = await dataDir.prepare(app, line => startup.mark(app, line));
  if (home) env.EASYREAD_HOME = home;
  if (shellPath) {
    env.PATH = [...new Set([...shellPath.split(":"), ...(env.PATH || "").split(":")].filter(Boolean))].join(":");
  }
  if (process.platform !== "win32") {
    const fallback = [path.join(os.homedir(), ".local", "bin"), "/opt/homebrew/bin", "/usr/local/bin"];
    env.PATH = [...new Set([...(env.PATH || "").split(":"), ...fallback.filter(p => fs.existsSync(p))].filter(Boolean))].join(":");
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    let output = "";
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn(value);
    };
    const timer = setTimeout(() => {
      finish(reject, new Error(say("EasyRead 后端启动超时。", "EasyRead 後端啟動逾時。", "EasyRead backend timed out while starting. ") + output.slice(-500)));
      stopBackend();
    }, 30000);

    startup.mark(app, "backend-spawn");
    backend = spawn(launch.command, launch.args, {
      cwd: launch.cwd,
      env,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    backend.stdout.on("data", (chunk) => {
      output = (output + chunk.toString()).slice(-65536);
      const match = output.match(/EasyRead\s+已启动：\s*(http:\/\/127\.0\.0\.1:\d+)/);
      if (match && !settled) { startup.mark(app, "backend-http-ready"); backendUrl = match[1]; finish(resolve, match[1]); }
    });
    backend.stderr.on("data", (chunk) => {
      output = (output + chunk.toString()).slice(-65536);
    });
    backend.once("error", (error) => finish(reject, error));
    backend.once("exit", (code, signal) => {
      if (!settled) finish(reject, new Error(say(`EasyRead 后端退出（code=${code}, signal=${signal}）。`, `EasyRead 後端結束（code=${code}, signal=${signal}）。`, `EasyRead backend exited (code=${code}, signal=${signal}). `) + output.slice(-500)));
      backend = undefined;
      backendReady = undefined;
      backendUrl = undefined;
    });
  });
  })();
  backendReady.catch(() => { backendReady = undefined; });
  return backendReady;
}

function backendJson(endpoint, token) {
  return new Promise((resolve, reject) => {
    const req = http.request(new URL(endpoint, backendUrl), {
      method: token ? "POST" : "GET",
      headers: token ? { "X-Token": token, "Content-Type": "application/json", "Content-Length": 2 } : {},
    }, res => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", part => { body += part; });
      res.on("end", () => {
        try {
          const data = JSON.parse(body);
          if (res.statusCode !== 200) return reject(new Error(data.error || `HTTP ${res.statusCode}`));
          resolve(data);
        } catch (error) { reject(error); }
      });
    });
    req.setTimeout(8000, () => req.destroy(new Error(say("后端关闭超时，请稍后重试", "後端關閉逾時，請稍後重試", "Backend shutdown timed out. Try again later."))));
    req.on("error", reject);
    req.end(token ? "{}" : undefined);
  });
}

// 寫入令牌只放在頁面 HTML 的 <meta name="easyread-token">，JSON 接口不再回傳。
function backendToken() {
  return new Promise((resolve, reject) => {
    const req = http.request(new URL("/", backendUrl), { method: "GET" }, res => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", part => { body += part; });
      res.on("end", () => {
        const m = /<meta name="easyread-token" content="([0-9a-f]+)">/.exec(body);
        if (res.statusCode !== 200 || !m) return reject(new Error(`HTTP ${res.statusCode}`));
        resolve(m[1]);
      });
    });
    req.setTimeout(8000, () => req.destroy(new Error(say("读取后端令牌超时，请稍后重试", "讀取後端令牌逾時，請稍後重試", "Timed out reading the backend token. Try again later."))));
    req.on("error", reject);
    req.end();
  });
}

async function stopBackendGracefully() {
  const child = backend;
  if (!child) return;
  await backendJson("/api/shutdown", await backendToken());
  // 后端清掉占用标记、关闭 HTTP 服务后才启动新进程。
  if (backend !== child) return;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { child.removeListener("exit", exited); reject(new Error(say("后端尚未退出，请稍后重试", "後端尚未結束，請稍後重試", "The backend has not exited yet. Try again later."))); }, 8000);
    function exited() { clearTimeout(timer); resolve(); }
    child.once("exit", exited);
  });
}

/* 退出前先让页面把没落盘的东西写回去再停后端；页面没应就照常退出 */
function savePageState() {
  const wc = mainWindow && mainWindow.webContents;
  if (!wc || wc.isDestroyed()) return Promise.resolve();
  return new Promise(resolve => {
    let timer;
    function done() {
      clearTimeout(timer);
      ipcMain.removeListener("easyread:page-saved", saved);
      resolve();
    }
    function saved(event) {
      if (event.sender === wc && event.senderFrame === wc.mainFrame) done();
    }
    timer = setTimeout(done, 1200);
    ipcMain.on("easyread:page-saved", saved);
    wc.send("easyread:before-quit");
  });
}

function trustedWindow(event) {
  if (!mainWindow || event.sender !== mainWindow.webContents || event.senderFrame !== mainWindow.webContents.mainFrame ||
      !backendUrl || new URL(event.senderFrame.url).origin !== backendUrl) {
    throw new Error("Untrusted IPC sender");
  }
}

ipcMain.handle("easyread:pick-folder", async event => {
  trustedWindow(event);
  const result = await dialog.showOpenDialog(mainWindow, { properties: ["openDirectory", "createDirectory"] });
  return result.canceled ? null : result.filePaths[0] || null;
});
// 成批匯入用：選完資料夾，主程序拿桌面祕密向後端換一次性授權；頁面拿不到祕密，只拿到這次的 nonce
function backendGrant(folder, token) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ path: folder });
    const req = http.request(new URL("/api/pick/grant", backendUrl), {
      method: "POST",
      headers: { "X-Token": token, "X-Desktop-Secret": desktopSecret, "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
    }, res => {
      let text = "";
      res.setEncoding("utf8");
      res.on("data", part => { text += part; });
      res.on("end", () => {
        try {
          const data = JSON.parse(text);
          if (res.statusCode !== 200) return reject(new Error(data.error || `HTTP ${res.statusCode}`));
          resolve(data.nonce);
        } catch (error) { reject(error); }
      });
    });
    req.setTimeout(8000, () => req.destroy(new Error("grant timeout")));
    req.on("error", reject);
    req.end(body);
  });
}
ipcMain.handle("easyread:pick-folder-granted", async event => {
  trustedWindow(event);
  const result = await dialog.showOpenDialog(mainWindow, { properties: ["openDirectory"] });
  const folder = result.canceled ? null : result.filePaths[0] || null;
  if (!folder) return null;
  return { path: folder, nonce: await backendGrant(folder, await backendToken()) };
});
ipcMain.handle("easyread:relaunch", async event => {
  trustedWindow(event);
  await stopBackendGracefully();
  app.relaunch();
  app.exit(0);
});

function stopBackend() {
  backendReady = undefined;
  if (backend && !backend.killed) {
    if (process.platform === "win32") {
      // PyInstaller's one-file launcher creates a child process. Killing only
      // the launcher would leave the local HTTP service running after exit.
      try {
        execFileSync("taskkill", ["/pid", String(backend.pid), "/t", "/f"], {
          windowsHide: true,
          stdio: "ignore",
        });
      } catch (_) {
        // The process may already have exited while the window was closing.
      }
    } else {
      backend.kill();
    }
    backend = undefined;
  }
}

// 窗口还在启动时先记下，后端就绪后 createWindow 直接打开这篇
function openLink(target) {
  if (!target) return;
  if (!mainWindow || windowOpening || !backendUrl) {
    pendingOpen = target;
    if (!mainWindow && app.isReady()) createWindow();
    return;
  }
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
  mainWindow.loadURL(new URL(target, backendUrl).href);
}

async function createWindow() {
  if (windowOpening || mainWindow) return;
  windowOpening = true;
  const state = windowState.options();
  mainWindow = new BrowserWindow({
    ...state.opts,
    minWidth: 960,
    minHeight: 680,
    icon: path.join(__dirname, "assets", "icon.ico"),
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    if (/^https?:/i.test(target)) shell.openExternal(target);
    return { action: "deny" };
  });
  // A native context menu is separate from the application Edit menu.
  // Electron does not emit this event when the page prevents contextmenu,
  // so the library's and reader's custom menus keep working.
  mainWindow.webContents.on("context-menu", (_event, params) => {
    const flags = params.editFlags || {};
    const items = params.isEditable
      ? [{ role: "undo", enabled: flags.canUndo }, { role: "redo", enabled: flags.canRedo },
         { type: "separator" }, { role: "cut", enabled: flags.canCut }, { role: "copy", enabled: flags.canCopy },
         { role: "paste", enabled: flags.canPaste }, { type: "separator" }, { role: "selectAll" }]
      : params.selectionText.trim() ? [{ role: "copy" }] : [];
    if (items.length) Menu.buildFromTemplate(items).popup({ window: mainWindow });
  });
  windowState.track(mainWindow);
  const openingWindow = mainWindow;
  mainWindow.once("ready-to-show", () => {
    if (mainWindow !== openingWindow) return;
    if (state.maximized) openingWindow.maximize();
    openingWindow.show();
  });
  mainWindow.on("close", event => {
    if (process.platform !== "darwin" && !quitting && backend) {
      event.preventDefault();
      app.quit();  // before-quit saves while the renderer is still alive.
    }
  });
  mainWindow.on("closed", () => { mainWindow = undefined; });
  try {
    await openingWindow.loadURL(startup.loadingUrl(isZhTW() ? "zh-TW" : isZh()));
    if (mainWindow !== openingWindow || quitting) return;
    if (state.maximized) openingWindow.maximize();
    openingWindow.show();
    startup.mark(app, "startup-window-visible");
    const url = await startBackend();
    if (mainWindow !== openingWindow || quitting) return;
    const first = pendingOpen ? new URL(pendingOpen, url).href : url;
    pendingOpen = undefined;
    await openingWindow.loadURL(first);
    startup.mark(app, "library-loaded");
  } catch (error) {
    if (mainWindow !== openingWindow || quitting) return;
    startup.mark(app, "startup-failed");
    dialog.showErrorBox(say("EasyRead 启动失败", "EasyRead 啟動失敗", "EasyRead failed to start"), error.message);
    app.quit();
  } finally {
    windowOpening = false;
    // 加载文献库期间又点了 easyread:// 链接，openLink 只记下了它，这里补开
    if (pendingOpen && mainWindow === openingWindow && !quitting) openLink(pendingOpen);
  }
}

// Keep the web application's own header at the top of the content area. The
// default Electron File/Edit/View/Window strip would otherwise create a second
// toolbar row above it. The macOS menu is at the top of the screen and
// its Edit roles provide Cmd+C/V/X/A/Z.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  Menu.setApplicationMenu(process.platform === "darwin"
    ? Menu.buildFromTemplate([{ role: "appMenu" }, { role: "editMenu" }, { role: "windowMenu" }])
    : null);
  // macOS 用 open-url 传链接，可能早于 ready
  app.on("open-url", (event, link) => {
    event.preventDefault();
    openLink(deepLink.openPath(link));
  });
  app.whenReady().then(() => {
    deepLink.register(app, process);
    registerUpdates({
      app, ipcMain, updater: require("electron-updater").autoUpdater, trustedWindow,
      getWindow: () => mainWindow,
      prepareInstall: stopBackendGracefully,
      recover: async () => {
        if (backend) return;  // 后端没停（正在翻译、拒绝关闭）：页面别刷新，弹窗留着显示原因
        const url = await startBackend();
        if (mainWindow) await mainWindow.loadURL(url);
      },
    });
    return createWindow();
  });
  app.on("before-quit", event => {
    if (quitting) return;
    quitting = true;
    if (!backend) return;
    event.preventDefault();
    savePageState().then(stopBackendGracefully).catch(stopBackend).finally(() => app.quit());
  });
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
  app.on("second-instance", (_event, argv) => {
    const target = deepLink.fromArgv(argv);
    if (target) return void openLink(target);
    if (!mainWindow) return void createWindow();
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
  process.on("exit", stopBackend);
}
