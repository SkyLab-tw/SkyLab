// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import AdminPage from "./AdminPage";
import { withQueryClient } from "../../../queries/testing";

const mocks = vi.hoisted(() => ({
  listAll: vi.fn(),
  getRegistrationPolicy: vi.fn(),
  saveRegistrationPolicy: vi.fn(),
  listPendingRegistrations: vi.fn(),
  confirm: vi.fn(),
  t: (key) => key,
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("../../../services/users", () => ({
  UsersService: {
    listAll: mocks.listAll,
    getRegistrationPolicy: mocks.getRegistrationPolicy,
    saveRegistrationPolicy: mocks.saveRegistrationPolicy,
    listPendingRegistrations: mocks.listPendingRegistrations,
  },
}));
/* 群組清單與這裡要測的行為無關：一律回空清單 */
vi.mock("../../../services/userGroups", () => ({
  UserGroupsService: { list: () => Promise.resolve({ data: [], count: 0 }), members: () => Promise.resolve({ data: [], count: 0 }) },
}));
vi.mock("react-i18next", async (importOriginal) => ({
  ...await importOriginal(),
  useTranslation: () => ({ t: mocks.t }),
}));
vi.mock("../../../contexts/AuthContext", () => ({ useAuth: () => ({ user: { id: "me" } }) }));
vi.mock("../../../hooks/useToast", () => ({ useToast: () => mocks.toast }));
vi.mock("../../../components/ConfirmDialog/ConfirmProvider", () => ({ useConfirm: () => mocks.confirm }));
vi.mock("../../../components/PageHeader/PageHeader", () => ({ default: () => null }));
vi.mock("../../../components/LoadingState/LoadingState", () => ({ default: () => null }));

let root;
let host;

/* TanStack Query 以 macrotask 批次通知，先等一個 timer tick 再看畫面 */
async function flush(ms = 0) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

/* 對話框離場動畫 150ms 後才卸載 */
const waitForClose = () => flush(200);

const dialog = () => document.body.querySelector("[role='dialog']");
const openButton = () => [...host.querySelectorAll("button")]
  .find((button) => button.textContent.includes("AdminPage.registrationSettingsTitle"));
const dialogButton = (key) => [...dialog().querySelectorAll("button")].find((button) => button.textContent === key);
const saveButton = () => dialog().querySelector("button[type='submit']");

/* 註冊設定的勾選框沒有 name，用標籤文字找（測試裡 t 直接回 key） */
function policyCheckbox(key) {
  const label = [...dialog().querySelectorAll("label")].find((el) => el.textContent.includes(key));
  return label?.querySelector("input[type='checkbox']") ?? null;
}

function domainInput() {
  return dialog().querySelector("#admin-student-email-domain");
}

/* React 只認原生 setter 設的值，再送一個 input 事件 */
function setInputValue(input, value) {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

async function renderAndOpen() {
  await act(async () => { root.render(withQueryClient(<AdminPage />)); });
  await flush();
  expect(dialog()).toBeNull();
  await act(async () => { openButton().click(); });
  await flush();
  expect(dialog()).toBeTruthy();
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.listAll.mockResolvedValue([]);
  mocks.listPendingRegistrations.mockResolvedValue({ data: [] });
  mocks.saveRegistrationPolicy.mockImplementation(async (payload) => payload);
  window.localStorage.clear();
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("AdminPage pending registrations panel", () => {
  const toggle = () => host.querySelector("[aria-controls='admin-pending-list']");
  const pendingNames = () => [...host.querySelectorAll("#admin-pending-list strong")].map((el) => el.textContent);

  test("starts collapsed with the count and settings button, expands from its title, and remembers the choice", async () => {
    mocks.getRegistrationPolicy.mockResolvedValue({ signup_enabled: true, approval_required: true, google_signup_enabled: false });
    mocks.listPendingRegistrations.mockResolvedValue({
      data: [{ id: "p1", email: "a@example.edu", full_name: "Student A", registration_status: "pending_review" }],
    });
    const remount = async () => {
      act(() => root.unmount());
      root = createRoot(host);
      await act(async () => { root.render(withQueryClient(<AdminPage />)); });
      await flush();
    };
    await act(async () => { root.render(withQueryClient(<AdminPage />)); });
    await flush();

    /* 預設收起：內容留在 DOM 播動畫，但 inert（點不到、Tab 不進去）；標題的人數與註冊設定鈕照常可用 */
    const list = () => host.querySelector("#admin-pending-list");
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
    expect(list().hasAttribute("inert")).toBe(true);
    expect(toggle().textContent).toContain("(1)");
    expect(openButton().disabled).toBe(false);

    await act(async () => { toggle().click(); });
    expect(toggle().getAttribute("aria-expanded")).toBe("true");
    expect(list().hasAttribute("inert")).toBe(false);
    expect(pendingNames()).toEqual(["Student A"]);

    /* 重新掛載（離開頁面再回來、重整）維持展開 */
    await remount();
    expect(toggle().getAttribute("aria-expanded")).toBe("true");
    expect(list().hasAttribute("inert")).toBe(false);

    /* 再收起後回來又是收起的 */
    await act(async () => { toggle().click(); });
    await remount();
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
    expect(list().hasAttribute("inert")).toBe(true);
  });
});

describe("AdminPage registration settings dialog", () => {
  test("the open button waits for the policy and sits in the pending registrations header", async () => {
    let resolvePolicy;
    mocks.getRegistrationPolicy.mockReturnValue(new Promise((resolve) => { resolvePolicy = resolve; }));
    await act(async () => { root.render(withQueryClient(<AdminPage />)); });
    await flush();

    expect(openButton().disabled).toBe(true);
    expect(openButton().closest("[data-guide='admin-pending']")).toBeTruthy();

    await act(async () => { resolvePolicy({ signup_enabled: false, approval_required: false, google_signup_enabled: false }); });
    await flush();
    expect(openButton().disabled).toBe(false);
  });

  test("switches are only saved by Save, in one request with the other settings untouched", async () => {
    mocks.getRegistrationPolicy.mockResolvedValue({
      signup_enabled: false, approval_required: true, google_signup_enabled: false,
      student_email_domain: "school.edu.tw",
    });
    await renderAndOpen();

    expect(saveButton().disabled).toBe(true);
    const box = policyCheckbox("AdminPage.googleSignupEnabled");
    expect(box.checked).toBe(false);

    await act(async () => { box.click(); });
    expect(policyCheckbox("AdminPage.googleSignupEnabled").checked).toBe(true);
    expect(mocks.saveRegistrationPolicy).not.toHaveBeenCalled();
    expect(saveButton().disabled).toBe(false);

    await act(async () => { saveButton().click(); });
    await flush();

    expect(mocks.saveRegistrationPolicy).toHaveBeenCalledTimes(1);
    expect(mocks.saveRegistrationPolicy).toHaveBeenCalledWith({
      signup_enabled: false, approval_required: true, google_signup_enabled: true,
      student_email_domain: "school.edu.tw",
    });
    expect(mocks.toast.success).toHaveBeenCalledTimes(1);
    await waitForClose();
    expect(dialog()).toBeNull();
  });

  test("the student email domain is trimmed, and cleared to null", async () => {
    mocks.getRegistrationPolicy.mockResolvedValue({
      signup_enabled: false, approval_required: false, google_signup_enabled: true,
      student_email_domain: "old.edu.tw",
    });
    await renderAndOpen();

    expect(domainInput().value).toBe("old.edu.tw");
    await act(async () => { setInputValue(domainInput(), "  new.edu.tw "); });
    await act(async () => { saveButton().click(); });
    await flush();
    expect(mocks.saveRegistrationPolicy).toHaveBeenLastCalledWith({
      signup_enabled: false, approval_required: false, google_signup_enabled: true,
      student_email_domain: "new.edu.tw",
    });
    await waitForClose();

    await act(async () => { openButton().click(); });
    await flush();
    expect(domainInput().value).toBe("new.edu.tw");
    await act(async () => { setInputValue(domainInput(), " "); });
    await act(async () => { saveButton().click(); });
    await flush();
    expect(mocks.saveRegistrationPolicy).toHaveBeenLastCalledWith(
      expect.objectContaining({ student_email_domain: null }),
    );
  });

  test("a failed save keeps the dialog and the draft", async () => {
    mocks.getRegistrationPolicy.mockResolvedValue({
      signup_enabled: false, approval_required: false, google_signup_enabled: true,
      student_email_domain: "old.edu.tw",
    });
    mocks.saveRegistrationPolicy.mockRejectedValueOnce(new Error("invalid"));
    await renderAndOpen();

    await act(async () => { setInputValue(domainInput(), "bad domain"); });
    await act(async () => { saveButton().click(); });
    await waitForClose();

    expect(mocks.toast.error).toHaveBeenCalledWith("invalid");
    expect(dialog()).toBeTruthy();
    expect(domainInput().value).toBe("bad domain");
    expect(saveButton().disabled).toBe(false);
  });

  test("closing with unsaved changes asks first; closing untouched does not", async () => {
    mocks.getRegistrationPolicy.mockResolvedValue({
      signup_enabled: true, approval_required: false, google_signup_enabled: true,
    });
    await renderAndOpen();

    /* 沒改就關：不問 */
    await act(async () => { dialogButton("AdminPage.cancel").click(); });
    await waitForClose();
    expect(mocks.confirm).not.toHaveBeenCalled();
    expect(dialog()).toBeNull();

    /* 改了再取消：使用者選留下 → 對話框與草稿都在 */
    await act(async () => { openButton().click(); });
    await flush();
    await act(async () => { policyCheckbox("AdminPage.signupEnabled").click(); });
    mocks.confirm.mockResolvedValueOnce(false);
    await act(async () => { dialogButton("AdminPage.cancel").click(); });
    await waitForClose();
    expect(mocks.confirm).toHaveBeenCalledTimes(1);
    expect(dialog()).toBeTruthy();
    expect(policyCheckbox("AdminPage.signupEnabled").checked).toBe(false);

    /* 再取消並選捨棄 → 關閉、不存；重開回到已存的值 */
    mocks.confirm.mockResolvedValueOnce(true);
    await act(async () => { dialogButton("AdminPage.cancel").click(); });
    await waitForClose();
    expect(dialog()).toBeNull();
    expect(mocks.saveRegistrationPolicy).not.toHaveBeenCalled();

    await act(async () => { openButton().click(); });
    await flush();
    expect(policyCheckbox("AdminPage.signupEnabled").checked).toBe(true);
  });
});
