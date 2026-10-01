import { expect, test } from "@playwright/test";
import path from "node:path";

const SAMPLE = path.resolve(new URL("../..", import.meta.url).pathname, ".e2e/sample.pdf");

test("匯入 → 選取討論 → AI 改寫 → 復原 → 拖曳圖表 → 重新整理後版面保留", async ({ page }) => {
  const note = page.locator(".note-pane");
  await page.goto("/");
  await page.getByLabel("論文 PDF").setInputFiles(SAMPLE);
  await page.getByLabel("標題").fill("E2E 測試論文");
  await page.getByRole("button", { name: "開始整理" }).click();

  await expect(page).toHaveURL(/#\/paper\//, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "E2E 測試論文" })).toBeVisible();
  await expect(note.getByText("就像用假人練習急救。")).toBeVisible();
  await expect(page.getByRole("button", { name: "AI 抽取，待核對" })).toBeVisible();
  await expect(page.locator("img.figure-img")).toBeVisible();

  // 選取段落 → 送出 → 被取代
  await note.getByText("原始段落文字").click();
  await expect(page.locator(".chat-selection")).toContainText("原始段落文字");
  await page.getByPlaceholder(/例如/).fill("改白話");
  await page.getByRole("button", { name: /送出/ }).click();
  await expect(note.getByText("改寫後的段落")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('.chat-selection')).toContainText('改寫後的段落');
  await expect(note.getByText("原始段落文字")).toHaveCount(0);
  await expect(page.getByText("已改寫成白話")).toBeVisible();

  // 一次 undo 撤回整個 AI 修改
  await note.getByText("改寫後的段落").click();
  await page.keyboard.press("ControlOrMeta+z");
  await expect(note.getByText("原始段落文字")).toBeVisible();
  await expect(note.getByText("改寫後的段落")).toHaveCount(0);

  // 拖曳圖表右下角把寬度縮小
  const frame = page.locator(".frame").filter({ has: page.locator(".chart-canvas") }).first();
  await frame.hover();
  const before = (await frame.boundingBox())!;
  const handle = (await frame.locator(".frame-resize").boundingBox())!;
  await page.mouse.move(handle.x + 5, handle.y + 5);
  await page.mouse.down();
  await page.mouse.move(handle.x - 200, handle.y + 5, { steps: 10 });
  await page.mouse.up();
  const after = (await frame.boundingBox())!;
  expect(after.width).toBeLessThan(before.width - 150);

  // 等自動存檔後重新整理，寬度保留
  await page.waitForTimeout(1500);
  await page.reload();
  const reloaded = page.locator(".frame").filter({ has: page.locator(".chart-canvas") }).first();
  await expect(reloaded).toBeVisible();
  expect(Math.abs((await reloaded.boundingBox())!.width - after.width)).toBeLessThan(4);
  await expect(note.getByText("原始段落文字")).toBeVisible();
});
