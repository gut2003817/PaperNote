import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { HealthLight } from "./HealthLight";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it.each([
  ["未登入", "在終端機執行 codex login"],
  ["找不到 codex CLI", "安裝 codex 並確認在 PATH 上"],
])("直接顯示 %s 的修復方式", async (detail, fix) => {
  vi.spyOn(api, "health").mockResolvedValue({
    claude: { ok: true, detail: "已登入" },
    codex: { ok: false, detail, fix },
  });
  render(<HealthLight />);
  const status = await screen.findByTitle(`${detail}；修復：${fix}`);
  expect(status.textContent).toContain(fix);
  expect(status.textContent).toContain(detail);
  expect(screen.getByText("Claude").textContent).toBe("Claude");
});
