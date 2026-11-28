/**
 * eventStream.test.js
 * 讀 Server-Sent Events：事件的切分與解析、keep-alive、閒置逾時，以及走 api.js 的
 * 認證流程（apiPostEventStream）。
 */
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { AuthStorage } from "./auth";
import { apiPostEventStream } from "./api";
import { parseEventBlock, readEventStream } from "./eventStream";

const encoder = new TextEncoder();

/* 照給定的切法一段一段送出；最後一段送完就結束 */
function streamOf(...chunks) {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
      }
      controller.close();
    },
  });
}

const sseResponse = (...chunks) => ({ ok: true, status: 200, body: streamOf(...chunks) });

async function collect(response, options = {}) {
  const events = [];
  await readEventStream(response, { onEvent: (event) => events.push(event), ...options });
  return events;
}

describe("parseEventBlock", () => {
  test("讀出事件名稱與 JSON 內容；沒寫名稱的是 message", () => {
    expect(parseEventBlock('event: delta\ndata: {"text":"你好"}')).toEqual({ event: "delta", data: { text: "你好" } });
    expect(parseEventBlock("data: 42")).toEqual({ event: "message", data: 42 });
  });

  test("只有註解的區塊（keep-alive）不算事件", () => {
    expect(parseEventBlock(": ping")).toBeNull();
    expect(parseEventBlock("event: delta")).toBeNull();
  });

  test("多行 data 以換行相接；冒號後面只吃掉一個空白", () => {
    expect(parseEventBlock('data: {"a":\ndata: 1}')).toEqual({ event: "message", data: { a: 1 } });
    expect(parseEventBlock('data:"x"\r\nevent:status')).toEqual({ event: "status", data: "x" });
  });

  test("內容不是 JSON 就是壞掉的串流", () => {
    expect(() => parseEventBlock("data: {oops")).toThrow(expect.objectContaining({ status: 502 }));
  });
});

describe("readEventStream", () => {
  test("事件被切在任何位置都拼得回來，包括切在一個中文字中間", async () => {
    const bytes = encoder.encode('event: delta\ndata: {"text":"防火牆"}\n\nevent: final\ndata: {"reply":"好"}\n\n');
    const cut = bytes.indexOf(0xe7); // 「火」的第一個位元組
    const events = await collect(sseResponse(bytes.slice(0, cut + 1), bytes.slice(cut + 1, cut + 9), bytes.slice(cut + 9)));
    expect(events).toEqual([
      { event: "delta", data: { text: "防火牆" } },
      { event: "final", data: { reply: "好" } },
    ]);
  });

  test("keep-alive 與 CRLF 換行都不影響", async () => {
    const events = await collect(sseResponse(": ping\n\n", 'event: delta\r\ndata: {"text":"a"}\r\n\r\n', ": ping\n\n"));
    expect(events).toEqual([{ event: "delta", data: { text: "a" } }]);
  });

  test("最後一則沒收完就斷線，不交出半截的事件", async () => {
    const events = await collect(sseResponse('event: delta\ndata: {"text":"a"}\n\nevent: final\ndata: {"reply":'));
    expect(events).toEqual([{ event: "delta", data: { text: "a" } }]);
  });

  test("回應沒有內容串流時丟 502", async () => {
    await expect(collect({ ok: true, status: 200, body: null })).rejects.toMatchObject({ status: 502 });
  });

  test("beforeEvent 丟例外就停止，後面的事件不再交出去", async () => {
    const seen = [];
    const stop = { status: 409, sessionChanged: true };
    await expect(readEventStream(
      sseResponse('data: 1\n\ndata: 2\n\ndata: 3\n\n'),
      {
        onEvent: (event) => seen.push(event.data),
        beforeEvent: () => { if (seen.length === 1) throw stop; },
      },
    )).rejects.toBe(stop);
    expect(seen).toEqual([1]);
  });

  describe("閒置逾時", () => {
    beforeEach(() => { vi.useFakeTimers(); });
    afterEach(() => { vi.useRealTimers(); });

    test("超過時間完全沒有資料就當成斷線，丟 408", async () => {
      let cancelled = false;
      const body = new ReadableStream({
        start(controller) { controller.enqueue(encoder.encode('data: 1\n\n')); },
        cancel() { cancelled = true; },
      });
      const seen = [];
      const reading = readEventStream({ body }, { onEvent: (event) => seen.push(event.data), idleTimeoutMs: 1000 });
      const outcome = expect(reading).rejects.toMatchObject({ status: 408, timeout: true });
      await vi.advanceTimersByTimeAsync(1000);
      await outcome;
      expect(seen).toEqual([1]);
      expect(cancelled).toBe(true);
    });

    test("每收到一段資料（含 keep-alive）就重新計時", async () => {
      let push;
      const body = new ReadableStream({ start(controller) { push = (text) => (text === null ? controller.close() : controller.enqueue(encoder.encode(text))); } });
      const seen = [];
      const reading = readEventStream({ body }, { onEvent: (event) => seen.push(event.data), idleTimeoutMs: 1000 });
      for (const text of [": ping\n\n", ": ping\n\n", 'data: "done"\n\n']) {
        await vi.advanceTimersByTimeAsync(900);
        push(text);
      }
      await vi.advanceTimersByTimeAsync(900);
      push(null);
      await reading;
      expect(seen).toEqual(["done"]);
    });
  });
});

