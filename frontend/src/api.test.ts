import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("回傳 JSON", async () => {
    mockFetch(200, [{ slug: "a", title: "A", created: 1, has_note: true }]);
    expect((await api.papers())[0].slug).toBe("a");
  });

  it("字串 detail 變成錯誤訊息", async () => {
    mockFetch(409, { detail: "已有一個 AI 修改進行中" });
    await expect(api.chat("a")).rejects.toMatchObject({ message: "已有一個 AI 修改進行中", status: 409 });
  });

  it("502 的 {message, raw} detail 帶出 raw", async () => {
    mockFetch(502, { detail: { message: "AI 回傳格式錯誤", raw: "[{]" } });
    const err = await api
      .edit("a", { engine: "claude", message: "m", block_ids: ["x"], selected_text: "" })
      .catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("AI 回傳格式錯誤");
    expect(err.raw).toBe("[{]");
  });

  it("PUT note 送 JSON", async () => {
    const fn = mockFetch(200, { ok: true });
    await api.saveNote("a", { blocks: [] });
    expect(fn).toHaveBeenCalledWith("/api/papers/a/note", expect.objectContaining({ method: "PUT" }));
  });

  it("figureUrl 會編碼檔名", () => {
    expect(api.figureUrl("a", "p1-1.png")).toBe("/api/papers/a/figures/p1-1.png");
  });
});
