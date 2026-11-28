// @vitest-environment happy-dom
import { beforeEach, describe, expect, test, vi } from "vitest";
import {
  MAX_STORED_MESSAGES,
  clearAssistantChats,
  loadAssistantChat,
  saveAssistantChat,
} from "./assistantChatStorage";

beforeEach(() => {
  sessionStorage.clear();
});

const chat = (count) => Array.from({ length: count }, (_, index) => ({
  role: index % 2 === 0 ? "user" : "assistant",
  content: `第 ${index} 則`,
}));

describe("助手對話保存", () => {
  test("存進去再讀回來是同一段對話，卡片資料也在", () => {
    const messages = [
      { role: "user", content: "帶我去防火牆" },
      { role: "assistant", content: "在這裡", pages: [{ title: "防火牆", path: "/firewall" }] },
    ];
    saveAssistantChat("u1", { messages, planned: true });
    expect(loadAssistantChat("u1")).toEqual({ messages, planned: true });
  });

  test("只留最近 40 則", () => {
    saveAssistantChat("u1", { messages: chat(55) });
    const restored = loadAssistantChat("u1").messages;
    expect(restored).toHaveLength(MAX_STORED_MESSAGES);
    expect(restored[0].content).toBe("第 15 則");
  });

  test("每個帳號各自一份，讀不到別人的", () => {
    saveAssistantChat("u1", { messages: chat(2) });
    expect(loadAssistantChat("u2").messages).toEqual([]);
  });

  test("空對話不留空殼", () => {
    saveAssistantChat("u1", { messages: chat(2) });
    saveAssistantChat("u1", { messages: [] });
    expect(sessionStorage.length).toBe(0);
  });

  test("登出時整批清掉，不動其他 key", () => {
    saveAssistantChat("u1", { messages: chat(2) });
    saveAssistantChat("u2", { messages: chat(2) });
    sessionStorage.setItem("skylab:other", "keep");
    clearAssistantChats();
    expect(loadAssistantChat("u1").messages).toEqual([]);
    expect(loadAssistantChat("u2").messages).toEqual([]);
    expect(sessionStorage.getItem("skylab:other")).toBe("keep");
  });

  test("壞掉的內容、舊版格式或沒有使用者都當作沒有對話", () => {
    sessionStorage.setItem("skylab:ai-assistant:chat:u1", "{not json");
    expect(loadAssistantChat("u1")).toEqual({ messages: [], planned: false });
    sessionStorage.setItem("skylab:ai-assistant:chat:u1", JSON.stringify({ v: 0, messages: chat(2) }));
    expect(loadAssistantChat("u1").messages).toEqual([]);
    sessionStorage.setItem("skylab:ai-assistant:chat:u1", JSON.stringify({
      v: 1, messages: [{ role: "system", content: "x" }, { role: "user", content: 3 }, { role: "user", content: "好的" }],
    }));
    expect(loadAssistantChat("u1").messages).toEqual([{ role: "user", content: "好的" }]);
    expect(loadAssistantChat(undefined).messages).toEqual([]);
    // 沒有使用者 id 就不存：還是只有上面那一個 key
    saveAssistantChat(null, { messages: chat(2) });
    expect(sessionStorage.length).toBe(1);
  });

  test("儲存空間不可用時不丟錯", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
    expect(() => saveAssistantChat("u1", { messages: chat(2) })).not.toThrow();
    spy.mockRestore();
  });
});
