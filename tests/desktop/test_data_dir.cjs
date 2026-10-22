const { test } = require("node:test");
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const dataDir = require("../../electron/data-dir.cjs");

const packaged = { isPackaged: true };

function sandbox() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "easyread-datadir-"));
  const home = path.join(root, "home");
  const install = path.join(root, "E", "EasyRead");
  fs.mkdirSync(install, { recursive: true });
  return { root, home, exe: path.join(install, "EasyRead.exe"), data: path.join(install, "data"), legacy: path.join(home, "EasyRead") };
}

function seedLegacy(s, cfg) {
  fs.mkdirSync(path.join(s.legacy, "library", "abc"), { recursive: true });
  fs.writeFileSync(path.join(s.legacy, "library", "abc", "paper.json"), '{"blocks":[]}');
  fs.writeFileSync(path.join(s.legacy, "config.json"), JSON.stringify(cfg));
}

test("fresh install keeps data next to the program", async () => {
  const s = sandbox();
  const dir = await dataDir.prepare(packaged, () => {}, { exe: s.exe, home: s.home, platform: "win32" });
  assert.strictEqual(dir, s.data);
  assert.ok(fs.existsSync(s.data));
  assert.ok(!fs.existsSync(s.legacy));
});

test("old ~/EasyRead data moves over and the library path follows", async () => {
  const s = sandbox();
  seedLegacy(s, { library_dir: path.join(s.legacy, "library"), engine: "claude" });
  const dir = await dataDir.prepare(packaged, () => {}, { exe: s.exe, home: s.home, platform: "win32" });
  assert.strictEqual(dir, s.data);
  assert.ok(fs.existsSync(path.join(s.data, "library", "abc", "paper.json")));
  const cfg = JSON.parse(fs.readFileSync(path.join(s.data, "config.json"), "utf8"));
  assert.strictEqual(cfg.library_dir, path.join(s.data, "library"));
  assert.strictEqual(cfg.engine, "claude");
  assert.ok(!fs.existsSync(s.legacy));
  assert.ok(!fs.existsSync(`${s.data}.migrating`));
});

test("a library kept elsewhere (cloud folder) is left alone", async () => {
  const s = sandbox();
  const cloud = path.join(s.root, "Dropbox", "papers");
  seedLegacy(s, { library_dir: cloud });
  await dataDir.prepare(packaged, () => {}, { exe: s.exe, home: s.home, platform: "win32" });
  const cfg = JSON.parse(fs.readFileSync(path.join(s.data, "config.json"), "utf8"));
  assert.strictEqual(cfg.library_dir, cloud);
});

test("existing data in the install folder wins; old folder is not touched", async () => {
  const s = sandbox();
  seedLegacy(s, { library_dir: path.join(s.legacy, "library") });
  fs.mkdirSync(s.data, { recursive: true });
  fs.writeFileSync(path.join(s.data, "config.json"), '{"engine":"codex"}');
  await dataDir.prepare(packaged, () => {}, { exe: s.exe, home: s.home, platform: "win32" });
  assert.strictEqual(JSON.parse(fs.readFileSync(path.join(s.data, "config.json"), "utf8")).engine, "codex");
  assert.ok(fs.existsSync(path.join(s.legacy, "config.json")));
});

test("source runs and other platforms keep the old behaviour", async () => {
  const s = sandbox();
  assert.strictEqual(await dataDir.prepare({ isPackaged: false }, () => {}, { exe: s.exe, home: s.home, platform: "win32" }), null);
  assert.strictEqual(await dataDir.prepare(packaged, () => {}, { exe: s.exe, home: s.home, platform: "darwin" }), null);
});
