const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const NAME = "0123456789abcdef0123456789abcdef.png";

function markup(extra = {}) {
  const PR = { t: (s) => s, esc: (text) => String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"), ...extra };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/common/markup.js"), "utf8"), {
    window: { PR }, katex: { renderToString: (tex) => "<math>" + PR.esc(tex) + "</math>" },
  });
  return PR;
}
const imgTags = (html) => html.match(/<img\b[^>]*>/g) || [];

test("strict relative note image renders as lazy <img>", () => {
  const PR = markup();
  const html = PR.md(`看图 ![图一](note-images/${NAME}) 结束`);
  assert.deepEqual(imgTags(html), [`<img class="note-img" loading="lazy" alt="图一" src="note-images/${NAME}">`]);
  assert.ok(PR.mdBlocks(`第一段\n\n![](note-images/${NAME})`).includes('loading="lazy"'));
  for (const ext of ["jpg", "webp", "gif"]) assert.equal(imgTags(PR.md(`![](note-images/${NAME.replace("png", ext)})`)).length, 1);
});

test("src comes from PR.noteImageSrc; empty result means plain text, never an image", () => {
  const ok = markup({ noteImageSrc: (n) => "/p/abc/note-images/" + n });
  assert.ok(ok.md(`![](note-images/${NAME})`).includes(`src="/p/abc/note-images/${NAME}"`));
  const none = markup({ noteImageSrc: () => "" });
  const html = none.md(`![](note-images/${NAME})`);
  assert.equal(imgTags(html).length, 0);
  assert.ok(html.includes("note-images/"));
});

test("hostile src is escaped even if the hook returned something odd", () => {
  const PR = markup({ noteImageSrc: () => 'x" onerror="alert(1)' });
  const html = PR.md(`![](note-images/${NAME})`);
  assert.equal(imgTags(html).length, 1);
  assert.ok(!/ onerror=/.test(html.replace(/&quot;/g, "")) || html.includes("&quot; onerror=&quot;"));
  assert.ok(!html.includes('" onerror='));
});

test("external, javascript:, traversal and malformed forms are never images", () => {
  const PR = markup();
  const bad = [
    "![](http://evil/x.png)", "![](https://evil/x.png)", "![x](//evil/x.png)", "![](javascript:alert(1))", "![](data:image/png;base64,AAAA)",
    "![](note-images/../../x)", "![](note-images/../" + NAME + ")", "![](note-images/" + NAME + "/../x.png)", "![](/note-images/" + NAME + ")",
    "![](./note-images/" + NAME + ")", "![](note-images/" + NAME.toUpperCase() + ")", "![](note-images/abc.png)", "![](note-images/" + NAME.replace("png", "svg") + ")",
    "![](note-images/" + NAME + "?x=1)", "![](note-images/" + NAME + " \"t\")", "![](note-images\\" + NAME + ")", "![](note-images/%2e%2e/x.png)",
    "![](note-images/" + NAME.replace("png", "html") + ")", "<img src=x onerror=alert(1)>", '<img src="note-images/' + NAME + '">',
  ];
  for (const text of bad) {
    for (const html of [PR.md(text), PR.mdBlocks(text), PR.md(`| a |\n|---|\n| ${text} |`)]) {
      assert.equal(imgTags(html).length, 0, text + " -> " + html);
      assert.ok(!/<(script|iframe|svg)\b/i.test(html), text);
      assert.ok(!/\sonerror=/i.test(html.replace(/&lt;[^]*?&gt;/g, "")), text + " -> " + html);
    }
  }
});

test("alt text with quotes or markup cannot break out of the attribute", () => {
  const PR = markup();
  for (const alt of ['" onerror="alert(1)', '"onerror=alert(1) x="', "<script>alert(1)</script>", "'><img src=x onerror=alert(1)>", "**b** *i* [1] 图 1"]) {
    const html = PR.md(`![${alt}](note-images/${NAME})`);
    const tags = imgTags(html);
    assert.equal(tags.length, 1, alt + " -> " + html);
    const names = [...tags[0].matchAll(/\s([a-z-]+)="[^"]*"/g)].map((m) => m[1]);
    assert.deepEqual(names, ["class", "loading", "alt", "src"], alt + " -> " + tags[0]);  // 引号配对完整、没有多出来的属性（onerror 等）
    assert.equal(tags[0].replace(/\s[a-z-]+="[^"]*"/g, ""), "<img>", tags[0]);
    assert.ok(!/<(?!img\b)[a-z]/i.test(tags[0].slice(1)), tags[0]);
  }
});

test("image inside code spans stays literal; plain() drops image markup", () => {
  const PR = markup();
  assert.equal(imgTags(PR.md("`![](note-images/" + NAME + ")`")).length, 0);
  assert.equal(PR.plain(`标题 ![](note-images/${NAME}) 尾`), "标题  尾");
});

test("a stray private-use placeholder typed by the user does not print undefined", () => {
  const PR = markup();
  assert.ok(!PR.md("0 x").includes("undefined"));
});
