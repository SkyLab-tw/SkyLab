// @vitest-environment happy-dom

/*
 * 克隆 Windows 範本時自訂的登入密碼要符合 Windows 的複雜度，否則機器建好也登不進去。
 * 後端克隆時會擋；這裡確認前端在送出前就列出規則並擋下，而不是等送出後才報錯。
 * 是不是 Windows 要另外查單一範本（清單不帶這一項）。
 */

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import TemplateCloneDialog from "./TemplateCloneDialog";
import { createTestQueryClient, withQueryClient } from "../../../queries/testing";

const mocks = vi.hoisted(() => ({
  clone: vi.fn(),
  get: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("../../../services/templates", () => ({ TemplatesService: { clone: mocks.clone, get: mocks.get } }));
vi.mock("../../../services/gpu", () => ({ GpuService: { listOptions: vi.fn() } }));
vi.mock("../../../hooks/useToast", () => ({ useToast: () => mocks.toast }));
vi.mock("react-i18next", async (importOriginal) => ({
  ...await importOriginal(),
  useTranslation: () => ({ t: (key) => key, i18n: { language: "zh-TW" } }),
}));

const VM_TEMPLATE = Object.freeze({ id: "tpl-w", name: "Win11", resource_type: "qemu", node: "pve-a", password_settable: true });

let host;
let root;

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

async function open(template = VM_TEMPLATE) {
  await act(async () => {
    root.render(withQueryClient(<TemplateCloneDialog template={template} onClose={vi.fn()} />, createTestQueryClient()));
  });
  await flush();
}

const passwordInput = () => document.querySelector("#clone-password");
const rules = () => document.querySelector('[role="list"][aria-label="PasswordRules.label"]');

async function typePassword(value) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(passwordInput(), value);
    passwordInput().dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function submit() {
  const button = [...document.querySelectorAll("button")]
    .find((item) => item.textContent.includes("TemplateCloneDialog.submit") || item.textContent.includes("TemplateCloneDialog.clone"));
  expect(button, "找不到送出按鈕").toBeDefined();
  await act(async () => button.click());
  await flush();
}

beforeEach(() => {
  vi.resetAllMocks();
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  mocks.clone.mockResolvedValue({ tasks: [{}] });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

describe("TemplateCloneDialog：Windows 範本的自訂密碼", () => {
  test("輸入後列出 Windows 的規則；不合規則時擋下不送出，並把欄位標成有問題", async () => {
    mocks.get.mockResolvedValue({ ...VM_TEMPLATE, is_windows: true });
    await open();
    expect(mocks.get).toHaveBeenCalledWith("tpl-w", expect.anything());

    /* 留空由系統產生，不必對照規則 */
    expect(rules()).toBeNull();

    /* 8 個字元但只有小寫：過得了長度，過不了 Windows 的複雜度 */
    await typePassword("abcdefgh");
    expect(rules()).not.toBeNull();
    await submit();
    expect(mocks.clone).not.toHaveBeenCalled();
    expect(mocks.toast.error).toHaveBeenCalledWith("TemplateCloneDialog.passwordWindowsInvalid");
    expect(passwordInput().getAttribute("aria-invalid")).toBe("true");

    /* 改了密碼就收起紅字；合規則的密碼照常送出 */
    await typePassword("Lab#2026ok");
    expect(passwordInput().hasAttribute("aria-invalid")).toBe(false);
    await submit();
    expect(mocks.clone).toHaveBeenCalledWith("tpl-w", expect.objectContaining({ login_password: "Lab#2026ok" }));
  });

  test("不是 Windows 的範本不列這份規則，只看 8 個字元", async () => {
    mocks.get.mockResolvedValue({ ...VM_TEMPLATE, is_windows: false });
    await open();

    await typePassword("abcdefgh");
    expect(rules()).toBeNull();
    await submit();
    expect(mocks.clone).toHaveBeenCalledWith("tpl-w", expect.objectContaining({ login_password: "abcdefgh" }));
  });

  test("容器範本與不能設密碼的範本不必查是不是 Windows", async () => {
    await open({ ...VM_TEMPLATE, id: "tpl-l", resource_type: "lxc" });
    expect(mocks.get).not.toHaveBeenCalled();

    await act(async () => root.unmount());
    root = createRoot(host);
    await open({ ...VM_TEMPLATE, id: "tpl-n", password_settable: false });
    expect(mocks.get).not.toHaveBeenCalled();
    expect(passwordInput()).toBeNull();
  });

  test("查不到是不是 Windows 時不擋：交給後端克隆時把關", async () => {
    mocks.get.mockRejectedValue(new Error("PVE 連線失敗"));
    await open();

    await typePassword("abcdefgh");
    expect(rules()).toBeNull();
    await submit();
    expect(mocks.clone).toHaveBeenCalledTimes(1);
    expect(mocks.toast.error).not.toHaveBeenCalled();
  });
});
