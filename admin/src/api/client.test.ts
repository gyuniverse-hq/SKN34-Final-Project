import { afterEach, describe, expect, it, vi } from "vitest";
import { api, apiForm } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("관리자 API 응답", () => {
  it("연결 실패에 공통 오류 코드를 반환한다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api("/orders")).rejects.toMatchObject({
      status: 0,
      code: "network_error",
    });
  });

  it("JSON이 아닌 서버 오류의 HTTP 상태를 보존한다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Internal Server Error", { status: 500 })));
    await expect(api("/orders")).rejects.toMatchObject({
      status: 500,
      code: "api_error",
    });
  });

  it("조회 요청과 업로드에 JSON 요청 헤더를 추가하지 않는다", async () => {
    const request = vi.fn<(url: string, init: RequestInit) => Promise<Response>>()
      .mockImplementation(() => Promise.resolve(Response.json({ ok: true })));
    vi.stubGlobal("fetch", request);
    await api("/orders");
    await apiForm("/lip-triad-eval", new FormData());
    for (const [url, init] of request.mock.calls) {
      expect(url).toContain("/api/admin/");
      expect(new Headers(init.headers).has("Content-Type")).toBe(false);
    }
  });
});
