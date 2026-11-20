// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, afterEach, expect, test, vi } from "vitest";
import AiFloatingChat from "./AiFloatingChat";
import { LayoutContext } from "../../layout/layoutContext";
import { AiContextualHelpService } from "../../services/aiContextualHelp";
import { AiTemplateRecommendationApi } from "../../services/aiTemplateRecommendation";
import { AiNavigationService } from "../../services/aiNavigation";
import translations from "../../locales/zh-TW/components.json";
import { USER_GUIDE_START_EVENT } from "../UserGuide/routeGuides";

vi.mock("../../contexts/AuthContext", () => ({ useAuth: () => ({ user: { id: "hint-student" } }) }));
vi.mock("react-i18next", async (importOriginal) => ({ ...await importOriginal(), useTranslation: () => ({ t: (key) => translations[key] ?? key }) }));
vi.mock("../../services/aiNavigation", () => ({ AiNavigationService: { resolve: vi.fn(), intake: vi.fn() } }));
vi.mock("../../services/aiTemplateRecommendation", () => ({ AiTemplateRecommendationApi: { chat: vi.fn(), recommend: vi.fn() } }));
vi.mock("../../services/aiContextualHelp", () => ({
  AiContextualHelpService: { surfaces: vi.fn().mockResolvedValue([]), explain: vi.fn() }, matchSurface: () => null,
}));
vi.mock("../OctoPet/OctoPet", () => ({ default: () => <span /> }));
let host, root;
function Harness() {
  const [open, setOpen] = useState(false);
  return <LayoutContext.Provider value={{ requestForm: null, surface: null, requestSubmission: null }}>
    <AiFloatingChat open={open} onOpenChange={setOpen} />
  </LayoutContext.Provider>;
}
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers(); vi.clearAllMocks(); localStorage.clear();
  window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove(); vi.useRealTimers();
});
async function render() {
  await act(async () => root.render(<MemoryRouter initialEntries={["/my-resources"]}><Harness /></MemoryRouter>));
  await act(async () => vi.advanceTimersByTimeAsync(1500));
}
function expectNoQuestionSent() {
  expect(AiContextualHelpService.explain).not.toHaveBeenCalled();
  expect(AiTemplateRecommendationApi.chat).not.toHaveBeenCalled();
  expect(AiNavigationService.resolve).not.toHaveBeenCalled();
}

test("clicking the reminder starts the page tour without opening the assistant", async () => {
  const onStart = vi.fn();
  window.addEventListener(USER_GUIDE_START_EVENT, onStart);
  await render();
  expect(host.querySelector("aside")).toBeNull();
  expectNoQuestionSent();
  await act(async () => host.querySelector('[role="status"]').closest("button").click());
  await act(async () => vi.advanceTimersByTimeAsync(200));
  window.removeEventListener(USER_GUIDE_START_EVENT, onStart);
  expect(onStart).toHaveBeenCalledTimes(1);
  expect(host.querySelector("aside")).toBeNull();
  expectNoQuestionSent();
});

test("closing the reminder does not open the assistant", async () => {
  await render();
  await act(async () => host.querySelector('button[aria-label="關閉提示"]').click());
  expect(host.querySelector("aside")).toBeNull();
  expect(host.querySelector('[role="status"]')).toBeNull();
  expectNoQuestionSent();
});

test("typing a whole-page question starts the page tour instead of asking the AI", async () => {
  const onStart = vi.fn();
  window.addEventListener(USER_GUIDE_START_EVENT, onStart);
  await render();
  await act(async () => host.querySelector(`button[aria-label="${translations["AiFloatingChat.openAssistantAriaLabel"]}"]`).click());
  const input = host.querySelector("textarea");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(input, "這頁怎麼用？");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => host.querySelector(`button[aria-label="${translations["AiFloatingChat.sendMessageAriaLabel"]}"]`).click());
  await act(async () => vi.advanceTimersByTimeAsync(400));
  window.removeEventListener(USER_GUIDE_START_EVENT, onStart);
  expect(onStart).toHaveBeenCalledTimes(1);
  expect(host.querySelector("aside")).toBeNull();
  expectNoQuestionSent();
});
