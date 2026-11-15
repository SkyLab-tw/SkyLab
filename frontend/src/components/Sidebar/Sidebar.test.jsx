// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import Sidebar from "./Sidebar";
import { setLanguage } from "../../i18n";

const logout = vi.fn();
const confirmLeave = vi.fn();
const auth = vi.hoisted(() => ({ user: null }));

vi.mock("../../contexts/AuthContext", () => ({
  useAuth: () => ({ user: auth.user, logout }),
}));
vi.mock("../../contexts/UnsavedChangesContext", () => ({ useUnsavedChanges: () => ({ confirmLeave }) }));
vi.mock("../../i18n", () => ({
  SUPPORTED_LANGUAGES: ["zh-TW", "en", "ja"],
  currentLanguage: (lang) => (["zh-TW", "en", "ja"].includes(lang) ? lang : "zh-TW"),
  setLanguage: vi.fn(),
}));
vi.mock("../Jobs/JobsButton", () => ({ default: () => null }));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal()),
  useTranslation: () => ({ t: (key) => key, i18n: { language: "zh-TW" } }),
}));

let host;
let root;

function CurrentLocation() {
  return <output>{useLocation().pathname}</output>;
}

async function renderAt(path) {
  await act(async () => {
    root.render(<MemoryRouter key={path} initialEntries={[path]}><Sidebar collapsed={false} mobileOpen={false} /><CurrentLocation /></MemoryRouter>);
  });
}

const buttons = (label) => host.querySelectorAll(`button[aria-label="Sidebar.${label}"]`);

beforeEach(async () => {
  vi.clearAllMocks();
  auth.user = { id: "u1", email: "a@example.com", full_name: "A", role: "student" };
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await renderAt("/dashboard");
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function clickLogout() {
  const userBtn = document.querySelector('button[aria-label="Sidebar.userMenuAriaLabel"]');
  await act(async () => { userBtn.click(); });
  const logoutBtn = [...document.querySelectorAll("button")].find((b) => b.textContent.includes("Sidebar.logOut"));
  await act(async () => { logoutBtn.click(); });
}

test("logout waits for the unsaved-changes confirmation and stays when declined", async () => {
  confirmLeave.mockResolvedValue(false);
  await clickLogout();
  expect(confirmLeave).toHaveBeenCalledTimes(1);
  expect(logout).not.toHaveBeenCalled();
});

test("logout proceeds once leaving is confirmed", async () => {
  confirmLeave.mockResolvedValue(true);
  await clickLogout();
  expect(logout).toHaveBeenCalledTimes(1);
});

/* 管理員只有一個首頁（/dashboard 管理首頁），管理員設定側欄裡不再另放首頁 */
test.each(["/dashboard", "/admin"])("admin sees at most one home entry at %s", async (path) => {
  auth.user = { ...auth.user, role: "admin" };
  await renderAt(path);
  expect(buttons("topDashboard").length).toBe(path === "/dashboard" ? 1 : 0);
  expect(buttons("generalPages").length).toBe(0);
});

test("管理者的課程入口可開啟學生課程頁", async () => {
  auth.user = { ...auth.user, role: "admin" };
  confirmLeave.mockResolvedValue(true);
  await renderAt("/dashboard");
  expect(buttons("topCourses")).toHaveLength(1);
  await act(async () => buttons("topCourses")[0].click());
  expect(host.querySelector("output").textContent).toBe("/courses");
});

test("學生的課程入口維持連到學生總覽", async () => {
  confirmLeave.mockResolvedValue(true);
  await renderAt("/dashboard");
  expect(buttons("topCourses")).toHaveLength(1);
  await act(async () => buttons("topCourses")[0].click());
  expect(host.querySelector("output").textContent).toBe("/courses");
});

test("老師使用班級管理入口", async () => {
  auth.user = { ...auth.user, role: "teacher" };
  await renderAt("/dashboard");
  expect(buttons("topCourses")).toHaveLength(0);
  expect(buttons("itemClassManagement")).toHaveLength(1);
});

async function pressEscape() {
  await act(async () => {
    document.activeElement.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  });
  // 等 130ms 離場動畫跑完、選單卸載
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 160)); });
}

test("帳號選單用共用動作選單：頭顯示姓名，焦點落在第一項，Esc 關閉並把焦點還給觸發鈕", async () => {
  const userBtn = document.querySelector('button[aria-label="Sidebar.userMenuAriaLabel"]');
  await act(async () => { userBtn.click(); });

  const menu = document.querySelector('[role="menu"]');
  expect(menu).not.toBeNull();
  expect(userBtn.getAttribute("aria-controls")).toBe(menu.id);
  expect(menu.textContent).toContain("a@example.com");
  expect(document.activeElement.textContent).toContain("Sidebar.userSettings");

  await pressEscape();
  expect(document.querySelector('[role="menu"]')).toBeNull();
  expect(document.activeElement).toBe(userBtn);
});

test("語言選單用共用單選清單：目前的語言打勾，選了就切換並把焦點還給觸發鈕", async () => {
  const langBtn = document.querySelector('button[aria-label="語言 / Language"]');
  await act(async () => { langBtn.click(); });

  const options = [...document.querySelectorAll('[role="listbox"] [role="option"]')];
  expect(options.map((option) => option.firstElementChild.textContent)).toEqual(["繁體中文", "English", "日本語"]);
  expect(options[0].getAttribute("aria-selected")).toBe("true");
  expect(document.activeElement).toBe(options[0]);

  await act(async () => { options[1].click(); });
  expect(setLanguage).toHaveBeenCalledWith("en");
  expect(document.activeElement).toBe(langBtn);
  expect(langBtn.getAttribute("aria-expanded")).toBe("false");
});
