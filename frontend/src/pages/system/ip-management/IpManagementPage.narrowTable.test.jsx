// @vitest-environment happy-dom
/* 窄版收欄（useTableFit）：表格區變窄時依序收起備註、分配時間、VMID；
   VMID、備註收進 IP 底下（單行截斷），分配時間收到用途徽章底下（只寫日期，完整時間在 title） */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { withQueryClient } from "../../../queries/testing";
import { formatDate, formatDateTime } from "../../../utils/formatDate";

const mocks = vi.hoisted(() => ({
  listAllocations: vi.fn(),
  getSubnet: vi.fn(),
  getStatus: vi.fn(),
  t: (key) => key,
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("../../../services/ipManagement", () => ({
  IpManagementService: {
    listAllocations: mocks.listAllocations,
    getSubnet: mocks.getSubnet,
    getStatus: mocks.getStatus,
  },
}));
vi.mock("react-i18next", async (importOriginal) => ({ ...await importOriginal(), useTranslation: () => ({ t: mocks.t }) }));
vi.mock("../../../contexts/AuthContext", () => ({ useAuth: () => ({ user: { id: "me", role: "admin", is_superuser: true } }) }));
vi.mock("../../../hooks/useToast", () => ({ useToast: () => mocks.toast }));
vi.mock("../../../components/ConfirmDialog/ConfirmProvider", () => ({ useConfirm: () => vi.fn() }));
vi.mock("../../../components/PageHeader/PageHeader", () => ({ default: () => null }));

const { default: IpManagementPage } = await import("./IpManagementPage");

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const originalClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
let tableWidth;
let host;
let root;

async function flush() {
  for (let round = 0; round < 3; round += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
      for (let i = 0; i < 5; i += 1) await Promise.resolve();
    });
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  /* happy-dom 沒有版面：表格區（data-guide="ip-table"）的寬度由測試指定 */
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get() { return this.getAttribute("data-guide") === "ip-table" ? tableWidth : 0; },
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  if (originalClientWidth) Object.defineProperty(HTMLElement.prototype, "clientWidth", originalClientWidth);
  else delete HTMLElement.prototype.clientWidth;
});

const ALLOCATED_AT = "2026-11-17T06:30:15Z";
/* 系統配發的 VM：備註就是「VMID 101」；管理員手動保留的：備註是自己寫的、沒有 VMID */
const VM = { ip_address: "192.168.100.254", purpose: "vm", vmid: 101, allocated_at: ALLOCATED_AT, description: "VMID 101" };
const RESERVED = { ip_address: "192.168.100.10", purpose: "reserved", vmid: null, allocated_at: ALLOCATED_AT, description: "印表機" };

async function renderAt(width) {
  tableWidth = width;
  mocks.listAllocations.mockResolvedValue({ allocations: [VM, RESERVED] });
  mocks.getSubnet.mockResolvedValue({ cidr: "192.168.100.0/24", bridge_name: "vmbr1", total_ips: 254, used_ips: 2, available_ips: 252 });
  mocks.getStatus.mockResolvedValue({ configured: true });
  await act(async () => { root.render(withQueryClient(<IpManagementPage />)); });
  await flush();
}

const headers = () => [...host.querySelectorAll("thead th")].map((th) => th.textContent);
const rowCells = (index) => [...host.querySelectorAll("tbody tr")[index].children];
/* IP 欄的文字行（圖示後面那一塊）：IP、收進來的 VMID、備註各一行 */
const addressLines = (cell) => [...cell.firstElementChild.lastElementChild.children].map((line) => line.textContent);

test("1366 筆電（約 929px）全部欄都放得下，不收欄；備註 td 帶全文 title", async () => {
  await renderAt(929);
  expect(headers()).toEqual([
    "IpManagementPage.colIpAddress",
    "IpManagementPage.colPurpose",
    "VMID",
    "IpManagementPage.colAllocatedAt",
    "IpManagementPage.colDescription",
  ]);
  expect(host.querySelector("table").style.minWidth).toBe("860px");
  const cells = rowCells(1);
  expect(cells[4].getAttribute("title")).toBe("印表機");
  expect(addressLines(cells[0])).toEqual(["192.168.100.10"]);
});

test("1100 寬視窗（約 678px）：備註收進 IP 底下，其他欄照舊", async () => {
  await renderAt(678);
  expect(headers()).toEqual([
    "IpManagementPage.colIpAddress",
    "IpManagementPage.colPurpose",
    "VMID",
    "IpManagementPage.colAllocatedAt",
  ]);
  expect(host.querySelectorAll("colgroup col")).toHaveLength(4);
  const [address] = rowCells(1);
  expect(addressLines(address)).toEqual(["192.168.100.10", "印表機"]);
  expect(host.querySelector("table").hasAttribute("data-overflow")).toBe(false);
});

test("1440 開著 AI 助手（約 567px）：分配時間收到用途徽章底下，只寫日期、完整時間在 title", async () => {
  await renderAt(567);
  expect(headers()).toEqual(["IpManagementPage.colIpAddress", "IpManagementPage.colPurpose", "VMID"]);
  const [, purpose, vmid] = rowCells(0);
  expect(vmid.textContent).toBe("101");
  const line = purpose.lastElementChild;
  expect(line.textContent).toBe(`IpManagementPage.colAllocatedAt ${formatDate(ALLOCATED_AT)}`);
  expect(line.getAttribute("title")).toBe(formatDateTime(ALLOCATED_AT));
  expect(host.querySelector("table").hasAttribute("data-overflow")).toBe(false);
});

test("手機（約 448px）：VMID 也收進 IP 底下；備註已經寫了 VMID 就不重複，全部收完不用橫捲", async () => {
  await renderAt(448);
  expect(headers()).toEqual(["IpManagementPage.colIpAddress", "IpManagementPage.colPurpose"]);
  expect(host.querySelector("table").hasAttribute("data-overflow")).toBe(false);

  /* VM：備註「VMID 101」已經說了 VMID，只留一行 */
  const [vmAddress] = rowCells(0);
  expect(addressLines(vmAddress)).toEqual(["192.168.100.254", "VMID 101"]);

  /* 手動保留：沒有 VMID，只有備註 */
  const [reservedAddress] = rowCells(1);
  expect(addressLines(reservedAddress)).toEqual(["192.168.100.10", "印表機"]);
});

test("備註跟 VMID 不同時兩行都留：VMID 一行、備註一行", async () => {
  tableWidth = 448;
  mocks.listAllocations.mockResolvedValue({
    allocations: [{ ...VM, description: "期末專題 web 伺服器" }],
  });
  mocks.getSubnet.mockResolvedValue({ cidr: "192.168.100.0/24", bridge_name: "vmbr1" });
  mocks.getStatus.mockResolvedValue({ configured: true });
  await act(async () => { root.render(withQueryClient(<IpManagementPage />)); });
  await flush();

  const [address] = rowCells(0);
  expect(addressLines(address)).toEqual(["192.168.100.254", "VMID 101", "期末專題 web 伺服器"]);
});
