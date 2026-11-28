/**
 * aiAssistant.test.js
 * 助手 API 送出的內容：對話、語言與眼前的畫面；以及畫面清單的快取與路徑對照。
 */

import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("./api", () => ({ apiGet: vi.fn(), apiPostEventStream: vi.fn() }));

import { apiGet, apiPostEventStream } from "./api";
import {
  AI_ASSISTANT_TIMEOUT_MS,
  AiAssistantService,
  assistantLocale,
  matchSurface,
  normalizeAssistantMessages,
} from "./aiAssistant";

/* 假的串流：依序把事件交給 onEvent，然後結束 */
function streamOnce(...events) {
  apiPostEventStream.mockImplementationOnce(async (_path, _body, { onEvent }) => {
    for (const [event, data] of events) onEvent({ event, data });
  });
}

const answered = (reply = {}) => streamOnce(["final", reply]);

beforeEach(() => {
  apiGet.mockReset();
  apiPostEventStream.mockReset();
  AiAssistantService.resetSurfaces();
});

const sent = () => apiPostEventStream.mock.calls[0];

describe("AiAssistantService.chat", () => {
  test("對話、語言與畫面一起送到單一端點，並放寬逾時", async () => {
    answered({ reply: "ok" });

    const result = await AiAssistantService.chat({
      messages: [
        { role: "user", content: "我要申請一台機器" },
        { role: "assistant", content: "先去填申請單" },
        { role: "user", content: "然後呢？" },
      ],
      locale: "ja",
      screen: {
        path: "/class-setup?classId=42&step=3",
        surfaceId: "class-setup",
        state: { "classsetup.current_step": { value: "3. 教學環境" } },
        guideSteps: [{ id: 2, title: "班級與課表" }],
      },
    });

    const [url, body, options] = sent();
    expect(url).toBe("/api/v1/ai/assistant/chat");
    expect(body).toEqual({
      messages: [
        { role: "user", content: "我要申請一台機器" },
        { role: "assistant", content: "先去填申請單" },
        { role: "user", content: "然後呢？" },
      ],
      locale: "ja",
      screen: {
        path: "/class-setup?classId=42&step=3",
        surface_id: "class-setup",
        active_target: null,
        state: { "classsetup.current_step": { value: "3. 教學環境" } },
        guide_steps: [{ id: "2", title: "班級與課表" }],
      },
    });
    expect(options).toEqual({ timeoutMs: AI_ASSISTANT_TIMEOUT_MS, onEvent: expect.any(Function) });
    expect(result).toEqual({ reply: "ok" });
  });

  test("過程中的事件轉給 onEvent，最後回傳的是 final 那一份", async () => {
    const final = { request_id: "r1", reply: "到「帳號設定」改。", pages: [] };
    streamOnce(
      ["delta", { text: "讓我查" }],
      ["status", { tool: "read_help" }],
      ["reset", {}],
      ["delta", { text: "到「帳號設定」" }],
      ["delta", { text: "改。" }],
      ["final", final],
    );
    const seen = [];

    const result = await AiAssistantService.chat({
      messages: [{ role: "user", content: "怎麼改密碼" }],
      onEvent: (event) => seen.push(event),
    });

    expect(result).toBe(final);
    expect(seen).toEqual([
      { type: "delta", text: "讓我查" },
      { type: "status", tool: "read_help" },
      { type: "reset" },
      { type: "delta", text: "到「帳號設定」" },
      { type: "delta", text: "改。" },
    ]);
  });

  test("不認得的事件直接略過，沒給 onEvent 也能用", async () => {
    streamOnce(["delta", { text: "a" }], ["heartbeat", {}], ["final", { reply: "a" }]);
    await expect(AiAssistantService.chat({ messages: [{ role: "user", content: "嗨" }] })).resolves.toEqual({ reply: "a" });
  });

  test("伺服器中途出錯或連線提早結束（沒有 final）算失敗，不拿半截的字當回答", async () => {
    streamOnce(["delta", { text: "寫到一半" }], ["error", {}]);
    await expect(AiAssistantService.chat({ messages: [{ role: "user", content: "嗨" }] })).rejects.toMatchObject({ status: 502 });

    streamOnce(["delta", { text: "寫到一半" }]);
    await expect(AiAssistantService.chat({ messages: [{ role: "user", content: "嗨" }] })).rejects.toMatchObject({ status: 502 });
  });

  test("請求本身失敗時原樣往外丟（逾時、太頻繁）", async () => {
    apiPostEventStream.mockRejectedValueOnce({ status: 429, message: "太頻繁" });
    await expect(AiAssistantService.chat({ messages: [{ role: "user", content: "嗨" }] })).rejects.toEqual({ status: 429, message: "太頻繁" });
  });

  test("沒有畫面資訊時也能單獨呼叫", async () => {
    answered();
    await AiAssistantService.chat({ messages: [{ role: "user", content: "哈囉" }] });
    expect(sent()[1]).toEqual({
      messages: [{ role: "user", content: "哈囉" }],
      locale: "zh-TW",
      screen: { path: "/", surface_id: null, active_target: null, state: {}, guide_steps: [] },
    });
  });

  test("欄位狀態轉成後端收得下的型別：數字變字串、空值不送、過長截斷", async () => {
    answered();
    await AiAssistantService.chat({
      messages: [{ role: "user", content: "為什麼不能送？" }],
      screen: {
        path: "/my-requests",
        surfaceId: "request-form",
        activeTarget: "request.hostname",
        state: {
          "request.cores": { value: 4 },
          "request.hostname": { value: "", error: "必填".repeat(200) },
          "request.submit": { disabled: false, disabled_reason: null },
          "request.gpu": null,
        },
      },
    });
    const { screen } = sent()[1];
    expect(screen.active_target).toBe("request.hostname");
    expect(screen.state["request.cores"]).toEqual({ value: "4" });
    expect(screen.state["request.hostname"].value).toBeUndefined();
    expect(screen.state["request.hostname"].error).toHaveLength(300);
    expect(screen.state["request.submit"]).toEqual({ disabled: false });
    expect(screen.state["request.gpu"]).toEqual({});
  });

  test("路徑與指得到的步驟都有上限", async () => {
    answered();
    await AiAssistantService.chat({
      messages: [{ role: "user", content: "這裡是哪裡" }],
      screen: {
        path: `/${"a".repeat(500)}`,
        guideSteps: Array.from({ length: 30 }, (_, index) => ({ id: String(index), title: `步驟 ${index}` })),
      },
    });
    const { screen } = sent()[1];
    expect(screen.path).toHaveLength(300);
    expect(screen.guide_steps).toHaveLength(20);
  });
});

