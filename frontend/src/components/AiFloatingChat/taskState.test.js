import { describe, expect, test } from "vitest";
import {
  applyStreamEvent,
  cardNote,
  chatErrorKey,
  environmentStepPath,
  historyForAssistant,
  intakeFactsPayload,
  isEnvironmentEditorPath,
  planErrorKey,
  planRequestMessages,
  recentMessages,
  streamStatusKey,
} from "./taskState";

describe("回答產生的過程", () => {
  test("delta 接在後面，reset 把字清掉，status 記下剛用完的工具", () => {
    const events = [
      { type: "delta", text: "讓我查" },
      { type: "status", tool: "read_help" },
      { type: "reset" },
      { type: "delta", text: "到「帳號設定」" },
      { type: "delta", text: "改。" },
    ];
    const states = [];
    events.reduce((state, event) => {
      const next = applyStreamEvent(state, event);
      states.push(next);
      return next;
    }, null);
    expect(states).toEqual([
      { text: "讓我查", tool: null },
      { text: "讓我查", tool: "read_help" },
      { text: "", tool: "read_help" },
      { text: "到「帳號設定」", tool: "read_help" },
      { text: "到「帳號設定」改。", tool: "read_help" },
    ]);
  });

  test("不認得的事件不改變狀態，也不會就地修改傳進來的物件", () => {
    const state = { text: "a", tool: null };
    expect(applyStreamEvent(state, { type: "final" })).toBe(state);
    expect(applyStreamEvent(state, undefined)).toBe(state);
    expect(applyStreamEvent(state, { type: "delta", text: "b" })).not.toBe(state);
    expect(state).toEqual({ text: "a", tool: null });
  });

  test("等待時那一行字：查說明與查申請各有說法，其他工具用通用的，還沒用工具就不說", () => {
    expect(streamStatusKey("read_help")).toBe("AiFloatingChat.statusReadHelp");
    expect(streamStatusKey("get_my_requests")).toBe("AiFloatingChat.statusMyRequests");
    expect(streamStatusKey("show_pages")).toBe("AiFloatingChat.statusWriting");
    expect(streamStatusKey(null)).toBeNull();
    expect(streamStatusKey(undefined)).toBeNull();
  });
});

describe("送給助手的歷史", () => {
  test("卡片用一行字記進歷史，追問「第二步是什麼」才有東西可指", () => {
    const flow = { title: "申請一台機器", steps: [{ title: "打開申請單" }, { title: "等待審核" }] };
    const pages = [{ title: "我的申請" }, { title: "我的資源" }];
    expect(cardNote({ flow, pages })).toBe("（已附上流程「申請一台機器」：打開申請單→等待審核；頁面按鈕：我的申請、我的資源）");
    expect(cardNote({ pages })).toBe("（已附上頁面按鈕：我的申請、我的資源）");
    expect(cardNote({})).toBe("");
    expect(cardNote()).toBe("");
  });

  test("本機產生的錯誤訊息不送給模型，卡片註記併進那一則的內容", () => {
    expect(historyForAssistant([
      { role: "user", content: "帶我去防火牆" },
      { role: "assistant", content: "在這裡", note: "（已附上頁面按鈕：防火牆）", pages: [{ title: "防火牆" }] },
      { role: "user", content: "再問一次" },
      { role: "assistant", content: "AI 目前無法回覆", omit: true },
    ])).toEqual([
      { role: "user", content: "帶我去防火牆" },
      { role: "assistant", content: "在這裡\n（已附上頁面按鈕：防火牆）" },
      { role: "user", content: "再問一次" },
    ]);
    expect(historyForAssistant(undefined)).toEqual([]);
  });
});

