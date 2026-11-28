// @vitest-environment happy-dom
/*
 * 規則編號：Proxmox 的位置（pos）從 0 起算，給人看的編號從 1 開始。
 * 資源詳情的防火牆卡一直是從 1 開始；防火牆頁的規則面板原本直接印 pos，
 * 同一條規則在兩頁編號不同（一頁寫 #0、一頁寫第 1 條）。
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const fw = vi.hoisted(() => ({
  getVmRules: vi.fn(),
  getVmOptions: vi.fn(),
  deleteVmRule: vi.fn(),
  updateVmRule: vi.fn(),
}));
const confirmCalls = vi.hoisted(() => []);

/* 帶參數的字串把參數印出來，才看得到確認視窗講的是第幾條；t 要是穩定參照 */
const i18n = vi.hoisted(() => ({
  t: (key, params) => (params ? `${key}${JSON.stringify(params)}` : key),
}));
vi.mock("react-i18next", () => ({ useTranslation: () => i18n }));
vi.mock("../../services/firewall", () => fw);
vi.mock("../ConnectionDialog/ConnectionDialog", () => ({ default: () => null }));
vi.mock("../LoadingState/LoadingState", () => ({ default: () => <div data-testid="loading" /> }));
vi.mock("../../hooks/useToast", () => ({ useToast: () => ({ error: vi.fn(), success: vi.fn() }) }));
vi.mock("../ConfirmDialog/ConfirmProvider", () => ({
  useConfirm: () => async (options) => {
    confirmCalls.push(options);
    return true;
  },
}));
vi.mock("../../contexts/AuthContext", () => ({ useAuth: () => ({ user: { role: "admin" } }) }));

import { createTestQueryClient, withQueryClient } from "../../queries/testing";
import RulesPanel from "./RulesPanel";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

const RULES = [
  { pos: 0, type: "in", action: "ACCEPT", enable: 1, comment: "ssh" },
  { pos: 1, type: "in", action: "DROP", enable: 1, comment: "web" },
];

let host;
let root;

beforeEach(() => {
  Object.values(fw).forEach((fn) => fn.mockReset());
  confirmCalls.length = 0;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  document.body.innerHTML = "";
});

test("規則從 #1 開始編號；刪除確認講同一個號碼，送給後端的仍是 0 起算的位置", async () => {
  fw.getVmRules.mockResolvedValue(RULES);
  fw.getVmOptions.mockResolvedValue({ enable: 1 });
  fw.deleteVmRule.mockResolvedValue({});

  await act(async () => root.render(withQueryClient(
    <MemoryRouter><RulesPanel node={{ vmid: 9, name: "N" }} onClose={() => {}} /></MemoryRouter>,
    createTestQueryClient(),
  )));
  await flush();

  const numbers = [...host.querySelectorAll('[class*="rulePos"]')].map((item) => item.textContent);
  expect(numbers).toEqual(["#1", "#2"]);

  /* 刪第二條（web）：畫面上是 #2，Proxmox 的位置是 1 */
  await act(async () => document.querySelectorAll("[title='RulesPanel.deleteRule']")[1].click());
  await flush();
  expect(confirmCalls).toHaveLength(1);
  expect(confirmCalls[0].message).toBe('RulesPanel.deleteRuleMessage{"pos":2}');
  expect(fw.deleteVmRule).toHaveBeenCalledWith(9, 1);
});