describe("normalizeAssistantMessages", () => {
  test("只留最近 24 則，而且從使用者的訊息開始", () => {
    const history = Array.from({ length: 41 }, (_, index) => ({
      role: index % 2 === 0 ? "user" : "assistant",
      content: `第 ${index} 則`,
    }));
    const result = normalizeAssistantMessages(history);
    // 最近 24 則是第 17～40 則；第 17 則是助手的，開頭要是使用者，所以從第 18 則起
    expect(result).toHaveLength(23);
    expect(result[0]).toEqual({ role: "user", content: "第 18 則" });
    expect(result.at(-1)).toEqual({ role: "user", content: "第 40 則" });
  });

  test("丟掉不是對話的項目與空訊息，並截斷過長內容", () => {
    const result = normalizeAssistantMessages([
      { role: "system", content: "不該被送出" },
      { role: "assistant", content: "開頭的助手訊息也不送" },
      { role: "user", content: "   " },
      { role: "user", content: "x".repeat(5000) },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].content).toHaveLength(4000);
  });

  test("相連的同角色訊息併成一則（上一輪失敗、沒有回覆時會連著兩則 user）", () => {
    expect(normalizeAssistantMessages([
      { role: "user", content: "我要申請機器" },
      { role: "user", content: "再試一次" },
    ])).toEqual([{ role: "user", content: "我要申請機器\n\n再試一次" }]);
  });

  test("最後一則不是使用者的訊息就沒有東西可問", () => {
    expect(normalizeAssistantMessages([
      { role: "user", content: "嗨" },
      { role: "assistant", content: "你好" },
    ])).toEqual([]);
    expect(normalizeAssistantMessages(undefined)).toEqual([]);
  });
});

describe("assistantLocale", () => {
  test("三種支援的語言原樣送出，地區變體取語言，其餘用繁中", () => {
    expect(assistantLocale("zh-TW")).toBe("zh-TW");
    expect(assistantLocale("en")).toBe("en");
    expect(assistantLocale("en-US")).toBe("en");
    expect(assistantLocale("ja-JP")).toBe("ja");
    expect(assistantLocale("zh-Hant")).toBe("zh-TW");
    expect(assistantLocale("fr")).toBe("zh-TW");
    expect(assistantLocale(undefined)).toBe("zh-TW");
  });
});

describe("surfaces 快取", () => {
  test("同一個身分只載一次，resetSurfaces 之後會重新向後端要", async () => {
    apiGet.mockResolvedValueOnce([{ id: "teacher-only" }]);
    apiGet.mockResolvedValueOnce([{ id: "student-only" }]);

    expect(await AiAssistantService.surfaces()).toEqual([{ id: "teacher-only" }]);
    expect(await AiAssistantService.surfaces()).toEqual([{ id: "teacher-only" }]);
    expect(apiGet).toHaveBeenCalledTimes(1);
    expect(apiGet).toHaveBeenCalledWith("/api/v1/ai/assistant/surfaces");

    AiAssistantService.resetSurfaces();
    expect(await AiAssistantService.surfaces()).toEqual([{ id: "student-only" }]);
    expect(apiGet).toHaveBeenCalledTimes(2);
  });

  test("載入失敗不會把錯誤快取住", async () => {
    apiGet.mockRejectedValueOnce(new Error("offline"));
    apiGet.mockResolvedValueOnce([{ id: "dashboard" }]);
    await expect(AiAssistantService.surfaces()).rejects.toThrow("offline");
    expect(await AiAssistantService.surfaces()).toEqual([{ id: "dashboard" }]);
  });
});

const SURFACES = [
  { id: "my-requests", path: "/my-requests", title: "我的申請" },
  { id: "request-form", path: "/my-requests", title: "申請虛擬機 / 容器" },
  { id: "my-resources", path: "/my-resources", title: "我的資源" },
  { id: "resource-detail", path: "/my-resources/:vmid", title: "資源詳細" },
];

describe("matchSurface", () => {
  test("完全相同的路徑優先", () => {
    expect(matchSurface(SURFACES, "/my-resources").id).toBe("my-resources");
  });

  test("帶參數的路徑靠樣板比對", () => {
    expect(matchSurface(SURFACES, "/my-resources/108").id).toBe("resource-detail");
  });

  test("忽略查詢字串與結尾斜線", () => {
    expect(matchSurface(SURFACES, "/my-resources/?tab=all").id).toBe("my-resources");
  });

  test("段數不同不算命中", () => {
    expect(matchSurface(SURFACES, "/my-resources/108/extra")).toBeNull();
  });

  test("沒有對應的畫面時回 null", () => {
    expect(matchSurface(SURFACES, "/settings")).toBeNull();
    expect(matchSurface([], "/my-requests")).toBeNull();
    expect(matchSurface(SURFACES, "")).toBeNull();
  });
});
