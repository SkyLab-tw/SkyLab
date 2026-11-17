// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import AiFloatingChat from "./AiFloatingChat";
import { LayoutContext } from "../../layout/layoutContext";
import translations from "../../locales/zh-TW/components.json";

vi.mock("../../contexts/AuthContext", () => ({ useAuth: () => ({ user: { id: "overlay-teacher" } }) }));
vi.mock("react-i18next", async (importOriginal) => ({ ...await importOriginal(), useTranslation: () => ({ t: (key) => translations[key] ?? key }) }));
vi.mock("../../services/aiNavigation", () => ({ AiNavigationService: { resolve: vi.fn(), intake: vi.fn() } }));
vi.mock("../../services/aiTemplateRecommendation", () => ({ AiTemplateRecommendationApi: { chat: vi.fn(), recommend: vi.fn() } }));
vi.mock("../../services/aiContextualHelp", () => ({
  AiContextualHelpService: { surfaces: vi.fn().mockResolvedValue([]), explain: vi.fn() }, matchSurface: () => null,
}));
vi.mock("../OctoPet/OctoPet", () => ({ default: () => <span /> }));

let host;
let root;

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  /* 寬螢幕（≥1440）：平常是並排停靠，不是覆蓋層 */
  window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

async function renderOpen(forceOverlay) {
  await act(async () => root.render(
    <MemoryRouter initialEntries={["/class-management/c1/ai"]}>
      <LayoutContext.Provider value={{ requestForm: null, surface: null, requestSubmission: null }}>
        <AiFloatingChat open onOpenChange={() => {}} forceOverlay={forceOverlay} />
      </LayoutContext.Provider>
    </MemoryRouter>,
  ));
}

const assistantRoot = () => host.querySelector("aside").parentElement;

test("寬螢幕平常並排停靠：不加覆蓋層、不鎖頁面捲動", async () => {
  await renderOpen(false);
  expect(assistantRoot().className).not.toMatch(/rootOverlay/);
  expect(document.documentElement.style.overflow).toBe("");
});

test("頁面要求覆蓋（AI 導師檢查）時，寬螢幕也改成覆蓋層並鎖住底下頁面捲動", async () => {
  await renderOpen(true);
  expect(assistantRoot().className).toMatch(/rootOverlay/);
  expect(document.documentElement.style.overflow).toBe("hidden");
});
