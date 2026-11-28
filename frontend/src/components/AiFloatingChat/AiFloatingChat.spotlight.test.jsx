// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import AiFloatingChat from "./AiFloatingChat";
import { LayoutContext } from "../../layout/layoutContext";
import { AiAssistantService } from "../../services/aiAssistant";
import {
  clearArrivalCommand,
  executeGuideCommand,
  listGuideSteps,
  requestGuideOnArrival,
} from "../UserGuide/guideCommands";
import translations from "../../locales/zh-TW/components.json";

const confirmLeave = vi.fn();
const onOpenChange = vi.fn();

vi.mock("../../contexts/AuthContext", () => ({ useAuth: () => ({ user: { id: "student" } }) }));
vi.mock("../../contexts/UnsavedChangesContext", () => ({ useUnsavedChanges: () => ({ confirmLeave }) }));
vi.mock("react-i18next", async (importOriginal) => ({ ...(await importOriginal()), useTranslation: () => ({ t: translate }) }));
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

const STEPS = [{ id: "0", title: "資源配額" }, { id: "3", title: "開關機" }];
const pointing = { reply: "開關機在每台機器的電源選單。", spotlight: { target_id: "3" } };
let host, root, overlay;

function Harness() {
  const location = useLocation();
  const navigate = useNavigate();
  return <LayoutContext.Provider value={{ requestForm: null, surface: null, requestSubmission: null }}>
    <span data-testid="path">{location.pathname}</span>
    <button onClick={() => navigate("/firewall")}>模擬換到防火牆</button>
    <AiFloatingChat open onOpenChange={onOpenChange} />
  </LayoutContext.Provider>;
}

const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
const path = () => host.querySelector('[data-testid="path"]').textContent;
/* 按鈕裡的圖示是 ligature 文字（例如 ads_click），所以比結尾而不是整串 */
const buttonByText = (text) => [...host.querySelectorAll("button")].find((button) => button.textContent.trim().endsWith(text));

async function send(text) {
  const input = host.querySelector("textarea");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => host.querySelector(`button[aria-label="${translate("AiFloatingChat.sendMessageAriaLabel")}"]`).click());
  await settle();
}

async function render(isOverlay) {
  overlay = isOverlay;
  await act(async () => root.render(<MemoryRouter initialEntries={["/my-resources"]}><Harness /></MemoryRouter>));
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  window.matchMedia = (query) => ({ matches: overlay, media: query, addEventListener() {}, removeEventListener() {} });
  confirmLeave.mockResolvedValue(true);
  AiAssistantService.surfaces.mockResolvedValue([]);
  AiAssistantService.chat.mockResolvedValue(pointing);
  listGuideSteps.mockReturnValue(STEPS);
  /* clearAllMocks 不會還原實作：上一個測試在這裡面塞的斷言不能帶到下一個 */
  executeGuideCommand.mockReset();
  executeGuideCommand.mockReturnValue(true);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

test("送出時帶上聚光燈現在指得到的步驟，助手只能從裡面挑", async () => {
  await render(false);
  await send("開關機在哪裡？");
  expect(AiAssistantService.chat.mock.calls[0][0].screen.guideSteps).toEqual(STEPS);
});

test("並排停靠：回覆帶著要指的地方就直接亮出來，之後還能再按一次", async () => {
  await render(false);
  await send("開關機在哪裡？");
  expect(executeGuideCommand).toHaveBeenCalledWith({ type: "spot", stepId: "3" });
  expect(onOpenChange).not.toHaveBeenCalledWith(false);

  executeGuideCommand.mockClear();
  await act(async () => buttonByText(translate("AiFloatingChat.pointAtButton")).click());
  await settle();
  expect(executeGuideCommand).toHaveBeenCalledWith({ type: "spot", stepId: "3" });
});

test("覆蓋層：不自動指（面板蓋著頁面），按「在畫面上指給我看」先收面板再亮", async () => {
  await render(true);
  await send("開關機在哪裡？");
  expect(executeGuideCommand).not.toHaveBeenCalled();

  executeGuideCommand.mockImplementation(() => {
    expect(onOpenChange).toHaveBeenCalledWith(false);
    return true;
  });
  await act(async () => buttonByText(translate("AiFloatingChat.pointAtButton")).click());
  await settle();
  expect(executeGuideCommand).toHaveBeenCalledWith({ type: "spot", stepId: "3" });
  expect(path()).toBe("/my-resources");
});

test("等回覆的期間換了頁就不自動指；之後按按鈕會先回到那一頁再亮", async () => {
  await render(false);
  let finish;
  AiAssistantService.chat.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  await send("開關機在哪裡？");
  await act(async () => buttonByText("模擬換到防火牆").click());
  await act(async () => finish(pointing));
  await settle();
  expect(executeGuideCommand).not.toHaveBeenCalled();

  await act(async () => buttonByText(translate("AiFloatingChat.pointAtButton")).click());
  await settle();
  expect(requestGuideOnArrival).toHaveBeenCalledWith("/my-resources", { type: "spot", stepId: "3" });
  expect(path()).toBe("/my-resources");
  expect(executeGuideCommand).not.toHaveBeenCalled();
});

test("沒有要指的地方就沒有那顆按鈕", async () => {
  AiAssistantService.chat.mockResolvedValue({ reply: "LXC 是輕量容器。" });
  await render(false);
  await send("什麼是 LXC");
  expect(buttonByText(translate("AiFloatingChat.pointAtButton"))).toBeUndefined();
  expect(executeGuideCommand).not.toHaveBeenCalled();
});

test("頁面按鈕旁的「帶我看」：換過去之後開始那一頁的導覽；使用者不離開就把命令收回", async () => {
  AiAssistantService.chat.mockResolvedValue({
    reply: "防火牆在這裡。", pages: [{ title: "防火牆", path: "/firewall", reason: "設定連線", state: null }],
  });
  await render(false);
  await send("帶我去防火牆");

  confirmLeave.mockResolvedValueOnce(false);
  await act(async () => buttonByText(translate("AiFloatingChat.tourPageButton")).click());
  await settle();
  expect(requestGuideOnArrival).toHaveBeenCalledWith("/firewall", { type: "tour" });
  expect(clearArrivalCommand).toHaveBeenCalledWith({ type: "tour" });
  expect(path()).toBe("/my-resources");

  await act(async () => buttonByText(translate("AiFloatingChat.tourPageButton")).click());
  await settle();
  expect(path()).toBe("/firewall");
});

test("已經在那一頁按「帶我看」：不換頁，直接開始導覽", async () => {
  AiAssistantService.chat.mockResolvedValue({
    reply: "就是這一頁。", pages: [{ title: "我的資源", path: "/my-resources", reason: "", state: null }],
  });
  await render(false);
  await send("我的機器在哪");
  await act(async () => buttonByText(translate("AiFloatingChat.tourPageButton")).click());
  await settle();
  expect(executeGuideCommand).toHaveBeenCalledWith({ type: "tour" });
  expect(requestGuideOnArrival).not.toHaveBeenCalled();
  expect(confirmLeave).not.toHaveBeenCalled();
});

test("沒有聚光燈導覽的路徑不給「帶我看」", async () => {
  AiAssistantService.chat.mockResolvedValue({
    reply: "在這裡。", pages: [{ title: "某個沒有導覽的頁面", path: "/no-such-guide", reason: "", state: null }],
  });
  await render(false);
  await send("帶我去");
  expect(buttonByText(translate("AiFloatingChat.tourPageButton"))).toBeUndefined();
});