describe("apiPostEventStream", () => {
  let fetchMock;

  function fakeStorage() {
    const values = new Map();
    return {
      getItem: (key) => (values.has(key) ? values.get(key) : null),
      setItem: (key, value) => values.set(key, String(value)),
      removeItem: (key) => values.delete(key),
    };
  }

  beforeEach(() => {
    vi.stubGlobal("localStorage", fakeStorage());
    const target = new EventTarget();
    vi.stubGlobal("window", {
      addEventListener: (...args) => target.addEventListener(...args),
      removeEventListener: (...args) => target.removeEventListener(...args),
      dispatchEvent: (event) => target.dispatchEvent(event),
    });
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    AuthStorage.setTokens({ access_token: "token-a", refresh_token: "token-r" });
  });

  afterEach(() => { vi.unstubAllGlobals(); });

  test("帶著登入憑證 POST，事件逐則交給 onEvent", async () => {
    fetchMock.mockResolvedValueOnce(sseResponse('event: delta\ndata: {"text":"嗨"}\n\n', 'event: final\ndata: {"reply":"嗨"}\n\n'));
    const events = [];

    await apiPostEventStream("/api/v1/ai/assistant/chat", { q: 1 }, { onEvent: (event) => events.push(event), timeoutMs: 5000 });

    expect(events).toEqual([
      { event: "delta", data: { text: "嗨" } },
      { event: "final", data: { reply: "嗨" } },
    ]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/v1/ai/assistant/chat");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ q: 1 });
    expect(init.headers).toMatchObject({
      Accept: "text/event-stream",
      Authorization: "Bearer token-a",
      "Content-Type": "application/json",
    });
  });

  test("串流開始前的失敗照一般請求的格式丟出來", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 429, json: async () => ({ detail: "太頻繁" }), text: async () => "" });
    const onEvent = vi.fn();
    await expect(apiPostEventStream("/x", {}, { onEvent })).rejects.toMatchObject({ status: 429, message: "太頻繁" });
    expect(onEvent).not.toHaveBeenCalled();
  });

  test("401 先續期再重送一次，事件只來自重送的那一次", async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ access_token: "token-b", refresh_token: "token-r2" }) })
      .mockResolvedValueOnce(sseResponse('event: final\ndata: {"reply":"好"}\n\n'));
    const events = [];

    await apiPostEventStream("/x", {}, { onEvent: (event) => events.push(event) });

    expect(events).toEqual([{ event: "final", data: { reply: "好" } }]);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe("Bearer token-b");
  });

  test("讀到一半登出：剩下的事件不再處理，並丟出 session 已變更", async () => {
    fetchMock.mockResolvedValueOnce(sseResponse('data: 1\n\n', 'data: 2\n\n'));
    const seen = [];

    await expect(apiPostEventStream("/x", {}, {
      onEvent: (event) => {
        seen.push(event.data);
        AuthStorage.clearTokens();
      },
    })).rejects.toMatchObject({ status: 409, sessionChanged: true });
    expect(seen).toEqual([1]);
  });
});
