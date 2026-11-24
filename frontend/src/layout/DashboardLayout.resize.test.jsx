// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DashboardLayout from "./DashboardLayout";

/* 只測抽屜開關：側欄與其他常駐元件換成最小替身 */
vi.mock("../components/Sidebar/Sidebar", () => ({
  default: ({ mobileOpen }) => <div data-testid="sidebar" data-open={String(mobileOpen)} />,
}));
vi.mock("../components/AiFloatingChat/AiFloatingChat", () => ({ default: () => null }));
vi.mock("../components/Classroom/ClassroomStudentLayer", () => ({ default: ({ children }) => children }));
vi.mock("../components/Jobs/JobsProvider", () => ({ default: ({ children }) => children }));
vi.mock("../components/SubnetBanner/SubnetBanner", () => ({ default: () => null }));
vi.mock("../components/SessionWarning/SessionWarningDialog", () => ({ default: () => null }));
vi.mock("../components/UserGuide/UserGuide", () => ({ default: () => null }));
vi.mock("../hooks/useSessionWarning", () => ({ default: () => ({ active: false, dismiss: () => {} }) }));
vi.mock("../contexts/AuthContext", () => ({ useAuth: () => ({ user: { id: "u1" } }) }));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal()),
  useTranslation: () => ({ t: (key) => key, i18n: { language: "zh-TW" } }),
}));

const original = { width: window.innerWidth, height: window.innerHeight };
let host;
let root;

function setViewport(width, height) {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
  Object.defineProperty(window, "innerHeight", { configurable: true, value: height });
  act(() => {
    window.dispatchEvent(new Event("resize"));
  });
}

const drawerOpen = () => host.querySelector('[data-testid="sidebar"]').dataset.open;

async function openDrawer() {
  await act(async () => {
    root.render(<MemoryRouter><DashboardLayout /></MemoryRouter>);
  });
  act(() => {
    host.querySelector('button[aria-label="DashboardLayout.openMenuAriaLabel"]').click();
  });
  expect(drawerOpen()).toBe("true");
}

describe("DashboardLayout 手機側欄抽屜", () => {
  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    setViewport(390, 700);
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
    setViewport(original.width, original.height);
  });

  it("只有高度變（網址列伸縮、鍵盤彈出）時抽屜維持開著", async () => {
    await openDrawer();
    setViewport(390, 760);
    expect(drawerOpen()).toBe("true");
  });

  it("寬度變了（轉向、拉窗）仍會關掉抽屜", async () => {
    await openDrawer();
    setViewport(700, 390);
    expect(drawerOpen()).toBe("false");
  });
});
