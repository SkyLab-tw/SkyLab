// @vitest-environment happy-dom

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/*
 * 學生名單的工具列與鎖定狀態：標題、人數與機器數、搜尋、匯入／加入同一列；
 * 送出建機後（不是準備中）不擺停用鈕，改一行鎖定說明，也不留移除那一欄。
 */

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";
import { Students } from "./ClassWorkspacePage";
import { withQueryClient } from "../../../queries/testing";
import i18n from "../../../i18n";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), info: vi.fn(), success: vi.fn(), warning: vi.fn() } }));
vi.mock("../../../components/ConfirmDialog/ConfirmProvider", () => ({ useConfirm: () => vi.fn() }));

const tr = (key, options) => i18n.t(`ClassWorkspacePage.${key}`, { ns: "teaching", ...options });

const STUDENTS = [
  { id: "s1", full_name: "Amy", email: "amy@example.com", joined_at: "2026-08-30T00:00:00Z", machines: [{ vmid: 101, status: "completed" }] },
  { id: "s2", full_name: "Ben", email: "ben@example.com", joined_at: "2026-08-30T00:00:00Z", machines: [{ vmid: 102, status: "completed" }] },
];

let cleanup = null;
afterEach(() => {
  cleanup?.();
  cleanup = null;
});

async function mount(status) {
  const item = { id: "c1", status, students: STUDENTS, nodes: [{ id: "n1", name: "Web" }], readyMachines: 2, totalMachines: 2 };
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(withQueryClient(<Students item={item} onRefresh={() => {}} />));
  });
  cleanup = () => {
    act(() => root.unmount());
    container.remove();
  };
  return container;
}

const buttonLabels = (container) => [...container.querySelectorAll("button")].map((button) => button.textContent);

test("準備中的班級：標題、人數、搜尋、匯入與加入在同一列，每列有移除鈕", async () => {
  const container = await mount("planning");
  const heading = container.querySelector("h2");
  expect(heading.textContent).toBe(tr("studentsTitle"));
  const toolbar = heading.closest("div").parentElement;
  expect(toolbar.textContent).toContain(tr("peopleCountUnit", { count: 2 }));
  expect(toolbar.textContent).toContain(tr("machinesReadyShort", { ready: 2, total: 2 }));
  expect(toolbar.querySelector('input[type="search"], input[placeholder]')).toBeTruthy();
  expect(toolbar.querySelector('[data-guide="class-students-actions"]')).toBeTruthy();
  expect(buttonLabels(toolbar).join("|")).toContain(tr("addStudentsBtn"));

  // 只有一個標題：名單面板不再重複「成員列表（N 人）」
  expect(container.querySelectorAll("h2")).toHaveLength(1);
  expect(container.querySelector('[data-guide="class-students-list"]').contains(heading)).toBe(false);
  expect(container.querySelectorAll('[data-guide="class-students-remove"]')).toHaveLength(2);
});

test("送出建機後：不擺停用的匯入／加入鈕，改一行鎖定說明；移除欄連空欄都不留", async () => {
  const container = await mount("active");
  expect(container.querySelector('[data-guide="class-students-actions"]')).toBeNull();
  expect(container.textContent).toContain(tr("rosterLockedNote"));
  expect(buttonLabels(container).some((label) => label.includes(tr("importCsvBtn")))).toBe(false);
  expect([...container.querySelectorAll("button")].some((button) => button.disabled)).toBe(false);

  const rows = container.querySelectorAll('[data-guide="class-students-list"] article');
  expect(rows).toHaveLength(2);
  // 學生、VMID、機器、加入日期，沒有第 5 格
  expect(rows[0].children).toHaveLength(4);
  expect(container.querySelector('[data-guide="class-students-remove"]')).toBeNull();
});
