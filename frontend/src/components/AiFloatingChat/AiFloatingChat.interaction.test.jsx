// @vitest-environment happy-dom
import { act, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import AiFloatingChat from "./AiFloatingChat";
import { LayoutContext } from "../../layout/layoutContext";
import { AiAssistantService } from "../../services/aiAssistant";
import { AiTemplateRecommendationApi } from "../../services/aiTemplateRecommendation";
import { executeGuideCommand, listGuideSteps, requestGuideOnArrival } from "../UserGuide/guideCommands";
import { getRouteGuide, USER_GUIDE_START_EVENT } from "../UserGuide/routeGuides";
import translations from "../../locales/zh-TW/components.json";

const i18n = vi.hoisted(() => ({ language: "zh-TW" }));

vi.mock("../../contexts/AuthContext", () => ({ useAuth: () => ({ user: { id: "student" } }) }));
vi.mock("react-i18next", async (importOriginal) => ({ ...(await importOriginal()), useTranslation: () => ({ t: translate, i18n }) }));
vi.mock("../../services/aiAssistant", async (importOriginal) => ({
  ...(await importOriginal()),
  AiAssistantService: { chat: vi.fn(), surfaces: vi.fn(), resetSurfaces: vi.fn() },
}));
vi.mock("../../services/aiTemplateRecommendation", () => ({ AiTemplateRecommendationApi: { recommend: vi.fn() } }));
vi.mock("../UserGuide/guideCommands", async (importOriginal) => ({
  ...(await importOriginal()),
  listGuideSteps: vi.fn(() => []),
  executeGuideCommand: vi.fn(() => true),
  requestGuideOnArrival: vi.fn(),
  clearArrivalCommand: vi.fn(),
}));
vi.mock("../OctoPet/OctoPet", () => ({ default: () => <span /> }));

function translate(key, vars) {
  return Object.entries(vars ?? {}).reduce((text, [name, value]) => text.replaceAll(`{{${name}}}`, value), translations[key] ?? key);
}

/* 有畫面說明、但前端沒有登錄導覽的路徑：頁面導覽按鈕在這裡只能替使用者發問 */
const NO_TOUR_PATH = "/page-without-a-tour";
const SURFACES = [
  { id: "my-resources", path: "/my-resources", title: "我的資源" },
  { id: "class-setup", path: "/class-setup", title: "建立班級" },
  { id: "no-tour", path: NO_TOUR_PATH, title: "沒有導覽的頁面" },
];
const prefill = { resource_type: "lxc", hostname: "nodejs-web", cores: 2, memory_mb: 2048, disk_gb: 20 };
const facts = { purpose: "Node.js 網站上線", gpu: "不需要 GPU", display: "Linux 指令列就好", duration: "2周", inferred: ["gpu", "display"] };
const applyPrefill = vi.fn();
let host, root, overlay;

/* 申請頁帶著 create 進來才有表單（跟真的頁面一樣）；/class-setup 會註冊自己的畫面狀態 */
function Harness({ onOpenChange }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [form, setForm] = useState(null);
  const [requestSubmission, reportRequestSubmission] = useState(null);
  useEffect(() => {
    if (location.pathname === "/my-requests" && location.state?.create) {
      setForm({ getContext: () => ({ hostname: "", resource_type: "lxc" }), applyPrefill });
    } else setForm(null);
  }, [location.pathname, location.state]);
  const surface = location.pathname === "/class-setup" ? {
    id: "class-setup", getState: () => ({ "classsetup.current_step": { value: "3. 教學環境" } }),
  } : null;
  return <LayoutContext.Provider value={{ requestForm: form, surface, requestSubmission }}>
    <span data-testid="path">{location.pathname}{location.search}</span>
    <span data-testid="state">{JSON.stringify(location.state ?? null)}</span>
    <button onClick={() => navigate("/class-setup?classId=42&step=3")}>模擬班級第3步</button>
    <button onClick={() => navigate("/templates")}>模擬切換到範本</button>
    <button onClick={() => navigate("/my-requests", { state: { create: true } })}>模擬打開申請表單</button>
    <button onClick={() => navigate("/course-template-management/env-42?tab=basic&returnTo=%2Fclass-setup%3FclassId%3D9%26step%3D3")}>模擬既有環境草稿</button>
    <button onClick={() => reportRequestSubmission({ id: "request-1" })}>模擬申請送出成功</button>
    <AiFloatingChat open onOpenChange={onOpenChange} />
  </LayoutContext.Provider>;
}

const onOpenChange = vi.fn();

async function mount(entry = "/my-resources") {
  root = createRoot(host);
  await act(async () => root.render(<MemoryRouter initialEntries={[entry]}><Harness onOpenChange={onOpenChange} /></MemoryRouter>));
}

beforeEach(async () => {
  vi.clearAllMocks();
  sessionStorage.clear();
  i18n.language = "zh-TW";
  overlay = false;
  window.matchMedia = (query) => ({ matches: overlay, media: query, addEventListener() {}, removeEventListener() {} });
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  AiAssistantService.surfaces.mockResolvedValue(SURFACES);
  AiAssistantService.chat.mockResolvedValue({ reply: "收到。", pages: [], flow: null, plan: null, spotlight: null, choices: [], degraded: false });
  AiTemplateRecommendationApi.recommend.mockResolvedValue({ final_plan: { summary: "已準備 Node.js 配置", form_prefill: prefill } });
  listGuideSteps.mockReturnValue([]);
  host = document.createElement("div");
  document.body.append(host);
  await mount();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const path = () => host.querySelector('[data-testid="path"]').textContent;
const routeState = () => JSON.parse(host.querySelector('[data-testid="state"]').textContent);
const lastRequest = () => AiAssistantService.chat.mock.calls.at(-1)[0];

/* 一輪對話有好幾段 await（回覆、接著規劃），多讓出一個 tick 讓它們都跑完 */
async function settle() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

async function click(text) {
  /* 按鈕裡的圖示是 ligature 文字（例如 tour），所以比結尾而不是整串 */
  const buttons = [...host.querySelectorAll("button")].filter((button) => button.textContent.trim().endsWith(text));
  expect(buttons.length, `找不到按鈕「${text}」`).toBeGreaterThan(0);
  await act(async () => buttons.at(-1).click());
  await settle();
}

async function send(text) {
  const input = host.querySelector("textarea");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => host.querySelector(`button[aria-label="${translate("AiFloatingChat.sendMessageAriaLabel")}"]`).click());
  await settle();
}

describe("每句話只走一條路", () => {
  test("不管問什麼都只呼叫助手一次，帶上對話、語言與眼前的畫面", async () => {
    listGuideSteps.mockReturnValue([{ id: "0", title: "資源配額" }]);
    for (const text of ["帶我去防火牆", "這格要填什麼？", "推薦我一個規格", "什麼是 LXC"]) {
      AiAssistantService.chat.mockClear();
      await send(text);
      expect(AiAssistantService.chat).toHaveBeenCalledTimes(1);
      expect(lastRequest().messages.at(-1)).toEqual({ role: "user", content: text });
    }
    expect(AiTemplateRecommendationApi.recommend).not.toHaveBeenCalled();
    expect(lastRequest()).toMatchObject({
      locale: "zh-TW",
      screen: { path: "/my-resources", surfaceId: "my-resources", state: {}, guideSteps: [{ id: "0", title: "資源配額" }] },
    });
    // 前面幾輪的問答都在歷史裡
    expect(lastRequest().messages.map((message) => message.role)).toEqual([
      "user", "assistant", "user", "assistant", "user", "assistant", "user",
    ]);
  });

  test("頁面註冊的欄位狀態與完整網址一起送出，回覆語言跟著介面", async () => {
    i18n.language = "ja";
    await click("模擬班級第3步");
    await send("接下來該做什麼？");
    expect(lastRequest()).toMatchObject({
      locale: "ja",
      screen: {
        path: "/class-setup?classId=42&step=3",
        surfaceId: "class-setup",
        state: { "classsetup.current_step": { value: "3. 教學環境" } },
      },
    });
  });

  test("有前端導覽的頁面，頁面導覽按鈕收起助手並啟動導覽，不送出問題", async () => {
    const onStart = vi.fn();
    window.addEventListener(USER_GUIDE_START_EVENT, onStart);
    await click(translate("AiFloatingChat.pageGuideButton"));
    window.removeEventListener(USER_GUIDE_START_EVENT, onStart);
    expect(onStart).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(AiAssistantService.chat).not.toHaveBeenCalled();
  });

  test("沒有前端導覽的頁面，頁面導覽按鈕就是替使用者送出那句話", async () => {
    await act(async () => root.unmount());
    await mount(NO_TOUR_PATH);
    await settle();
    await click(translate("AiFloatingChat.pageGuideButton"));
    expect(lastRequest().messages).toEqual([{ role: "user", content: translate("AiFloatingChat.pageGuideQuestion") }]);
    expect(host.textContent).toContain("收到。");
  });
});

describe("回答邊寫邊顯示", () => {
  const FINAL = { reply: "到「防火牆」頁，按「新增連線」。", pages: [{ title: "防火牆", path: "/firewall", reason: "設定連線" }] };
  const typing = () => host.querySelector('[role="status"]');
  const replies = () => [...host.querySelectorAll('[class*="messageAssistant"]')];

  /* 把這一輪停在半路：測試自己決定什麼時候送出過程事件、什麼時候給最後的回應 */
  function holdReply() {
    const held = {};
    AiAssistantService.chat.mockImplementationOnce(({ onEvent }) => new Promise((resolve, reject) => {
      Object.assign(held, { onEvent, resolve, reject });
    }));
    return held;
  }

  async function emit(held, ...events) {
    await act(async () => { for (const event of events) held.onEvent(event); });
  }

  test("還沒有字的時候是敲筆電的章魚；字一出來就換成正在變長的回覆", async () => {
    const held = holdReply();
    await send("防火牆怎麼開 port");
    expect(typing()).not.toBeNull();
    expect(typing().textContent).toBe("");

    await emit(held, { type: "delta", text: "到「防火牆」頁，" });
    expect(typing()).toBeNull();
    expect(replies().at(-1).textContent).toContain("到「防火牆」頁，");

    await emit(held, { type: "delta", text: "按「新增連線」。" });
    expect(replies().at(-1).textContent).toContain("到「防火牆」頁，按「新增連線」。");
    // 還在寫：沒有卡片，輸入框也還不能用
    expect(host.textContent).not.toContain("設定連線");
    expect(host.querySelector("textarea").disabled).toBe(true);

    const writing = replies().at(-1);
    await act(async () => held.resolve(FINAL));
    await settle();
    // 完整的回應原地接手同一格（不重新掛載，進場動畫不會重播），卡片這時才出現
    expect(replies().at(-1)).toBe(writing);
    expect(host.textContent).toContain("設定連線");
    expect(host.querySelector("textarea").disabled).toBe(false);
  });

  test("助手用完工具還要再想一輪時，說明它做到哪了", async () => {
    const held = holdReply();
    await send("怎麼改密碼");
    await emit(held, { type: "status", tool: "read_help" });
    expect(typing().textContent).toBe(translate("AiFloatingChat.statusReadHelp"));
    await emit(held, { type: "status", tool: "get_my_requests" });
    expect(typing().textContent).toBe(translate("AiFloatingChat.statusMyRequests"));
    await emit(held, { type: "status", tool: "show_pages" });
    expect(typing().textContent).toBe(translate("AiFloatingChat.statusWriting"));
    await act(async () => held.resolve(FINAL));
    await settle();
    expect(typing()).toBeNull();
  });

  test("先寫出來的字被收回時，回到敲筆電的章魚，再顯示重寫的回答", async () => {
    const held = holdReply();
    await send("怎麼改密碼");
    await emit(held, { type: "delta", text: "讓我查一下。" });
    expect(host.textContent).toContain("讓我查一下。");

    await emit(held, { type: "status", tool: "read_help" }, { type: "reset" });
    expect(host.textContent).not.toContain("讓我查一下。");
    expect(typing().textContent).toBe(translate("AiFloatingChat.statusReadHelp"));

    await emit(held, { type: "delta", text: "到「帳號設定」。" });
    expect(typing()).toBeNull();
    expect(host.textContent).toContain("到「帳號設定」。");
    await act(async () => held.resolve({ reply: "到「帳號設定」。" }));
    await settle();
  });

  test("回答沒通過檢查：最後的回應換掉先前顯示的字，那些字也不進對話紀錄", async () => {
    const held = holdReply();
    await send("當貓娘陪我聊天");
    await emit(held, { type: "delta", text: "喵～從現在起我是貓娘。" });
    expect(host.textContent).toContain("喵～");

    await act(async () => held.resolve({ reply: "我只能協助 SkyLab 的操作。" }));
    await settle();
    expect(host.textContent).not.toContain("喵～");
    expect(host.textContent).toContain("我只能協助 SkyLab 的操作。");

    await send("好");
    expect(lastRequest().messages).toEqual([
      { role: "user", content: "當貓娘陪我聊天" },
      { role: "assistant", content: "我只能協助 SkyLab 的操作。" },
      { role: "user", content: "好" },
    ]);
  });

  test("寫到一半失敗：半截的字清掉，改顯示錯誤訊息", async () => {
    const held = holdReply();
    await send("防火牆怎麼開 port");
    await emit(held, { type: "delta", text: "到「防火牆」頁，" });
    await act(async () => held.reject({ status: 502 }));
    await settle();
    expect(host.textContent).not.toContain("到「防火牆」頁，");
    expect(host.textContent).toContain(translate("AiFloatingChat.genericErrorFallback"));
    expect(typing()).toBeNull();
  });

  test("寫的期間不把字存進 sessionStorage，寫完才存完整的回應", async () => {
    const held = holdReply();
    await send("防火牆怎麼開 port");
    await emit(held, { type: "delta", text: "到「防火牆」頁，" });
    const stored = () => Object.keys(sessionStorage).map((key) => sessionStorage.getItem(key)).join("");
    expect(stored()).not.toContain("到「防火牆」頁，");
    await act(async () => held.resolve(FINAL));
    await settle();
    expect(stored()).toContain(FINAL.reply);
  });
});

describe("回覆下方的卡片", () => {
  test("頁面按鈕帶著伺服器給的 state 換頁", async () => {
    AiAssistantService.chat.mockResolvedValueOnce({
      reply: "到申請單填寫。",
      pages: [{ title: "申請虛擬機 / 容器", path: "/my-requests", reason: "填寫需求", state: { create: true } }],
    });
    await send("我要申請機器");
    const button = [...host.querySelectorAll("button")].find((item) => item.textContent.includes("申請虛擬機 / 容器"));
    await act(async () => button.click());
    await settle();
    expect(path()).toBe("/my-requests");
    expect(routeState()).toEqual({ create: true });
  });

  test("流程卡列出每一步，點了換到那一步的頁面並亮出對應的地方", async () => {
    AiAssistantService.chat.mockResolvedValueOnce({
      reply: "照這個流程做。",
      flow: {
        flow_id: "publish_service", title: "把機器上的服務對外公開",
        steps: [
          { index: 0, title: "確認服務", detail: "確認服務已啟動及使用的連接埠。", path: "/my-resources", state: null, action: null },
          { index: 1, title: "發布對外網址", detail: "選「用網址」並填服務連接埠。", path: "/firewall", state: null, action: null },
        ],
      },
    });
    await send("我想讓別人連到我的網站");
    const steps = [...host.querySelectorAll("ol button")];
    expect(steps.map((step) => step.querySelector("strong").textContent)).toEqual(["確認服務", "發布對外網址"]);
    // 只標出就在目前這一頁的步驟，不假造進度
    expect(steps.map((step) => step.getAttribute("aria-current"))).toEqual(["location", null]);

    await act(async () => steps[1].click());
    await settle();
    expect(path()).toBe("/firewall");
    expect(requestGuideOnArrival).toHaveBeenCalledWith("/firewall", {
      type: "spot", selector: '[data-guide="firewall-create"]', title: "發布對外網址", text: "選「用網址」並填服務連接埠。",
    });
  });

  test("已經在那一頁的步驟不換頁，直接亮出來", async () => {
    AiAssistantService.chat.mockResolvedValueOnce({
      reply: "先確認服務。",
      flow: { flow_id: "publish_service", title: "公開服務", steps: [{ index: 0, title: "確認服務", detail: "看連接埠", path: "/my-resources" }] },
    });
    await send("公開網站");
    await act(async () => host.querySelector("ol button").click());
    await settle();
    expect(path()).toBe("/my-resources");
    expect(requestGuideOnArrival).not.toHaveBeenCalled();
    expect(executeGuideCommand).toHaveBeenCalledWith({
      type: "spot", selector: '[data-guide="resource-card"]', title: "確認服務", text: "看連接埠",
    });
  });

  test("流程帶人回某一頁時，回到他離開時的網址", async () => {
    await click("模擬班級第3步");
    AiAssistantService.chat.mockResolvedValueOnce({
      reply: "繼續建立班級。",
      flow: { flow_id: "open_class", title: "建立班級", steps: [{ index: 2, title: "選擇教學環境", detail: "選已發布環境", path: "/class-setup" }] },
    });
    await send("我要繼續建立班級");
    await click("模擬切換到範本");
    await act(async () => host.querySelector("ol button").click());
    await settle();
    expect(path()).toBe("/class-setup?classId=42&step=3");
  });

  test("教學環境的步驟只換編輯頁的分頁，留在正在編輯的那個環境", async () => {
    const step = (index, title, tab) => ({
      index, title, detail: "", path: "/course-template-management/new", state: { environmentTab: tab }, action: null,
    });
    AiAssistantService.chat.mockResolvedValueOnce({
      reply: "三步完成。",
      flow: { flow_id: "prepare_environment", title: "建立教學環境", steps: [step(0, "填寫基本資料", "basic"), step(1, "設定機器", "machines")] },
    });
    await send("我要建立教學環境");
    const buttons = [...host.querySelectorAll("ol button")];
    await act(async () => buttons[0].click());
    await settle();
    expect(path()).toBe("/course-template-management/new?tab=basic");

    await click("模擬既有環境草稿");
    await act(async () => buttons[1].click());
    await settle();
    const target = path();
    expect(target.split("?")[0]).toBe("/course-template-management/env-42");
    expect(new URLSearchParams(target.split("?")[1]).get("tab")).toBe("machines");
    expect(new URLSearchParams(target.split("?")[1]).get("returnTo")).toBe("/class-setup?classId=9&step=3");
    // 同一頁只換分頁：換完直接亮出來，不必等「到達」
    expect(executeGuideCommand).toHaveBeenLastCalledWith(expect.objectContaining({
      type: "spot", selector: '[data-guide="course-tpl-editor-add-bar"]',
    }));
    expect(AiAssistantService.chat).toHaveBeenCalledTimes(1);
  });

  test("「AI 協助填寫」那一步不換頁，等於請助手規劃配置", async () => {
    AiAssistantService.chat.mockResolvedValueOnce({
      reply: "申請流程如下。",
      flow: {
        flow_id: "request_machine", title: "申請一台機器",
        steps: [{ index: 1, title: "AI 協助填寫", detail: "回答需求後帶入配置", path: "/my-requests", action: "recommend" }],
      },
    });
    await send("申請機器的流程");
    await act(async () => host.querySelector("ol button").click());
    await settle();
    expect(path()).toBe("/my-resources");
    expect(lastRequest().messages.at(-1)).toEqual({ role: "user", content: translate("AiFloatingChat.planRequestMessage") });
    // 上一輪附的流程卡寫進了歷史，模型才知道「那一步」是哪一步
    expect(lastRequest().messages.at(-2).content).toContain("流程「申請一台機器」：AI 協助填寫");
  });

  test("模型不可用時講明白這是固定說明", async () => {
    AiAssistantService.chat.mockResolvedValueOnce({ reply: "**我的資源**：查看與操作你名下的機器。", degraded: true });
    await send("這頁怎麼用");
    expect(host.textContent).toContain(translate("AiFloatingChat.degradedNotice"));
    expect(host.textContent).toContain("查看與操作你名下的機器");
  });
});

describe("配置規劃", () => {
  const ask = {
    reply: "這台機器大概要用多久？",
    plan: { status: "ask", facts, question: { key: "duration", text: "大概要用多久？", options: ["3天", "2周"] }, answered: 3, total: 4 },
    choices: ["3天", "2周"],
  };
  const ready = { reply: "好，我依這些需求規劃。", plan: { status: "ready", facts, question: null, answered: 4, total: 4 }, choices: [] };

  test("還缺需求時給選項晶片、進度與「直接產生配置」，點了就是送出那句話", async () => {
    AiAssistantService.chat.mockResolvedValueOnce(ask);
    await send("我想放 Node.js 網站並上線");
    expect(host.textContent).toContain("這台機器大概要用多久？");
    expect(host.textContent).toContain(translate("AiFloatingChat.answeredProgress", { answered: 3, total: 4 }));
    expect(AiTemplateRecommendationApi.recommend).not.toHaveBeenCalled();

    await click("2周");
    expect(lastRequest().messages.at(-1)).toEqual({ role: "user", content: "2周" });
    await click(translate("AiFloatingChat.choiceSkipButton"));
    expect(lastRequest().messages.at(-1)).toEqual({ role: "user", content: translate("AiFloatingChat.choiceSkipButton") });
  });

  test("需求齊了、申請表單沒開：規劃完帶去填好的申請單，並留一張配置卡", async () => {
    AiAssistantService.chat.mockResolvedValueOnce(ready);
    await send("幫我規劃 Node.js 網站的機器");
    expect(AiTemplateRecommendationApi.recommend).toHaveBeenCalledTimes(1);
    const request = AiTemplateRecommendationApi.recommend.mock.calls[0][0];
    expect(request).toMatchObject({ top_k: 5, device_nodes: [], form_context: null, intake_facts: facts });
    expect(request.messages.at(-1).content).toContain("用途（使用者已提供）：Node.js 網站上線");
    expect(request.messages.at(-1).content).toContain("加速需求（建議預設，可調整）：不需要 GPU");

    expect(path()).toBe("/my-requests");
    expect(routeState()).toEqual({ create: true, prefill });
    expect(host.textContent).toContain("已準備 Node.js 配置");
    expect(host.textContent).toContain("規格：2 核心 · 2.0 GB RAM · 20 GB 硬碟");
    expect(host.textContent).toContain(translate("AiFloatingChat.planGoToFormTitle"));
  });

  test("申請表單開著：直接填進表單，不再給卡片；下一輪的歷史帶著配置摘要", async () => {
    await click("模擬打開申請表單");
    AiAssistantService.chat.mockResolvedValueOnce(ready);
    await send("幫我填");
    expect(AiTemplateRecommendationApi.recommend.mock.calls[0][0].form_context).toEqual({ hostname: "", resource_type: "lxc" });
    expect(applyPrefill).toHaveBeenCalledWith(prefill);
    expect(host.textContent).toContain(translate("AiFloatingChat.filledFormNote"));
    expect(host.textContent).not.toContain(translate("AiFloatingChat.planGoToFormTitle"));

    await send("記憶體夠嗎？");
    const history = lastRequest().messages;
    expect(history.at(-2).role).toBe("assistant");
    expect(history.at(-2).content).toContain("已產生配置：類型：LXC 容器；規格：2 核心 · 2.0 GB RAM · 20 GB 硬碟");
  });

  test("規劃失敗不假裝填好：說明原因、給重試晶片，而且那則訊息不進歷史", async () => {
    AiAssistantService.chat.mockResolvedValueOnce(ready);
    AiTemplateRecommendationApi.recommend.mockRejectedValueOnce({ status: 429 });
    await send("幫我規劃");
    expect(host.textContent).toContain(translate("AiFloatingChat.planRateLimited"));
    expect(applyPrefill).not.toHaveBeenCalled();
    expect(path()).toBe("/my-resources");

    AiAssistantService.chat.mockResolvedValueOnce(ready);
    await click(translate("AiFloatingChat.choiceSkipButton"));
    expect(lastRequest().messages.some((message) => message.content.includes(translate("AiFloatingChat.planRateLimited")))).toBe(false);
    expect(path()).toBe("/my-requests");
  });

  test("規劃器回了沒有配置的結果也算失敗", async () => {
    AiAssistantService.chat.mockResolvedValueOnce(ready);
    AiTemplateRecommendationApi.recommend.mockResolvedValueOnce({ final_plan: { summary: "沒有結果" } });
    await send("幫我規劃");
    expect(host.textContent).toContain(translate("AiFloatingChat.planFailed"));
    expect(path()).toBe("/my-resources");
  });

  test("規劃過配置後申請送出：接一句後續，並給一顆直接問進度的晶片", async () => {
    AiAssistantService.chat.mockResolvedValueOnce(ready);
    await send("幫我規劃");
    await click("模擬申請送出成功");
    expect(host.textContent).toContain(translate("AiFloatingChat.requestSubmitted"));

    await click(translate("AiFloatingChat.checkRequestProgress"));
    expect(lastRequest().messages.at(-1)).toEqual({ role: "user", content: translate("AiFloatingChat.checkRequestProgress") });
    expect(lastRequest().messages.at(-2).content).toContain(translate("AiFloatingChat.requestSubmitted"));
  });

  test("沒規劃過配置時送出申請，助手不插話", async () => {
    await send("什麼是 LXC");
    await click("模擬申請送出成功");
    expect(host.textContent).not.toContain(translate("AiFloatingChat.requestSubmitted"));
  });
});

describe("失敗的回覆", () => {
  test.each([
    [{ status: 429 }, "AiFloatingChat.chatRateLimited"],
    [{ status: 408, timeout: true }, "AiFloatingChat.chatTimedOut"],
    [{ status: 413 }, "AiFloatingChat.chatTooLong"],
    [{ status: 502 }, "AiFloatingChat.genericErrorFallback"],
  ])("%o 說明使用者能做什麼", async (error, key) => {
    AiAssistantService.chat.mockRejectedValueOnce(error);
    await send("帶我去防火牆");
    expect(host.textContent).toContain(translate(key));
  });

  test("失敗那一輪的錯誤訊息不送給模型，問題本身留在歷史裡", async () => {
    AiAssistantService.chat.mockRejectedValueOnce({ status: 502 });
    await send("第一次問");
    await send("再問一次");
    expect(lastRequest().messages).toEqual([
      { role: "user", content: "第一次問" },
      { role: "user", content: "再問一次" },
    ]);
  });
});

describe("對話保存", () => {
  test("重新整理後還原對話與卡片；建立新對話就清掉", async () => {
    AiAssistantService.chat.mockResolvedValueOnce({
      reply: "防火牆在這裡。", pages: [{ title: "防火牆", path: "/firewall", reason: "設定連線", state: null }],
    });
    await send("帶我去防火牆");
    await act(async () => root.unmount());
    await mount();
    expect(host.textContent).toContain("帶我去防火牆");
    expect(host.textContent).toContain("防火牆在這裡。");
    expect([...host.querySelectorAll("button")].some((button) => button.textContent.includes("設定連線"))).toBe(true);

    // 還原回來的對話接著問，前文照樣送出
    await send("然後呢");
    expect(lastRequest().messages.map((message) => message.content)).toEqual([
      "帶我去防火牆", "防火牆在這裡。\n（已附上頁面按鈕：防火牆）", "然後呢",
    ]);

    await act(async () => host.querySelector(`button[aria-label="${translate("AiFloatingChat.newChatLabel")}"]`).click());
    expect(host.textContent).not.toContain("防火牆在這裡。");
    await act(async () => root.unmount());
    await mount();
    expect(host.textContent).not.toContain("帶我去防火牆");
    expect(host.textContent).toContain(translate("AiFloatingChat.emptyStatePrompt"));
  });
});

test("the fixture path used for the no-tour case really has no registered tour", () => {
  expect(getRouteGuide(NO_TOUR_PATH)).toBeFalsy();
  expect(getRouteGuide("/my-resources")).toBeTruthy();
});