describe("送給規劃器的需求", () => {
  test("長對話只留最近的幾則", () => {
    const history = Array.from({ length: 60 }, (_, index) => ({ role: "user", content: `第 ${index} 則` }));
    const kept = recentMessages(history);
    expect(kept).toHaveLength(12);
    expect(kept.at(-1).content).toBe("第 59 則");
    const huge = [{ role: "user", content: "x".repeat(20_000) }, { role: "user", content: "最新" }];
    expect(recentMessages(huge).map((item) => item.content)).toEqual(["最新"]);
  });

  test("最新一則本身超長時截斷它，不整則送出", () => {
    const pasted = { role: "user", content: "y".repeat(50_000) };
    const kept = recentMessages([{ role: "user", content: "舊的" }, pasted]);
    expect(kept).toHaveLength(1);
    expect(kept[0].content).toHaveLength(12_000);
    expect(pasted.content).toHaveLength(50_000);
  });

  test("問到的需求以結構化欄位送出；一格都沒有就不送", () => {
    expect(intakeFactsPayload(null)).toBeNull();
    expect(intakeFactsPayload({ inferred: [] })).toBeNull();
    expect(intakeFactsPayload({ purpose: "AI 訓練", gpu: "不確定，你幫我判斷", inferred: ["gpu", "bogus"] })).toEqual({
      purpose: "AI 訓練", gpu: "不確定，你幫我判斷", display: null, duration: null, inferred: ["gpu"],
    });
  });

  test("需求再用文字寫一次放在最後，推斷的那幾格標成可調整", () => {
    const history = Array.from({ length: 20 }, () => ({ role: "assistant", content: "舊對話" }));
    history.push({ role: "user", content: "幾週" });
    const messages = planRequestMessages(history, {
      purpose: "Node.js 網站", gpu: "不需要 GPU", duration: "幾週", inferred: ["gpu"],
    });
    const last = messages.at(-1);
    expect(last.role).toBe("user");
    expect(last.content).toContain("用途（使用者已提供）：Node.js 網站");
    expect(last.content).toContain("加速需求（建議預設，可調整）：不需要 GPU");
    expect(last.content).toContain("使用時間（使用者已提供）：幾週");
    expect(last.content).not.toContain("作業環境");
    // 原本的對話只留最近 12 則，再加上這一則
    expect(messages).toHaveLength(13);
    expect(history).toHaveLength(21);
  });

  test("沒有需求可寫時只送對話", () => {
    const history = [{ role: "user", content: "直接產生配置" }];
    expect(planRequestMessages(history, {})).toEqual(history);
    expect(planRequestMessages(undefined, null)).toEqual([]);
  });

  test("整份規劃請求穩定低於後端的字數上限", () => {
    const facts = { purpose: "p".repeat(2_000), gpu: "q".repeat(2_000), display: "d".repeat(2_000), duration: "t".repeat(2_000), inferred: [] };
    const messages = planRequestMessages([{ role: "user", content: "z".repeat(100_000) }], facts);
    const total = messages.reduce((sum, item) => sum + item.content.length, 0);
    expect(total).toBeLessThan(32 * 1024);
  });
});

describe("失敗時的說法", () => {
  test("規劃失敗依原因告訴使用者能做什麼", () => {
    expect(planErrorKey({ status: 408, timeout: true })).toBe("AiFloatingChat.planTimedOut");
    expect(planErrorKey({ status: 429 })).toBe("AiFloatingChat.planRateLimited");
    expect(planErrorKey({ status: 400 })).toBe("AiFloatingChat.planTooLong");
    expect(planErrorKey({ status: 502 })).toBe("AiFloatingChat.planFailed");
  });

  test("回覆失敗同樣分逾時、太頻繁、對話太長與其他", () => {
    expect(chatErrorKey({ timeout: true })).toBe("AiFloatingChat.chatTimedOut");
    expect(chatErrorKey({ status: 408 })).toBe("AiFloatingChat.chatTimedOut");
    expect(chatErrorKey({ status: 429 })).toBe("AiFloatingChat.chatRateLimited");
    for (const status of [400, 413, 422]) {
      expect(chatErrorKey({ status })).toBe("AiFloatingChat.chatTooLong");
    }
    expect(chatErrorKey({ status: 503 })).toBe("AiFloatingChat.genericErrorFallback");
    expect(chatErrorKey(undefined)).toBe("AiFloatingChat.genericErrorFallback");
  });
});

describe("教學環境編輯頁的分頁網址", () => {
  test("步驟進到編輯頁，保留正在編輯的環境與返回班級的網址", () => {
    expect(environmentStepPath("/course-template-management", undefined, "basic")).toBe("/course-template-management/new?tab=basic");
    const path = "/course-template-management/env-42?returnTo=%2Fclass-setup%3FclassId%3D9%26step%3D3&tab=basic";
    const target = environmentStepPath(path, undefined, "machines");
    expect(target.split("?")[0]).toBe("/course-template-management/env-42");
    expect(new URLSearchParams(target.split("?")[1]).get("returnTo")).toBe("/class-setup?classId=9&step=3");
    expect(new URLSearchParams(target.split("?")[1]).get("tab")).toBe("machines");
    // 人已經離開編輯頁：回到先前待過的那個環境，不另開新的
    expect(environmentStepPath("/templates", target, "basic")).toContain("/course-template-management/env-42?");
    const fromClass = environmentStepPath("/class-setup?classId=9&step=3", undefined, "basic");
    expect(new URLSearchParams(fromClass.split("?")[1]).get("returnTo")).toBe("/class-setup?classId=9&step=3");
  });

  test("只有某個環境的編輯頁才算，清單頁不算", () => {
    expect(isEnvironmentEditorPath("/course-template-management/env-42")).toBe(true);
    expect(isEnvironmentEditorPath("/course-template-management/new?tab=basic")).toBe(true);
    expect(isEnvironmentEditorPath("/course-template-management")).toBe(false);
    expect(isEnvironmentEditorPath(undefined)).toBe(false);
  });
});
