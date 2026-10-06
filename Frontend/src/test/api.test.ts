import { afterEach, describe, expect, it, vi } from "vitest";
import {
  API_URL,
  ApiError,
  askQuestion,
  messageFromBody,
  resolveAssetUrl,
  waitUntilReady,
} from "@/lib/api";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

describe("messageFromBody", () => {
  it("prefers the server's detail string", () => {
    expect(messageFromBody({ detail: "File too large (max 25MB)." }, "fallback")).toBe("File too large (max 25MB).");
  });
  it("reads the first FastAPI validation error", () => {
    expect(messageFromBody({ detail: [{ msg: "String too long" }] }, "fallback")).toBe("String too long");
  });
  it("falls back when there is no usable detail", () => {
    expect(messageFromBody(null, "fallback")).toBe("fallback");
    expect(messageFromBody({ detail: [] }, "fallback")).toBe("fallback");
  });
});

describe("resolveAssetUrl", () => {
  it("resolves backend-relative paths against the configured API origin", () => {
    expect(resolveAssetUrl("/extracted/abc/figure1_page2.png")).toBe(`${API_URL}/extracted/abc/figure1_page2.png`);
  });
  it("leaves absolute URLs and empty values alone", () => {
    expect(resolveAssetUrl("https://cdn.example/x.png")).toBe("https://cdn.example/x.png");
    expect(resolveAssetUrl(undefined)).toBeUndefined();
    expect(resolveAssetUrl(null)).toBeUndefined();
  });
});

describe("askQuestion", () => {
  it("sends query, doc id and history", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ answer: "hi", citations: [], supporting_visuals: [], doc_id: "d" }));
    vi.stubGlobal("fetch", fetchMock);

    await askQuestion("why?", "d".repeat(32), [{ role: "user", content: "earlier" }]);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_URL}/ask`);
    expect(JSON.parse(init.body)).toEqual({
      query: "why?",
      doc_id: "d".repeat(32),
      history: [{ role: "user", content: "earlier" }],
    });
  });

  it("surfaces the backend's error detail instead of a generic message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "Document is still being processed." }, 409)));
    await expect(askQuestion("q", "d")).rejects.toMatchObject({
      message: "Document is still being processed.",
      status: 409,
    });
  });

  it("gives a friendly message on rate limiting", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "Too many requests." }, 429)));
    await expect(askQuestion("q", "d")).rejects.toThrow(/wait a moment/i);
  });

  it("reports an unreachable backend clearly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(askQuestion("q", "d")).rejects.toThrow(/cannot reach the server/i);
  });
});

describe("waitUntilReady", () => {
  const status = (s: string, extra = {}) => json({ doc_id: "d", status: s, ...extra });

  it("polls through the stages until the document is ready", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(status("processing", { stage: "parsing" }))
      .mockResolvedValueOnce(status("processing", { stage: "indexing" }))
      .mockResolvedValueOnce(status("ready", { stage: "complete", blocks: 12 }));
    vi.stubGlobal("fetch", fetchMock);

    const stages: string[] = [];
    const result = await waitUntilReady("d", (s) => stages.push(s), { intervalMs: 1 });

    expect(stages).toEqual(["parsing", "indexing", "complete"]);
    expect(result.blocks).toBe(12);
  });

  it("rejects with the backend's message when processing fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(status("failed", { stage: "failed", error: "Scanned PDFs need OCR." })),
    );
    await expect(waitUntilReady("d", undefined, { intervalMs: 1 })).rejects.toThrow("Scanned PDFs need OCR.");
  });

  it("gives up after the timeout", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => status("processing", { stage: "parsing" })));
    await expect(waitUntilReady("d", undefined, { intervalMs: 1, timeoutMs: 5 })).rejects.toBeInstanceOf(ApiError);
  });

  it("stops polling when aborted", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => status("processing", { stage: "parsing" })));
    const controller = new AbortController();
    const pending = waitUntilReady("d", undefined, { intervalMs: 50, signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});
